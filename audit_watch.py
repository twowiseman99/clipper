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
            data, checkers=tuple(audit_fmt.ORDER))
    # A ledger saved before entries were recorded still has its report text.
    # Shipping that beats shipping an empty message.
    title = data.get("title") or os.path.basename(data.get("clip", ""))
    return f"🎬 **{title}**\n```\n{data.get('report', '').strip()}\n```"


def post(webhook, text):
    for part in chunk(text):
        body = json.dumps({"content": part}).encode()
        req = urllib.request.Request(
            webhook, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status >= 300:
                raise RuntimeError(f"webhook HTTP {resp.status}")


def run_once(webhook):
    state = load_state()
    todo = pending(state)
    if not todo:
        return 0
    sent = 0
    for path in todo:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            print(f"audit_watch: skip {path.name} — {exc}", file=sys.stderr)
            continue
        text = format_ledger(data)
        if webhook:
            post(webhook, text)
        else:
            print(text)
        state.setdefault("sent", []).append(path.name)
        sent += 1
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
    n = run_once(webhook)
    if not webhook and n:
        print(f"\n({n} ledger — AUDIT_WEBHOOK belum diset, jadi cuma dicetak)",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
