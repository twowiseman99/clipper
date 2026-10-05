"""Two named clip types, so the layers cannot disagree about the register.

The operator asked for the viral cut as a TYPE, not a flag combination: "Ini
jadiin jenis klip kedua, pertama kan sedih ya kmrn kita develop". The reason
that matters is the whole history of this file's siblings:

  - a triumphal anthem under a clip about people being bombed
  - a hype flash stinger on a funeral
  - a jedag-jedug shake over a melancholy BGM (this session)
  - news b-roll of a hospital ward under a beat-driven ending

Each one was mood, outro and b-roll disagreeing about what the clip was. A
named type sets all three at once, so there is one decision instead of three
that have to be remembered to match.

jamet carries broll=False deliberately. The operator: "Duh, jangan beritanya
dong, tapi pas bagian si gibran ngomong suruh bawa bekal aja cukup" — the viral
cut is the speaker's own sentence, not a news package.

Offline: no network, no ffmpeg, no render.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bgm
import edit
import job

# --- both types exist and are complete --------------------------------------
assert set(job.CLIP_TYPES) == {"sedih", "jamet"}, list(job.CLIP_TYPES)
for name, spec in job.CLIP_TYPES.items():
    for key in ("mood", "outro", "broll", "flash", "why"):
        assert key in spec, (name, key)

sedih, jamet = job.CLIP_TYPES["sedih"], job.CLIP_TYPES["jamet"]

# --- the sombre cut keeps what was built first ------------------------------
assert sedih["mood"] == "emotional", sedih
assert sedih["outro"] == "melancholy", sedih
assert sedih["broll"] is True, sedih
# A flash stinger on a grief clip is the mismatch the operator caught by eye.
assert sedih["flash"] is False, sedih

# --- the viral cut --------------------------------------------------------
assert jamet["mood"] == "hype", jamet
assert jamet["outro"] == "jamet", jamet
# No news b-roll: the speaker's own sentence is the clip.
assert jamet["broll"] is False, jamet

# --- the two types must actually differ in register -------------------------
# If a future edit made them agree, the second type would be decoration.
assert sedih["mood"] != jamet["mood"]
assert sedih["outro"] != jamet["outro"]
assert sedih["broll"] != jamet["broll"]

# --- every outro named by a type must be one edit.py understands ------------
# A typo here would silently fall through to "auto" and pick by mood, which is
# exactly the guessing the types exist to remove.
for name, spec in job.CLIP_TYPES.items():
    assert spec["outro"] in ("stinger", "melancholy", "jamet", "none"), \
        (name, spec["outro"])

# --- every mood named by a type must have a track on this box ---------------
# "No suitable track" is a legitimate outcome the pipeline warns about, but a
# clip TYPE that can never find music is a broken preset, not a warning.
for name, spec in job.CLIP_TYPES.items():
    track, why = bgm.pick(spec["mood"], key="v35")
    assert track, f"{name}: no track for mood {spec['mood']!r} ({why})"

# --- the jamet mood must reach the jedag-jedug track ------------------------
# The operator supplied this song for this ending specifically.
track, _ = bgm.pick(jamet["mood"], key="v35")
assert track and "jedag" in track["file"].lower(), track

# --- each type's outro must survive edit.py's own dispatcher ----------------
# _outro_kind reads the module-level OUTRO (set from CLIPPER_OUTRO at import),
# so this drives it the way a render does rather than inventing a parameter.
# Checking it here means a renamed kind breaks in a second, not eight minutes
# into a render.
orig = edit.OUTRO
try:
    edit.OUTRO = sedih["outro"]
    assert edit._outro_kind("emotional") == "melancholy", edit._outro_kind("emotional")
    # A sombre type must not turn into a shake just because the mood is hype.
    assert edit._outro_kind("hype") == "melancholy"

    edit.OUTRO = jamet["outro"]
    assert edit._outro_kind("hype") == "jamet", edit._outro_kind("hype")
    # ...and jamet stays jamet: the type is the operator's explicit call.
    assert edit._outro_kind("emotional") == "jamet"

    # "auto" must never pick jamet on its own — a shake on a funeral is the
    # exact mistake this guard exists for.
    edit.OUTRO = "auto"
    assert edit._outro_kind("emotional") != "jamet"
    assert edit._outro_kind("hype") != "jamet"
finally:
    edit.OUTRO = orig

print("_v35 ok — sedih and jamet differ in mood, outro and b-roll; "
      "both moods have music")
