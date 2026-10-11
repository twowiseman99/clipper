#!/usr/bin/env python3
"""Translation is whole-string only, and the error fields outlive truncation.

Two fixes, one failure mode between them: content a reader needs being
silently mangled or thrown away.

#4  The phrase table used to replace any key found ANYWHERE in a string, so
    strings it did not describe came out half-translated: the model's own
    "right edge of frame" became "right edge dari frame", the field name
    `subject` became `subjek` mid-English-clause, and `--clip-type` became
    `--klip-type` -- a flag that does not exist, printed as if it could be
    pasted. Now: whole-string match in PHRASES, or whole-string fullmatch in
    NUMERIC, or the English ships untouched.

#6  A render over the message budget used to be split across as many messages
    as it took (179 of them) and then truncated anyway, losing whatever fell
    off the end. Now the NARRATIVE is dropped and the issue block kept, with
    the cut stated and the debug path named.

The corrupted forms are listed HERE rather than derived from audit_fmt, so
this test cannot agree with the bug the way a tautological one would.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import audit        # noqa: E402
import audit_fmt    # noqa: E402

# Exactly what the operator read in the channel. Each must be IMPOSSIBLE now.
CORRUPTED = [
    "dari frame",        # "right edge of frame" -> word swapped mid-sentence
    "dari cro",          # "...at right edge of crowd", truncated as sent
    "--klip-type",       # a CLI flag rewritten into one that does not exist
    "in left dari",      # "Foreground man in left of frame"
    "klip_",             # a file name rewritten, so the path stops resolving
]

# English the model wrote, which must pass through verbatim: a phrase table
# cannot translate a sentence it does not describe.
PASSTHROUGH = [
    "right edge of frame",
    "woman in red jacket at right edge of crowd",
    "foreground man in left of frame, seen in profile",
    "--clip-type",
    "man in dark cap in the background crowd",
    "turned toward camera and lit",
]

# Strings the tables DO describe completely, with what they must become.
TRANSLATED = {
    "no mishearings found": "ga ada salah dengar",
    "subject": "subjek",
    "66 word(s) of transcript": "66 kata transkrip",
    "hook 70 / title 70 chars": "hook 70 / judul 70 huruf",
    "kept 'hype' (explicit --clip-type)": "tetep 'hype' (dipaksa --clip-type)",
    "last 5s of clip_1791642180_122.mp4":
        "5s terakhir dari clip_1791642180_122.mp4",
}


def test_no_mid_sentence_substitution():
    for text in PASSTHROUGH:
        got = audit_fmt.id_text(text)
        assert got == text, f"rewrote {text!r} -> {got!r}"
    for text, want in TRANSLATED.items():
        got = audit_fmt.id_text(text)
        assert got == want, f"{text!r} -> {got!r}, wanted {want!r}"


def test_corrupted_forms_cannot_be_produced():
    """Run every real ledger string through and look for the damage."""
    import glob
    import json
    checked = 0
    for path in glob.glob(os.path.join(ROOT, "jobs", "*.audit.json")):
        data = json.load(open(path, encoding="utf-8"))
        texts = []
        for e in data.get("entries", []):
            texts += [e.get("target", ""), e.get("reason", ""),
                      e.get("detail", "")]
        for w in data.get("warnings", []):
            texts.append(audit_fmt.split_detail(w)[0])
        for t in texts:
            if not t:
                continue
            got = audit_fmt.id_text(t)
            checked += 1
            for bad in CORRUPTED:
                assert bad not in got, \
                    f"{bad!r} in {got!r} (from {t!r}) in {path}"
    assert checked > 100, f"only {checked} strings checked"


def test_filenames_survive_both_paths():
    """A path is not prose, on the match path and the no-match path alike."""
    for text in ("last 5s of clip_1791642180_122.mp4",
                 "mood hype -> hype_dj_nansuya_gang.mp3",
                 "debug jobs/freeze-debug/clip_1.freeze.json"):
        got = audit_fmt.id_text(text)
        for token in text.split():
            if "." in token and "/" in token or token.endswith(
                    (".mp4", ".mp3", ".json")):
                assert token in got, f"{token!r} lost from {got!r}"


def ledger_with(warnings, entries, totals):
    return {"title": "Gibran Minta Maaf ke Ibu Korban MBG",
            "clip": "/home/ubuntu/clipper/jobs/clip_1791642180_122.mp4",
            "totals": totals, "duration_sec": 28.0, "mood": "emotional",
            "warnings": warnings, "entries": entries}


WARN = (
    "musik: --clip-type minta 'hype' tapi transkripnya kebaca 'emotional', "
    "dua-duanya tabrakan — tetep pakai 'hype' karena clip type diminta "
    "eksplisit | stage: music | source: job.py:run (bgm._clashes) | trigger: "
    "preset 'hype' vs transcript 'emotional' | error: mood clash, kept 'hype' "
    "(explicit --clip-type) | fix: pakai --mood emotional | fallback: preset "
    "'hype' dipakai buat milih lagu")

REJECT = {
    "checker": "freeze", "target": "pick", "verdict": "reject",
    "reason": "no qualifying frame",
    "detail": "31 frame dicek, 0 lolos · conf terbaik 0.48 < ambang 0.55 "
              "| stage: freeze | source: freeze_pick.py:pick | video: "
              "144.27s-150.27s (31 frame, 0 lolos) | trigger: conf terbaik "
              "0.48 vs ambang 0.55 | error: no qualifying frame | fallback: "
              "mechanical frame | debug: /home/ubuntu/clipper/jobs/"
              "freeze-debug/clip_1791642180_122.20261011.freeze.json"}


def test_detail_fields_are_structured_and_untranslated():
    body = audit_fmt.format_ledger(
        ledger_with([WARN], [REJECT], {"pass": 7, "reject": 1, "warn": 1}))

    assert "**Perlu dicek sebelum upload:**" in body, body
    # Every field from rule 2/6 present and labelled.
    for field in ("stage", "source", "video", "trigger", "error", "fallback",
                  "debug"):
        assert f"{field}" in body and f": " in body, f"{field} missing"
    # Names, flags, functions and paths verbatim -- never translated.
    for literal in ("freeze_pick.py:pick", "--clip-type", "bgm._clashes",
                    "no qualifying frame", "job.py:run",
                    "freeze-debug/clip_1791642180_122.20261011.freeze.json"):
        assert literal in body, f"{literal!r} lost or translated:\n{body}"
    # Wrapped in a code block so the fields line up on a phone.
    assert body.count("```") >= 2 and body.count("```") % 2 == 0, body
    # The friendly name AND the internal one, per rule 2/6.
    assert "Pemilih Gambar (freeze)" in body, body
    # Measured positions use the operator's decimal comma.
    assert "144,27s-150,27s" in body, body


def test_narrative_is_cut_before_the_error_fields():
    entries = [REJECT]
    for i in range(40):
        entries.append({"checker": "edit", "target": "cutaways placed",
                        "verdict": "pass", "reason": "none",
                        "detail": "filler line %d %s" % (i, "y" * 60)})
    data = ledger_with([WARN], entries, {"pass": 41, "reject": 1, "warn": 1})

    full = audit_fmt.format_ledger(data)
    assert len(full) > 1500, f"fixture too small to test the cut: {len(full)}"

    limit = 1500
    cut = audit_fmt.format_ledger(data, limit=limit)
    assert len(cut) <= limit, f"{len(cut)} chars over a {limit} limit"

    # The narrative went; the error block stayed whole.
    assert "filler line" not in cut, "narrative survived instead of the fields"
    for literal in ("freeze_pick.py:pick", "144,27s-150,27s",
                    "no qualifying frame", "mechanical frame"):
        assert literal in cut, f"{literal!r} was cut:\n{cut}"
    # The cut is stated, not silent, and points at the debug file.
    assert "dipotong" in cut, cut
    assert ".freeze.json" in cut, cut
    # Header survives: a reader needs to know WHICH render this is.
    assert "clip_1791642180_122" in cut and "🎬" in cut, cut


def test_one_render_fits_three_messages():
    import audit_watch
    data = ledger_with([WARN], [REJECT] + [
        {"checker": "language", "target": "transcript review",
         "verdict": "pass", "reason": "no mishearings found", "detail": ""}],
        {"pass": 8, "reject": 1, "warn": 1})
    text = audit_watch.format_ledger(data)
    parts = audit_watch.chunk(text)
    assert len(parts) <= audit_watch.MAX_MESSAGES, \
        f"{len(parts)} messages for one render"
    assert len(text) <= audit_watch.DISCORD_LIMIT * audit_watch.MAX_MESSAGES


def main():
    test_no_mid_sentence_substitution()
    test_corrupted_forms_cannot_be_produced()
    test_filenames_survive_both_paths()
    test_detail_fields_are_structured_and_untranslated()
    test_narrative_is_cut_before_the_error_fields()
    test_one_render_fits_three_messages()
    print("_v72: ok (whole-string translation, error fields survive the cut)")


if __name__ == "__main__":
    main()
