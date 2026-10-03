"""The venue cutaway, the still-photo cutaway, and the ending nobody saw.

Three operator findings from watching v12, each one a real defect:

  1. "broll gontoe ngaco buang" — a cutaway to Gontor, the venue the speech is
     being given in, fires exactly as the speaker says "Gontor". Footage of the
     room you are already in is a continuity error, not an edit.
  2. "brollnya cuman foto" — three of four cutaways were effectively stills.
     Measured mean inter-frame motion: 0.31, 0.37 against 16.3 for the one that
     read as video. prepare() cut blindly at a third of the way in.
  3. "out tro krng lama" — 3s of colour drain is over before it registers.

Checks the fixes against the real data, and against ffmpeg where a filter is
involved, because a string assertion already passed once while ffmpeg rejected
the graph outright.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import broll_place
import edit
import job

WORDS = "media/uf9833efdc72b/PPOKdwOCMLA.words.json"

# --- 1. the venue is not a cutaway trigger ----------------------------------
CTX = "Prabowo membela Palestina di depan banyak pemimpin negara, di Gontor"
names = {"prabowo", "palestina", "gontor"}

venues = job._venue_names(CTX, names)
assert "gontor" in venues, f"Gontor should read as the venue: {venues}"
assert "palestina" not in venues, f"Palestina is the subject, not a venue: {venues}"
assert "prabowo" not in venues, f"Prabowo is a person: {venues}"

# A longer venue phrase, with place words between the preposition and the name.
long_ctx = "Prabowo bicara soal Palestina di Pondok Modern Gontor"
v2 = job._venue_names(long_ctx, names)
assert "gontor" in v2, f"multi-word venue missed: {v2}"
assert "palestina" not in v2, f"subject swept up as venue: {v2}"

# A clip genuinely ABOUT a place keeps its footage: no place preposition.
v3 = job._venue_names("Gontor merayakan seratus tahun", {"gontor"})
assert "gontor" not in v3, f"subject-position place wrongly excluded: {v3}"

# --- 2. a cutaway has to move ----------------------------------------------
assert broll_place.MOTION_MIN > 0.45, "threshold must sit above the measured duds"
assert broll_place.MOTION_MIN < 16.3, "threshold must pass real footage"

# Measure against synthetic sources instead of the shipped inserts: those files
# are overwritten by every render, so pinning the test to them made it pass or
# fail depending on which version last ran. A still and a moving clip built here
# are stable, and the real v12 measurements are recorded in the assertions.
#
#   v12 shipped          0.37, 0.32  (stills the operator spotted)
#   v12's one good cut   10.34
#   v13 after the fix    14.75, 12.24, 11.19
probe_dir = "/tmp/_v13src"
os.makedirs(probe_dir, exist_ok=True)
still = os.path.join(probe_dir, "still.mp4")
moving = os.path.join(probe_dir, "moving.mp4")
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
     "color=c=gray:size=320x240:rate=25:duration=4", "-c:v", "libx264",
     "-preset", "ultrafast", still], check=True, capture_output=True)
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
     "testsrc2=size=320x240:rate=25:duration=4", "-c:v", "libx264",
     "-preset", "ultrafast", moving], check=True, capture_output=True)

m_still = broll_place._motion_at(still, 0.2, 2.0)
m_moving = broll_place._motion_at(moving, 0.2, 2.0)
assert m_still is not None and m_moving is not None, "motion probe returned nothing"
assert m_still < broll_place.MOTION_MIN, f"still accepted as footage: {m_still}"
assert m_moving >= broll_place.MOTION_MIN, f"real footage rejected: {m_moving}"
measured = {"still": round(m_still, 2), "moving": round(m_moving, 2)}

# prepare() must refuse a source that never moves rather than holding a frame.
dead = os.path.join(probe_dir, "out.mp4")
assert broll_place.prepare(still, dead, seconds=2.0) is False, \
    "an entirely static source should not become a cutaway"

for f in os.listdir(probe_dir):
    os.remove(os.path.join(probe_dir, f))
os.rmdir(probe_dir)

# --- 3. the ending is long enough to land ----------------------------------
assert edit.OUTRO_SECONDS >= 5.0, f"outro too short: {edit.OUTRO_SECONDS}"
assert edit.OUTRO_DIM < 0.7, "dimming this far loses the speaker's face"

bright, filters = edit._outro_filters(90.0, mood="emotional")
assert filters, "melancholy ending produced no filters"
assert "hue=s=" in filters[0], filters
assert "between(t," not in bright, "no flashes belong in a grief ending"
# The ramp has to span the configured window, not a hardcoded 3s.
assert f"{90.0 - edit.OUTRO_SECONDS:.2f}" in filters[0], filters

# --- ffmpeg must accept it, not just the string ----------------------------
# _outro_filters refuses to treat a clip shorter than 3x the window: an ending
# covering a third of the clip is not an ending. So the probe has to clear that
# bar, and the refusal itself is worth asserting.
assert edit._outro_filters(edit.OUTRO_SECONDS * 2, mood="emotional") == ("", []), \
    "a clip barely longer than the outro should get no treatment"

probe_dur = edit.OUTRO_SECONDS * 3 + 1
probe = "/tmp/_v13probe.mp4"
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
     f"testsrc=size=320x568:rate=30:duration={probe_dur:.0f}", "-c:v",
     "libx264", "-preset", "ultrafast", probe], check=True, capture_output=True)
for mood in ("emotional", "hype"):
    b, f = edit._outro_filters(probe_dur, mood=mood)
    parts = list(f)
    if b:
        parts.append(f"eq=brightness='{b}':eval=frame")
    assert parts, f"{mood} produced no chain at {probe_dur}s"
    res = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", probe, "-vf", ",".join(parts),
         "-f", "null", "-"],
        capture_output=True, text=True)
    assert res.returncode == 0, f"ffmpeg rejected {mood}: {res.stderr[:300]}"
os.remove(probe)

print(f"_v13.py OK — venue 'Gontor' excluded as a trigger, subject kept; "
      f"motion gate {broll_place.MOTION_MIN} separates {measured}; "
      f"outro {edit.OUTRO_SECONDS}s dim {edit.OUTRO_DIM}; ffmpeg accepts both")
