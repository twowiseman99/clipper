#!/usr/bin/env python3
"""Phase 2: the narration layer cannot invent a fact.

A language model handed a page of digits and asked to summarise is a machine
for producing plausible wrong numbers. The operator's rule is flat: "Angka dan
fakta dilarang diubah atau dikarang." So the guard, not the prompt, is the
thing under test here -- a prompt rule is a request, and this class of error
has already shipped twice on prompt rules alone (the Indonesian flag on a
Palestine clip, and a vision gate answering ok=true while naming a competing
face).

What is asserted:

  * The brief carries no path, flag, function name or error string, so the
    model cannot echo one back.
  * A number absent from the brief kills the narration, even when it is
    plausible and even when it is CORRECT in the ledger -- the narration is
    only allowed to restate what it was shown.
  * Machine detail in the output kills the narration.
  * Over-long output kills it.
  * A router failure returns "" rather than raising: the Phase 1 message must
    ship regardless.
  * format_ledger works with no narrator at all, and the narration is the
    first thing dropped when the message is over budget (rule 4/6: what gets
    cut is prose, never the error fields).

Verified against a live call this session: claude-opus-5 via combo1 produced
"28 detik ... 8 lolos, 1 ditolak di bagian gambar penutup, plus 1 catatan dari
sisi musik", and all 8 claims in it were checked against the ledger by hand.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import audit_fmt  # noqa: E402
import audit_narrate  # noqa: E402

DATA = {
    "duration_sec": 28.0,
    "mood": "emotional",
    "mood_used": "hype",
    "clip": "/home/ubuntu/clipper/jobs/render5.mp4",
    "title": "Gibran Berhenti di Tengah Pidato",
    "totals": {"pass": 8, "reject": 1, "warn": 1},
    "entries": [
        {"checker": "freeze", "verdict": "reject", "target": "pick",
         "reason": "no qualifying frame", "detail": "31 frame, 0 lolos"},
        {"checker": "sound", "verdict": "warn", "target": "mood clash",
         "reason": "preset 'hype' vs transcript 'emotional'", "detail": ""},
        {"checker": "copy", "verdict": "pass", "target": "risky words",
         "reason": "none found", "detail": ""},
    ],
    "warnings": [
        "gambar penutup: ga ada frame yang jelas nunjukin Gibran"
        " | stage: freeze | source: freeze_pick.py:pick"
        " | error: no qualifying frame"
        " | debug: /home/ubuntu/clipper/jobs/freeze-debug/r5.freeze.json",
    ],
}
SECTIONS = [("Gambar penutup", ["reject"]), ("Musik", ["warn"]),
            ("Hook & judul", ["pass"])]


def test_brief_hides_the_machine():
    b = audit_narrate.brief(DATA, SECTIONS)
    for leak in (".py", ".mp4", ".json", "/home/", "--", "freeze_pick",
                 "no qualifying frame", "Traceback"):
        assert leak not in b, f"brief leaked {leak!r}:\n{b}"
    # It must still carry the facts worth narrating.
    for want in ("28 detik", "lolos: 8", "ditolak: 1", "catatan: 1",
                 "divisi Gambar penutup"):
        assert want in b, f"brief missing {want!r}:\n{b}"


def test_a_number_not_in_the_brief_is_rejected():
    b = audit_narrate.brief(DATA, SECTIONS)
    # "31 frame" is TRUE -- it is in the ledger. It is still rejected, because
    # the narration was never shown it and cannot be trusted to have read it.
    assert not audit_narrate._numbers_ok("31 frame dicek, 0 lolos", b, DATA)
    assert not audit_narrate._numbers_ok("confidence 0,95 di bawah ambang",
                                         b, DATA)
    assert not audit_narrate._numbers_ok("ada 47 cek", b, DATA)
    # Restating the brief is fine, in either decimal convention.
    assert audit_narrate._numbers_ok("8 lolos, 1 ditolak, 1 catatan", b, DATA)
    assert audit_narrate._numbers_ok("klipnya 28,0 detik", b, DATA)


def test_the_brief_states_the_total_rather_than_making_it_derivable():
    """A guard that rejects TRUE statements trains the reader to ignore it.

    Under an adversarial prompt the live model wrote "kena 10 pengecekan" --
    8 + 1 + 1, correct arithmetic over the brief it was given. The guard
    dropped it, because 10 was not a number it had been shown. Rejecting
    correct output is a false positive, and a check that cries wolf gets
    switched off. So the total is stated in the brief instead of left to be
    inferred, and the guard stays strict about everything it really has not
    seen.
    """
    b = audit_narrate.brief(DATA, SECTIONS)
    assert "total cek: 10" in b, f"the total must be stated:\n{b}"
    assert audit_narrate._numbers_ok("dicek 10 item, 8 lolos", b, DATA)
    # Still strict about measurements it was never handed.
    assert not audit_narrate._numbers_ok("31 frame, confidence 0,95", b, DATA)


def test_narration_is_dropped_not_raised(monkeypatched=None):
    """Every failure mode returns "" so Phase 1 still ships."""
    real = audit_narrate.ai.chat_json
    log = open(os.devnull, "w")
    try:
        audit_narrate.ENABLED = True

        # 1. Router down.
        def boom(*a, **k):
            raise RuntimeError("connection refused")
        audit_narrate.ai.chat_json = boom
        assert audit_narrate.narrate(DATA, SECTIONS, log=log) == ""

        # 2. Fabricated number.
        audit_narrate.ai.chat_json = lambda *a, **k: {
            "narasi": "Ada 31 frame yang dicek dan semuanya gagal."}
        assert audit_narrate.narrate(DATA, SECTIONS, log=log) == ""

        # 3. Machine detail.
        audit_narrate.ai.chat_json = lambda *a, **k: {
            "narasi": "Cek freeze_pick.py buat detailnya."}
        assert audit_narrate.narrate(DATA, SECTIONS, log=log) == ""

        # 4. Too long.
        audit_narrate.ai.chat_json = lambda *a, **k: {"narasi": "aman. " * 90}
        assert audit_narrate.narrate(DATA, SECTIONS, log=log) == ""

        # 5. Empty answer.
        audit_narrate.ai.chat_json = lambda *a, **k: {"narasi": ""}
        assert audit_narrate.narrate(DATA, SECTIONS, log=log) == ""

        # 6. An honest narration survives.
        good = ("Klip 28 detik ini dipakein mood hype padahal transkripnya "
                "kebaca emotional. 8 lolos, 1 ditolak, 1 catatan.")
        audit_narrate.ai.chat_json = lambda *a, **k: {"narasi": good}
        assert audit_narrate.narrate(DATA, SECTIONS, log=log) == good
    finally:
        audit_narrate.ai.chat_json = real
        audit_narrate.ENABLED = False
        log.close()


def test_disabled_by_default_in_a_fresh_process():
    """Phase 1 must be provable without Phase 2 running at all."""
    src = open(os.path.join(ROOT, "audit_narrate.py"), encoding="utf-8").read()
    assert 'os.environ.get("AUDIT_NARRATE", "")' in src, \
        "the narration must stay opt-in via AUDIT_NARRATE"
    assert 'not in ("", "0", "false", "no")' in src, \
        "an unset AUDIT_NARRATE must mean OFF"


def test_formatter_works_with_no_narrator():
    msg = audit_fmt.format_ledger(DATA, checkers=tuple(audit_fmt.ORDER))
    assert "🎬" in msg and "Perlu dicek sebelum upload" in msg
    # And the error fields are present and untranslated.
    assert "freeze_pick.py:pick" in msg
    assert "no qualifying frame" in msg


def test_narration_is_cut_before_the_error_fields():
    """Rule 4/6: what gets dropped is prose, never a field."""
    long_narration = "ringkasan panjang sekali. " * 8

    def narrator(data, sections):
        return long_narration

    full = audit_fmt.format_ledger(DATA, checkers=tuple(audit_fmt.ORDER),
                                   narrate=narrator)
    assert long_narration.strip() in full, "narration should appear when it fits"

    squeezed = audit_fmt.format_ledger(DATA, checkers=tuple(audit_fmt.ORDER),
                                       limit=700, narrate=narrator)
    assert long_narration.strip() not in squeezed, \
        "the narration must be dropped first when over budget"
    for field in ("freeze_pick.py:pick", "no qualifying frame"):
        assert field in squeezed, \
            f"{field!r} was cut -- the error fields must survive"


def test_a_narrator_that_explodes_cannot_break_the_message():
    def bad(data, sections):
        raise ValueError("narrator blew up")

    msg = audit_fmt.format_ledger(DATA, checkers=tuple(audit_fmt.ORDER),
                                  narrate=bad)
    assert "🎬" in msg and "no qualifying frame" in msg


def test_the_model_is_the_one_the_operator_picked():
    """ds/deepseek-v4-pro does not exist on this router; combo1 was chosen.

    Asserted as a property, not a pinned string: the module must take its
    model from configuration rather than hardcoding one, and must never carry
    an API key.
    """
    src = open(os.path.join(ROOT, "audit_narrate.py"), encoding="utf-8").read()
    assert 'os.environ.get("AUDIT_NARRATE_MODEL", "") or ai.MODEL' in src, \
        "the model must come from config, falling back to the pipeline's"
    assert "sk-" not in src and "NINEROUTER_API_KEY" not in src, \
        "no key material may appear in this module -- ai.py reads the .env"


def main():
    test_brief_hides_the_machine()
    test_a_number_not_in_the_brief_is_rejected()
    test_the_brief_states_the_total_rather_than_making_it_derivable()
    test_narration_is_dropped_not_raised()
    test_disabled_by_default_in_a_fresh_process()
    test_formatter_works_with_no_narrator()
    test_narration_is_cut_before_the_error_fields()
    test_a_narrator_that_explodes_cannot_break_the_message()
    test_the_model_is_the_one_the_operator_picked()
    print("_v75: ok (narration cannot invent a fact, and cannot cost the log)")


if __name__ == "__main__":
    main()
