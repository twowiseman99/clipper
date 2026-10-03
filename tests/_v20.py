"""Footage has to be OF the event, not merely about it.

The operator's rule, verbatim: "semua frame harus bener footage dari palestina
yang dibahas, itu rule kunci, kalau cuman gambaran dari footage lain, gw gamau".

A readable-frame gate is not enough for that. v19 shipped a window the model
described as "Crowd with luggage at border crossing" — factually Gaza refugees,
so the source was right, but on screen it read as, in the reviewer's words, "a
generic daytime outdoor crowd scene... no rubble, no smoke, no soldiers".

Measured on this box with the real sources, subject = the Gaza context line:

    frame                       usable  on_topic
    airstrike over Gaza         True    True
    bodycam rooftop raid        True    True
    crowd at Gaza crossing      True    True
    Prabowo at the Gontor podium True   False     <- the control that matters
    colour bars                 False   False

The podium frame proves the gate can say no: it is a perfectly readable shot of
the clip's own subject matter, and it is not footage of Gaza.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import ai
import broll_place as bp

TMP = "/tmp/_v20"
os.makedirs(TMP, exist_ok=True)
bars = os.path.join(TMP, "bars.mp4")
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
     "testsrc2=size=320x240:rate=25:duration=5",
     "-c:v", "libx264", "-preset", "ultrafast", bars],
    check=True, capture_output=True)

# --- the subject reaches the prompt --------------------------------------
seen = {}


def fake(system, user, images, **kw):
    seen["user"] = user
    return {"usable": True, "on_topic": True, "shows": "stub"}


real = ai.vision_json
ai.vision_json = fake
try:
    bp._vision_check(bars, 1.0, "Gaza being bombed")
    assert "Gaza being bombed" in seen["user"], \
        "the subject never reached the prompt:\n" + seen["user"][:400]
    # The JSON example in the prompt must survive templating — an earlier
    # version used str.format and died on the braces in '{"usable": ...}'.
    assert '"on_topic"' in seen["user"], "reply shape missing from the prompt"
finally:
    ai.vision_json = real

# --- off-topic is a rejection, not a warning ----------------------------
# A source whose every finalist is off topic must be dropped. Falling back to
# the liveliest window would ship the exact frame the model just refused.
ai.vision_json = lambda *a, **k: {"usable": True, "on_topic": False,
                                  "shows": "calm unrelated crowd"}
try:
    at, why = bp._pick_window(bars, 5.0, 2.0, 2.0, "Gaza being bombed")
    assert at is None, f"an off-topic source produced a window at {at} ({why})"
    assert "shows the subject" in why, why
finally:
    ai.vision_json = real

# --- on-topic still passes ----------------------------------------------
ai.vision_json = lambda *a, **k: {"usable": True, "on_topic": True,
                                  "shows": "rubble and smoke"}
try:
    at, why = bp._pick_window(bars, 5.0, 2.0, 2.0, "Gaza being bombed")
    assert at is not None, f"on-topic footage was rejected: {why}"
    assert "rubble and smoke" in why, why
finally:
    ai.vision_json = real

# --- a model that omits on_topic must not silently reject ---------------
# Older prompts returned {"usable": ...} only. Treat a missing field as "no
# opinion" so an upgrade that drops the key does not kill every cutaway.
ai.vision_json = lambda *a, **k: {"usable": True, "shows": "field footage"}
try:
    u, t, a, shows = bp._vision_check(bars, 1.0, "Gaza")
    assert u is True and t is None, (u, t)
    at, why = bp._pick_window(bars, 5.0, 2.0, 2.0, "Gaza")
    assert at is not None, f"a missing on_topic field blocked the cutaway: {why}"
finally:
    ai.vision_json = real

# --- a dead router still must not fail the render -----------------------
def boom(*_a, **_k):
    raise RuntimeError("router down")


ai.vision_json = boom
try:
    u, t, a, shows = bp._vision_check(bars, 1.0, "Gaza")
    assert (u, t, a, shows) == (None, None, None, ""), (u, t, a, shows)
    at, why = bp._pick_window(bars, 5.0, 2.0, 2.0, "Gaza")
    assert at is not None, "a dead router must not block the cutaway"
    assert "motion" in why, why
finally:
    ai.vision_json = real

# --- prepare() forwards the subject -------------------------------------
asked = {}


def spy(src, dur, latest, seconds, subject=None, action=None):
    asked["subject"] = subject
    return None, "stub"


real_pick = bp._pick_window
bp._pick_window = spy
try:
    bp.prepare(bars, os.path.join(TMP, "out.mp4"), seconds=2.0,
               subject="Gaza being bombed")
    assert asked["subject"] == "Gaza being bombed", asked
finally:
    bp._pick_window = real_pick

for f in os.listdir(TMP):
    os.remove(os.path.join(TMP, f))
os.rmdir(TMP)

print("_v20.py OK — subject reaches the prompt, off-topic footage drops the "
      "source instead of falling back, a missing on_topic field is not a "
      "rejection, and a dead router degrades to measured motion")
