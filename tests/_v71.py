#!/usr/bin/env python3
"""Per-frame diagnostics leave the ledger, and an unknown verdict cannot flood.

The freeze gate recorded one entry per judged frame under a fourth verdict,
"info", that audit.counts() ignored and audit_fmt printed: 31 rows a render,
1,023 lines and 113,657 characters in one Discord message. A reader needs the
aggregate, not the rows.

Three properties:
  1. pick() returns a summary whose numbers match the rows it judged, and the
     rows land in a debug file that rotates.
  2. format_ledger skips a verdict it does not know and says so on stderr, so
     the NEXT gate inventing a verdict is reported rather than printed 31 times.
  3. The check count in the header counts exactly the pass/warn/reject
     entries, and the freeze section's own numbers agree with it.
"""

import io
import json
import os
import sys
import tempfile
import shutil
import types
import contextlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import audit        # noqa: E402
import audit_fmt    # noqa: E402
import freeze_pick  # noqa: E402


def rows(n, good_at=None):
    """n judged frames, optionally one qualifying at index good_at."""
    out = []
    for i in range(n):
        ok = i == good_at
        out.append((144.27 + i * 0.2, ok,
                    0.90 if ok else 0.72,
                    "man in dark cap (%s)" % ("turned toward camera" if ok
                                              else "profile / blurred")))
    return out


def test_summary_matches_rows():
    r = rows(31, good_at=10)
    s = freeze_pick.summarise(r, 149.0)
    assert s["frames"] == 31, s
    assert s["qualified"] == 1, s
    assert s["window"] == (r[0][0], r[-1][0]), s
    assert s["picked"] == r[10][0], s
    assert abs(s["best_conf"] - 0.90) < 1e-9, s
    assert s["top_reason"][1] == 30, s
    assert "profile" in s["top_reason"][0], s

    # No qualifying frame: the verdict and the counts must agree, and the best
    # confidence must still be reported -- it is the number that says whether
    # the gate was close or nowhere near.
    s = freeze_pick.summarise(rows(31), 149.0)
    assert s["picked"] is None and s["qualified"] == 0, s
    assert abs(s["best_conf"] - 0.72) < 1e-9, s
    assert s["min_conf"] == freeze_pick.MIN_CONF, s


def test_debug_file_rotates():
    tmp = tempfile.mkdtemp(prefix="v71-")
    try:
        paths = []
        for i in range(8):
            # The stamp has one-second resolution, so write through the real
            # function but give each file a distinct render_id; rotation is by
            # sorted name and the id leads.
            p = freeze_pick.write_debug(
                rows(5), {"render_id": "clip_%02d" % i}, directory=tmp, keep=3)
            assert p, "write_debug returned nothing"
            paths.append(p)

        left = sorted(f for f in os.listdir(tmp) if f.endswith(".freeze.json"))
        assert len(left) == 3, f"keep=3 left {len(left)}: {left}"
        # The newest survive, the oldest are gone.
        assert left == sorted(os.path.basename(p) for p in paths[-3:]), left

        # The file holds the rows and the thresholds they were judged against.
        data = json.loads(open(os.path.join(tmp, left[-1])).read())
        assert len(data["frames"]) == 5, data
        assert data["threshold"]["min_conf"] == freeze_pick.MIN_CONF, data
        assert data["meta"]["render_id"] == "clip_07", data

        # A debug file that cannot be written must not fail a render.
        assert freeze_pick.write_debug(
            rows(2), {"render_id": "x"}, directory="/proc/nope") == ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_pick_sends_rows_to_debug_not_the_ledger():
    tmp = tempfile.mkdtemp(prefix="v71-pick-")
    old_dir, old_look = freeze_pick.DEBUG_DIR, freeze_pick.LOOKBACK
    try:
        freeze_pick.DEBUG_DIR = tmp
        freeze_pick.LOOKBACK = 1.0
        fake = types.ModuleType("ai")
        fake.vision_json = lambda *a, **k: {
            "ok": False, "confidence": 0.72,
            "most_readable": "someone else", "why": "profile"}
        sys.modules["ai"] = fake
        grab = freeze_pick._grab
        freeze_pick._grab = lambda v, t: b"x" * 2000

        led = audit.start()
        try:
            picked, summary = freeze_pick.pick(
                "dummy.mp4", 10.0, "Gibran", meta={"render_id": "clip_1"})
        finally:
            freeze_pick._grab = grab

        assert picked is None, picked
        assert summary["frames"] > 1, summary

        # Nothing per-frame reached the ledger: pick() takes no audit callback
        # in the render path, so the only freeze entries are the ones job.py
        # records itself -- here, none.
        assert led.entries == [], led.entries

        # The rows are on disk instead.
        files = [f for f in os.listdir(tmp) if f.endswith(".freeze.json")]
        assert len(files) == 1, files
        data = json.loads(open(os.path.join(tmp, files[0])).read())
        assert len(data["frames"]) == summary["frames"], data
        assert summary["debug"].endswith(files[0]), summary
    finally:
        audit.stop()
        freeze_pick.DEBUG_DIR, freeze_pick.LOOKBACK = old_dir, old_look
        shutil.rmtree(tmp, ignore_errors=True)


