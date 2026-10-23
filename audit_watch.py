#!/usr/bin/env python3
"""Deliver each render's division ledger to Discord.

Why this exists: audit.py built a full review every render — six divisions,
each with the brief it was GIVEN and the verdicts it returned — and then
printed it to stdout and dropped it. The operator pointed a Discord channel at
"log agency agent" and saw an empty channel, because nothing had ever written
the ledger down, let alone sent it.

job.py now saves <clip>.audit.json next to every clip. This script finds the
ones it has not reported yet and posts them, newest last, then records what it
sent so a second run stays quiet.

Run with --once for a single pass (what the cron job does), or --selftest for
the offline checks.
"""

import argparse
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_fmt  # noqa: E402  (path set above so cron can run from anywhere)

JOBS = pathlib.Path(os.environ.get("CLIPPER_JOBS", "/home/ubuntu/clipper/jobs"))
STATE = pathlib.Path(os.environ.get(
    "AUDIT_WATCH_STATE", "/home/ubuntu/.hermes/audit-watch/state.json"))
# Discord rejects a message over 2000 characters outright. The ledger for a
# b-roll render runs past that, so it is split on line boundaries rather than
# truncated — losing the tail would hide exactly the division that failed.
DISCORD_LIMIT = 1900

# Discord's edge returns 403 to urllib's default User-Agent. Identify the
# sender instead; see post() for the measured both-ways control.
USER_AGENT = "clipper-audit-watch/1.0 (+https://github.com/twowiseman)"
# How many messages ONE render may occupy. Splitting on line boundaries kept
# every line, which is right for a message that is a few hundred lines over
# and catastrophic for one that is a thousand: a single render took 179
# messages and 328,206 characters were truncated anyway. Past this budget the
# formatter drops its narrative and keeps the error fields, so the cut is a
# decision rather than whatever fell off the end.
MAX_MESSAGES = int(os.environ.get("AUDIT_WATCH_MAX_MESSAGES", "3"))

# How many RENDERS one tick may deliver. MAX_MESSAGES caps ONE ledger;
# nothing capped how many ledgers go out TOGETHER. run_once() looped over
# every pending file, so N renders waiting = N x up to 3 messages fired in
# one burst. That is the shape that already bit us once: the comment above
# records a single render taking 179 messages, and the state file records a
# 70-ledger backlog that the operator deliberately chose NOT to replay
# because clearing it would be "a 70-message burst, ~84k chars, not undoable".
#
# A cap turns a burst into a queue: the cron job runs every 15 minutes, so
# leftovers go out on the next tick instead of all at once. Nothing is lost —
# a ledger is only marked sent after it is actually POSTED.
MAX_LEDGERS = int(os.environ.get("AUDIT_WATCH_MAX_LEDGERS", "4"))

def _narrator():
    """The Phase 2 narration callable, or None when it cannot be had.

    Imported lazily and inside a try: this watcher runs from cron every 15
    minutes and its job is to deliver the log. A missing module, a missing
    router or a missing key must cost the narration only -- never the
    message. Returns None, which format_ledger treats as "no narration".
    """
    try:
        import audit_narrate
    except Exception as exc:
        print(f"audit_watch: narasi ga dipasang ({type(exc).__name__}: "
              f"{str(exc)[:80]})", file=sys.stderr)
        return None
    return audit_narrate.narrate if audit_narrate.ENABLED else None


def load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"sent": []}


def save_state(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))


def pending(state):
    """Ledgers on disk that have not been reported, oldest first."""
    sent = set(state.get("sent", []))
    found = []
    for p in JOBS.glob("*.audit.json"):
        if p.name in sent:
            continue
        try:
            found.append((p.stat().st_mtime, p))
        except OSError:
            continue
    return [p for _, p in sorted(found)]


def chunk(text, limit=DISCORD_LIMIT):
    """Split on line boundaries, never mid-line.

    A ledger line is one division's verdict; cutting one in half produces a
    report that reads as if a gate said something it did not.
    """
    out, buf = [], ""
    for line in text.split("\n"):
        # A single line longer than the limit is hard-split: nothing sensible
        # to do, and dropping it would be worse.
        while len(line) > limit:
            if buf:
                out.append(buf)
                buf = ""
            out.append(line[:limit])
            line = line[limit:]
        if len(buf) + len(line) + 1 > limit:
            out.append(buf)
            buf = line
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf:
        out.append(buf)
    return out


def format_ledger(data):
    """The message body.

    Built from `entries` by audit_fmt rather than from the saved `report`
    string. The report is the terminal rendering: fixed-width columns and the
    checkers' internal names, which arrives in Discord as a block to decode.
    The entries are the same facts without the formatting, so the chat message
    can be written for a reader while still saying only what the gates said.
    """
    if data.get("entries"):
        return audit_fmt.format_ledger(
            data, checkers=tuple(audit_fmt.ORDER),
            limit=DISCORD_LIMIT * MAX_MESSAGES,
            narrate=_narrator())
    # A ledger saved before entries were recorded still has its report text.
    # Shipping that beats shipping an empty message.
    title = data.get("title") or os.path.basename(data.get("clip", ""))
    return f"🎬 **{title}**\n```\n{data.get('report', '').strip()}\n```"


