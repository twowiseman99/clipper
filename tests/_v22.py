"""The frame has to show the ACT the sentence named, not its aftermath.

v21 shipped a cutaway under the word "dibom" showing people picking through
rubble. Everything upstream was right: real Gaza footage, credible channel,
on-topic by every check in place. The operator's verdict: "mereka di bom tapi
footagenya bukan bom. cape gw."

Rubble is what a bombing LEAVES. The gate asked "is this Gaza?" and never asked
"is this a bombing?", so the aftermath passed as the act.

Measured on this box against the real sources:

    frame                   action asked            verdict
    rubble + people digging dibom serangan          reject   <- the bug
    airstrike fireball      dibom serangan          pass
    rubble + people digging kehancuran reruntuhan   pass     <- same frame
    soldier on a rooftop    dibom serangan          reject

The third row is the control that matters: the same frame that fails as a
bombing passes as destruction, so the gate is reading the action and not just
scoring the frame's quality.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import ai
import broll
import broll_place as bp

TMP = "/tmp/_v22"
os.makedirs(TMP, exist_ok=True)
bars = os.path.join(TMP, "bars.mp4")
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
     "testsrc2=size=320x240:rate=25:duration=5",
     "-c:v", "libx264", "-preset", "ultrafast", bars],
    check=True, capture_output=True)

# --- every action word carries a visual description ---------------------
# A missing entry silently degrades the gate back to subject-only, which is
# exactly the hole this test exists to close.
for word in ("dibom", "diserang", "dibantai", "mengungsi", "hancur"):
    terms = broll.action_terms(word)
    assert terms, f"no action term for {word!r}"
    assert broll.action_look(terms[0]), \
        f"{word!r} -> {terms[0]!r} has no visual description"

# A bombing and its aftermath must not share wording, or the prompt cannot
# tell them apart.
bom = broll.action_look(broll.action_terms("dibom")[0])
ruin = broll.action_look(broll.action_terms("hancur")[0])
assert "explosion" in bom and "rubble" not in bom, bom
assert "rubble" in ruin and "explosion" not in ruin, ruin

# --- the action reaches the prompt as its own question ------------------
seen = {}


def capture(system, user, images, **kw):
    seen["user"] = user
    return {"usable": True, "on_topic": True, "shows_action": True,
            "shows": "stub"}


real = ai.vision_json
ai.vision_json = capture
try:
    bp._vision_check(bars, 1.0, "Gaza", "an explosion or blast fireball")
    u = seen["user"]
    assert "shows_action" in u, "the action question never reached the prompt"
    assert "an explosion or blast fireball" in u, u[-400:]
    assert "AFTERMATH" in u, "the aftermath exclusion is missing from the prompt"
    # Without an action, the third question must not appear at all.
    bp._vision_check(bars, 1.0, "Gaza", None)
    assert "shows_action" not in seen["user"], \
        "the action question leaked in with no action to ask about"
    assert "__ACTION" not in seen["user"], "a template sentinel reached the model"
finally:
    ai.vision_json = real

# --- aftermath is a rejection ------------------------------------------
ai.vision_json = lambda *a, **k: {"usable": True, "on_topic": True,
                                  "shows_action": False,
                                  "shows": "rubble after a strike"}
try:
    at, why = bp._pick_window(bars, 5.0, 2.0, 2.0, "Gaza", "an explosion")
    assert at is None, f"aftermath footage was accepted at {at} ({why})"
finally:
    ai.vision_json = real

# --- the act itself passes ---------------------------------------------
ai.vision_json = lambda *a, **k: {"usable": True, "on_topic": True,
                                  "shows_action": True,
                                  "shows": "airstrike fireball"}
try:
    at, why = bp._pick_window(bars, 5.0, 2.0, 2.0, "Gaza", "an explosion")
    assert at is not None, f"the act itself was rejected: {why}"
    assert "airstrike fireball" in why, why
finally:
    ai.vision_json = real

# --- a model that omits shows_action must not block every cutaway ------
ai.vision_json = lambda *a, **k: {"usable": True, "on_topic": True,
                                  "shows": "field footage"}
try:
    u, t, a, shows = bp._vision_check(bars, 1.0, "Gaza", "an explosion")
    assert (u, t, a) == (True, True, None), (u, t, a)
    at, why = bp._pick_window(bars, 5.0, 2.0, 2.0, "Gaza", "an explosion")
    assert at is not None, f"a missing shows_action field blocked the cutaway: {why}"
finally:
    ai.vision_json = real

# --- a dead router still degrades to motion ----------------------------
def boom(*_a, **_k):
    raise RuntimeError("router down")


ai.vision_json = boom
try:
    assert bp._vision_check(bars, 1.0, "Gaza", "an explosion") == \
        (None, None, None, "")
    at, why = bp._pick_window(bars, 5.0, 2.0, 2.0, "Gaza", "an explosion")
    assert at is not None and "motion" in why, (at, why)
finally:
    ai.vision_json = real

# --- prepare() forwards the action -------------------------------------
asked = {}


def spy(src, dur, latest, seconds, subject=None, action=None):
    asked.update(subject=subject, action=action)
    return None, "stub"


real_pick = bp._pick_window
bp._pick_window = spy
try:
    bp.prepare(bars, os.path.join(TMP, "out.mp4"), seconds=2.0,
               subject="Gaza", action="an explosion")
    assert asked == {"subject": "Gaza", "action": "an explosion"}, asked
finally:
    bp._pick_window = real_pick

for f in os.listdir(TMP):
    os.remove(os.path.join(TMP, f))
os.rmdir(TMP)

print("_v22.py OK — every action word has a distinct visual description, the "
      "action is asked as its own question, aftermath footage is rejected "
      "under 'dibom' but accepted under 'hancur', and a missing field or dead "
      "router never blocks a cutaway")
