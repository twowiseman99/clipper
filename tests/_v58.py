#!/usr/bin/env python3
"""The posted ledger must be readable, on every ledger actually on disk.

audit_fmt's own self-check uses hand-built entries, which only prove the
formatter handles the shapes I thought of. These 39 ledgers are what the
renders really produced, including the ones written before the brief existed.
Three bugs shipped past the self-check and were caught by reading the posted
message: a filename run through the phrase table ("klip_179...mp4"), a music
line that said the same thing three times, and an English `warnings` entry
sitting above Indonesian verdicts.

So this test asserts properties over the real corpus rather than exact strings:
no internal checker name reaches the reader, no path is corrupted, no line
repeats its own subject, and nothing from the phrase table ships in English.
"""

import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import audit        # noqa: E402
import audit_fmt    # noqa: E402
import audit_watch  # noqa: E402

LEDGERS = sorted(glob.glob(os.path.join(
    os.path.dirname(__file__), "..", "jobs", "*.audit.json")))

# The checker keys are internal. Seen as a section header they mean the
# SECTIONS table lost a row.
INTERNAL = set(audit.DIVISIONS)

# English the reader must never see, listed HERE rather than read from
# audit_fmt.PHRASES. Deriving it from the table makes the test a tautology: a
# negative control that deleted the warning translations stayed green, because
# removing a row also removed the assertion that looked for it.
ENGLISH = [
    "no cutaways were placed",
    "no footage passed the gates",
    "no footage of the act",
    "no mishearings found",
    "transcript review",
    "after segment selection",
    "operator override",
    "verified channel",
    "marketing filler",
    "risky words",
    "none found",
    "not the action",
    "off topic",
    "word(s) of transcript",
    "track(s) on this box",
    "DID NOT RUN",
    "BRIEFED, NO VERDICT",
]


def check(path):
    data = json.load(open(path, encoding="utf-8"))
    body = audit_watch.format_ledger(data)
    name = os.path.basename(path)

    assert body.strip(), f"{name}: empty message"

    # Legacy ledgers (no entries) fall back to the terminal report; the
    # properties below describe the new path only.
    if not data.get("entries"):
        assert data.get("report", "") .strip() in body, \
            f"{name}: legacy ledger lost its report"
        return "legacy"

    for key in INTERNAL:
        assert f"**{key}**" not in body, \
            f"{name}: internal checker name '{key}' reached the reader"

    # Every filename mentioned in an entry must appear unmodified, or not at
    # all. A path the phrase table rewrote points at a file nobody has.
    for e in data["entries"]:
        for field in ("target", "reason", "detail"):
            for fn in re.findall(r"[\w./-]+\.(?:mp4|mp3|json|txt)",
                                 str(e.get(field, ""))):
                stem = os.path.basename(fn)
                if stem.lower() in body.lower():
                    assert stem in body, \
                        f"{name}: filename altered, expected {stem}"
                assert "klip_" not in body, \
                    f"{name}: 'clip_' was translated into 'klip_'"

    # No verdict line may name its own subject twice: that was the music gate
    # saying target, reason and detail as three copies of one fact.
    for ln in body.split("\n"):
        for fn in re.findall(r"[\w-]+\.mp3", ln):
            assert ln.count(fn) == 1, f"{name}: line repeats {fn}: {ln}"
        assert "->" not in ln, f"{name}: raw arrow reached the reader: {ln}"
        assert not re.search(r"\['[^']*'\]", ln), \
            f"{name}: raw python repr reached the reader: {ln}"

    # Known English must not reach the reader. Checked against the POSTED
    # text only: the saved ledger holds the raw call-site English by design,
    # so asserting over `data["warnings"]` tested the input, not the output.
    for src in ENGLISH:
        assert src not in body, f"{name}: untranslated {src!r}"

    # Each warning must be translated on its way into the message, since a
    # warning is the line the operator reads first. Compared by the words it
    # carries rather than exact text, because a warning embeds a measurement.
    for w in data.get("warnings", []):
        assert w not in body, f"{name}: warning posted verbatim: {w}"

    # Every phrase this test polices must still be something audit_fmt claims
    # to handle, so a renamed call-site string is a visible failure here
    # rather than silent English in the channel.
    unknown = [s for s in ENGLISH
               if s not in audit_fmt.PHRASES and s.isupper() is False
               and audit_fmt.id_text(s) == s]
    assert not unknown, f"audit_fmt has no translation for: {unknown}"

    # Counts come from the ledger, never recomputed here.
    totals = data.get("totals", {})
    checks = totals.get("pass", 0) + totals.get("reject", 0) \
        + totals.get("warn", 0)
    assert f"{checks} cek" in body, f"{name}: check count missing or wrong"
    if totals.get("reject"):
        assert f"{totals['reject']} ditolak" in body, f"{name}: rejects hidden"

    return "ok"


def main():
    assert LEDGERS, "no ledgers on disk to test against"
    tally = {}
    for p in LEDGERS:
        verdict = check(p)
        tally[verdict] = tally.get(verdict, 0) + 1
    print("_v58: %d ledger ok (%s)" % (
        len(LEDGERS), ", ".join(f"{k} {v}" for k, v in sorted(tally.items()))))


if __name__ == "__main__":
    main()
