"""The jamet preset's approved defaults are a DECISION, not a tuning target.

Operator, after watching the delivered file: "Cakep ni untuk preset jedag jedug
sempurna! Simpen ya logicnya".

This test deliberately breaks the house rule that a test asserts the property
and never the number being tuned. The rule is right for numbers still being
tuned. These are not: each one is an approved decision, and two of them are
places where I pushed in the wrong direction and the operator's own measured
reference overruled me.

So this is a decision-lock, not a quality gate. Its failure message is not
"this value is wrong" but "someone is changing an approved value" — the test
tells a future session to go ask rather than to adjust. The properties those
values produce are covered by _v41, _v43, _v46, _v60, _v65 and _v66; if you
genuinely need to move a number, the operator approves it, you change the
expectation HERE and the property tests still have to pass on their own.

Pins only the ending constants the operator signed off on. Nothing else.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edit

# (attribute, approved value, what the operator decided)
APPROVED = [
    ("OUTRO_JAMET_SECONDS", 5.0,
     "freeze span before the portrait tail"),
    ("OUTRO_PORTRAIT", 2.6,
     "how long the portrait holds; it LENGTHENS the outro rather than "
     "becoming a separate segment -- 'Outro di perpanjang, itu ibarat outro "
     "juga'"),
    ("OUTRO_PORTRAIT_SPIN", 540.0,
     "one and a half turns on the way in -- 'pas transisi gambar kasih aja "
     "spinning atau gimana, yg lebay'"),
    ("OUTRO_PORTRAIT_SPIN_SECS", 0.45,
     "longer and the landing stops being a landing"),
    ("OUTRO_PORTRAIT_SHAKE_PX", 88.0,
     "travel on the still, larger than the footage's 64 because a photograph "
     "has no internal motion so equal displacement reads as less"),
    ("OUTRO_PORTRAIT_ZOOM", 0.18,
     "punch-in per hit on the portrait"),
    ("OUTRO_CLUSTER", 4,
     "hits per run; the reference groups 3-5 and rests between"),
    ("OUTRO_CLUSTERS", 3,
     "runs in the ending window"),
    ("OUTRO_SHAKE_PX", 64.0,
     "travel on the footage freeze; rowdiness lever is TRAVEL, not hit count"),
    ("OUTRO_PUNCH_PER_BEAT", 1.0,
     "no-track fallback only. Raising it to 3 gave a fixed 5.77 Hz against "
     "onsets 0.5-0.8s apart, marked nothing on 2 of 3 hits, and correctly "
     "broke _v41/_v46"),
]

_wrong = []
for _name, _want, _why in APPROVED:
    assert hasattr(edit, _name), (
        "edit.%s is gone. The jamet preset is settled and documented in the "
        "clipper-operations skill (references/jamet-preset-settled.md); "
        "renaming a knob silently drops an approved decision." % _name)
    _got = getattr(edit, _name)
    if abs(float(_got) - float(_want)) > 1e-9:
        _wrong.append("  %-28s is %-8s approved %-8s (%s)"
                      % (_name, _got, _want, _why))

assert not _wrong, (
    "An APPROVED jamet value changed:\n%s\n\n"
    "These are not defaults to tune -- the operator signed them off after "
    "watching the delivered file (\"Cakep ni untuk preset jedag jedug "
    "sempurna! Simpen ya logicnya\"). If a change is genuinely wanted, get it "
    "approved, update the expectation in this file AND in the skill reference "
    "references/jamet-preset-settled.md, and keep _v41/_v43/_v46/_v60/_v65/"
    "_v66 green on their own merits." % "\n".join(_wrong))

# The three inputs are part of the contract too: hook, main video, outro still.
# Operator: "Berarti bisa 3 field ini, hook, video utama, gambar untuk outro".
import inspect

import job

_sig = inspect.signature(job.run)
for _flag in ("portrait",):
    assert _flag in _sig.parameters, (
        "job.run lost the %r parameter. A jamet clip takes three inputs -- "
        "hook footage, the main video, and the outro still -- and the still "
        "reaching the renderer depends on this being plumbed through every "
        "layer." % _flag)

_src = inspect.getsource(edit.render_clip)
assert "portrait" in _src, (
    "edit.render_clip no longer mentions the portrait. A flag that is accepted "
    "but never read is the config-plumbing failure this repo has hit before: "
    "the test sets a global, passes, and the renderer stays broken.")

print("_v67: %d approved jamet values intact, portrait plumbed through "
      "job.run and render_clip" % len(APPROVED))
print("_v67 ok")