def ledger(entries, totals):
    return {"title": "Judul", "clip": "/x/clip_1.mp4", "totals": totals,
            "duration_sec": 28.0, "mood": "emotional", "warnings": [],
            "entries": entries}


def test_unknown_verdict_is_skipped_and_reported():
    entries = [{"checker": "freeze", "target": "subject",
                "verdict": audit.BRIEF, "reason": "Gibran", "detail": ""}]
    for i in range(31):
        entries.append({"checker": "freeze", "target": "freeze-pick",
                        "verdict": "info",
                        "reason": "%.2fs no conf 0.72" % (144.27 + i * .2),
                        "detail": ""})
    entries.append({"checker": "freeze", "target": "pick",
                    "verdict": "reject", "reason": "no qualifying frame",
                    "detail": "31 frame dicek, 0 lolos"})

    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        body = audit_fmt.format_ledger(
            ledger(entries, {"pass": 0, "reject": 1, "warn": 0}))

    assert "freeze-pick" not in body, "per-frame rows still reach the message"
    assert body.count("no qualifying frame") == 1, body
    assert len(body) < 2000, f"{len(body)} chars for one render"

    msg = err.getvalue()
    assert "unknown verdict" in msg, f"nothing warned: {msg!r}"
    assert "31" in msg and "'info'" in msg, msg
    assert "freeze" in msg, msg


def test_check_count_matches_the_sections():
    """"N cek" counts decisions, and the sections carry exactly N of them."""
    entries = [
        {"checker": "language", "target": "transcript review",
         "verdict": "pass", "reason": "no mishearings found", "detail": ""},
        {"checker": "freeze", "target": "subject", "verdict": audit.BRIEF,
         "reason": "Gibran", "detail": ""},
        {"checker": "freeze", "target": "window", "verdict": audit.BRIEF,
         "reason": "144.27s–150.27s, 31 frame", "detail": "ambang conf 0.55"},
        {"checker": "freeze", "target": "pick", "verdict": "reject",
         "reason": "no qualifying frame",
         "detail": "31 frame dicek, 0 lolos · conf terbaik 0.48"},
    ]
    decided = [e for e in entries
               if e["verdict"] in (audit.PASS, audit.REJECT, audit.WARN)]
    body = audit_fmt.format_ledger(
        ledger(entries, {"pass": 1, "reject": 1, "warn": 0}))

    assert f"{len(decided)} cek" in body, \
        f"header disagrees with {len(decided)} decisions:\n{body}"
    # Every decision shows up as exactly one marked line, so the count in the
    # header can be checked against the body by eye.
    marked = [ln for ln in body.split("\n")
              if ln[:1] in ("✅", "❌", "⚠️") or ln.startswith("⚠️")]
    assert len(marked) == len(decided), f"{len(marked)} marked lines:\n{body}"
    # And the reject keeps its aggregate, which is what replaced the 31 rows.
    assert "31 frame dicek" in body, body
    # The brief is a question, not a decision: present, uncounted.
    assert "144,27s" in body, "the window brief was dropped"


def main():
    test_summary_matches_rows()
    test_debug_file_rotates()
    test_pick_sends_rows_to_debug_not_the_ledger()
    test_unknown_verdict_is_skipped_and_reported()
    test_check_count_matches_the_sections()
    print("_v71: ok (rows to debug + rotation, unknown verdict skipped, "
          "counts agree)")


if __name__ == "__main__":
    main()
