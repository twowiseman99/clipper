#!/usr/bin/env python3
"""An unregistered checker gets ONE section, however many entries it recorded.

`names += [c for c in seen if c not in names]` reads like a dedupe and is not
one: the comprehension is fully evaluated against the OLD `names` before `+=`
extends it, so every occurrence of a checker missing from ORDER passed the
`not in` test. A ledger with 33 freeze entries printed the freeze section 33
times — 113,657 characters and 179 Discord messages for one render.

The property is per-checker, not per-name: EVERY checker present in the ledger
appears exactly once, and the per-checker verdict count is preserved (a dedupe
that drops entries would also pass a header count of 1).
"""

import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                ".."))

import audit        # noqa: E402
import audit_fmt    # noqa: E402


def ledger(n_freeze):
    """A ledger shaped like the real one: one brief, n info rows, one reject."""
    entries = [
        {"checker": "language", "target": "transcript review",
         "verdict": "pass", "reason": "no mishearings found", "detail": ""},
        {"checker": "freeze", "target": "subject",
         "verdict": audit.BRIEF, "reason": "Gibran", "detail": ""},
    ]
    for i in range(n_freeze):
        entries.append({
            "checker": "freeze", "target": "freeze-pick",
            "verdict": "info",
            "reason": "%.2fs no conf 0.72 — man in dark cap" % (144.27 + i * .2),
            "detail": ""})
    entries.append({"checker": "freeze", "target": "pick",
                    "verdict": "reject", "reason": "no qualifying frame",
                    "detail": ""})
    return {
        "title": "Judul", "clip": "/x/clip_1791642180_122.mp4",
        "totals": {"pass": 1, "reject": 1, "warn": 0},
        "entries": entries, "warnings": [], "duration_sec": 28.0,
        "mood": "emotional",
    }


def headers(body):
    """Section headers, by the label the reader sees."""
    return [ln for ln in body.split("\n")
            if ln.startswith("**") and " · " in ln]


def main():
    # One entry and thirty-three must both give one section.
    for n in (0, 1, 2, 33, 60):
        body = audit_fmt.format_ledger(ledger(n))
        counts = collections.Counter(headers(body))
        dupes = {h: c for h, c in counts.items() if c > 1}
        assert not dupes, f"n_freeze={n}: section printed more than once: {dupes}"

        # Every checker in the ledger is represented. A dedupe that loses a
        # whole section would satisfy the assertion above.
        present = {e["checker"] for e in ledger(n)["entries"]}
        for checker in present:
            label = str(audit_fmt.SECTIONS.get(checker) or checker)
            assert any(label in h for h in counts), \
                f"n_freeze={n}: checker {checker!r} ({label}) has no section"

    # The 33-entry case is the one that shipped: assert the real numbers.
    body = audit_fmt.format_ledger(ledger(33))
    assert len(headers(body)) == 2, headers(body)
    assert len(body) < 4000, f"one render is {len(body)} chars"

    # Ordering is still ORDER-first, with unregistered checkers after the
    # registered ones rather than interleaved.
    pos = {h: body.index(h) for h in headers(body)}
    lang = next(h for h in pos if "Transkrip" in h)
    frz = next(h for h in pos if h not in (lang,))
    assert pos[lang] < pos[frz], f"ORDER lost: {pos}"

    print("_v68: ok (33 freeze entries -> 1 section, %d chars)" % len(body))


if __name__ == "__main__":
    main()