def post(webhook, text):
    for part in chunk(text):
        body = json.dumps({"content": part}).encode()
        # Discord's edge rejects urllib's default User-Agent with 403 even
        # though the webhook URL is valid. MEASURED both directions on one
        # live webhook, same process, same minute: no UA header -> 403,
        # with this header -> 204. curl worked all along because curl sends
        # its own UA, which is exactly why a curl smoke test passing is not
        # evidence that this function works.
        req = urllib.request.Request(
            webhook, data=body, headers={
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status >= 300:
                raise RuntimeError(f"webhook HTTP {resp.status}")


def run_once(webhook):
    state = load_state()
    todo = pending(state)
    if not todo:
        return 0
    # Cap the BURST, not the backlog. Leftovers are not dropped: `pending`
    # recomputes from disk every tick, so what is skipped here is simply the
    # head of the next run 15 minutes later. Reported so a backlog is visible
    # instead of looking like the channel went quiet.
    ekstra = len(todo) - MAX_LEDGERS
    if ekstra > 0:
        todo = todo[:MAX_LEDGERS]
        print(f"audit_watch: {ekstra} ledger lagi nunggu tick berikutnya "
              f"(batas {MAX_LEDGERS}/tick biar channel ga kebanjiran)",
              file=sys.stderr)
    sent = 0
    for path in todo:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            print(f"audit_watch: skip {path.name} — {exc}", file=sys.stderr)
            continue
        text = format_ledger(data)
        if not webhook:
            # PRINTING IS NOT DELIVERING. This used to mark the ledger sent
            # either way, so a cron run with no webhook configured silently
            # consumed all 70 ledgers to a stdout nobody reads -- and because
            # "sent" is permanent, configuring the webhook afterwards
            # delivered NOTHING. The channel stayed empty while the job
            # reported ok every 15 minutes.
            print(text)
            continue
        post(webhook, text)
        state.setdefault("sent", []).append(path.name)
        sent += 1
        # Persist after EACH ledger, not once at the end. `save_state` used to
        # sit after the loop, so a webhook error mid-batch skipped it entirely
        # and the next run re-posted everything already delivered. Measured:
        # ledger 1 posted, HTTP 500 on ledger 2, and the following run sent 2.
        # Marking a ledger sent is the record that it WAS sent, so it has to
        # be durable at that moment rather than at the end of a batch that may
        # not finish.
        save_state(state)
    return sent


def _selftest():
    # chunk must never split a line, because half a verdict is a lie about
    # what a division said.
    lines = [f"line {i} " + "x" * 80 for i in range(60)]
    parts = chunk("\n".join(lines), limit=500)
    assert all(len(p) <= 500 for p in parts), "chunk exceeded limit"
    rejoined = "\n".join(parts)
    assert rejoined.count("line ") == 60, "chunk lost or duplicated a line"
    for p in parts:
        for line in p.split("\n"):
            assert line == "" or line in lines, f"split mid-line: {line!r}"

    # An over-long single line is hard-split rather than dropped.
    parts = chunk("y" * 1200, limit=500)
    assert "".join(parts) == "y" * 1200, "long line lost content"

    # format_ledger surfaces warnings; a silent warning is the failure mode
    # this whole ledger exists to prevent.
    body = format_ledger({
        "title": "T", "clip": "/x/c.mp4",
        "totals": {"pass": 3, "reject": 1, "warn": 0},
        "mood": "hype", "music": "m.mp3", "duration_sec": 22.0,
        "warnings": ["outro jamet: clip too short"],
        "entries": [
            {"checker": "edit", "target": "outro", "verdict": "pass",
             "reason": "jamet", "detail": "last 5s"},
            {"checker": "footage", "target": "abc @40s",
             "verdict": "reject", "reason": "not the action", "detail": ""},
        ],
        "report": "MARKETING  edit  1 pass",
    })
    assert "outro jamet" in body, "warning not shown"
    assert "1 ditolak" in body, "totals missing"
    assert "Editing" in body and "Frame b-roll" in body, "sections missing"
    # The terminal report is not what gets posted; the entries are.
    assert "MARKETING  edit" not in body, "posted the terminal rendering"

    # A ledger saved before entries existed still produces a message rather
    # than an empty one.
    old = format_ledger({"title": "T", "report": "legacy text"})
    assert "legacy text" in old, "legacy ledger lost its report"
    print("audit_watch: self-check ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        return 0
    webhook = os.environ.get("AUDIT_WEBHOOK", "")
    if not webhook:
        # Exit non-zero so the scheduler shows a FAILURE. A delivery job that
        # cannot deliver reported "ok" every 15 minutes for a day while the
        # channel stayed empty; a watchdog that cannot fail is worse than no
        # watchdog, because it actively tells you the silence is fine.
        waiting = len(pending(load_state()))
        print("audit_watch: AUDIT_WEBHOOK belum diset, ga ada yang dikirim. "
              f"{waiting} ledger nunggu. Taro URL webhook di "
              "/home/ubuntu/.hermes/audit-watch/webhook.", file=sys.stderr)
        run_once("")  # still print them, for a human running this by hand
        return 1
    run_once(webhook)
    return 0


if __name__ == "__main__":
    sys.exit(main())
