"""The cutaway gate has to reject empty frames without rejecting real footage.

Motion alone picked a defocused brown cross-fade frame as the BEST window in a
Kompas news package: it had respectable motion and no face, and showed nothing.
Measured on the three sources the last render used:

    at      motion  face%   what it actually was
    117.0   14.81   27.2    ground crew arming a bomb      <- good footage
     51.2   11.90   15.4    body-cam soldier, smoke-filled street
     89.6    4.47    0.0    blurred brown wash, no subject <- empty

So the face gate I planned would have been backwards in both directions: it
would have thrown away the two best windows and kept the empty one. These tests
pin the behaviour that replaced it.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import broll_place as bp

TMP = "/tmp/_v19"
os.makedirs(TMP, exist_ok=True)


def make(path, filt, seconds=6):
    # lavfi takes the first option after "=", not ":" — testsrc2=size=...
    sep = ":" if "=" in filt else "="
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         f"{filt}{sep}size=320x240:rate=25:duration={seconds}",
         "-c:v", "libx264", "-preset", "ultrafast", path],
        check=True, capture_output=True)
    return path


# --- substance: a flat wash vs real detail -------------------------------
# testsrc2 is busy colour bars; a solid colour is the synthetic stand-in for the
# defocused transition frame that fooled the motion-only probe.
busy = make(os.path.join(TMP, "busy.mp4"), "testsrc2")
flat = make(os.path.join(TMP, "flat.mp4"), "color=c=0x8a7a5e")

b_spread, b_edges = bp._frame_substance(busy, 2.0)
f_spread, f_edges = bp._frame_substance(flat, 2.0)
assert None not in (b_spread, b_edges, f_spread, f_edges), \
    "substance probe returned nothing — cv2 missing?"
assert b_spread > f_spread, f"spread did not separate: {b_spread} vs {f_spread}"
assert b_edges > f_edges, f"edges did not separate: {b_edges} vs {f_edges}"
# The floors have to sit between the two, or the gate is decorative.
assert f_spread < bp.SUBSTANCE_SPREAD < b_spread, \
    f"spread floor {bp.SUBSTANCE_SPREAD} is not between {f_spread} and {b_spread}"
assert f_edges < bp.SUBSTANCE_EDGES < b_edges, \
    f"edge floor {bp.SUBSTANCE_EDGES} is not between {f_edges} and {b_edges}"

# --- candidate count ------------------------------------------------------
# Three seconds out of two minutes: five probes sampled 12% of the source.
src_dur, hold = 128.0, 3.5
cands = bp._pick_window.__doc__ or ""
assert "14 candidates" in cands, "docstring must record why the count changed"

# --- a source with no usable window is skipped, not shipped --------------
# Every window of a solid colour fails both substance floors, and a still frame
# fails the motion floor, so this must come back as "no window" rather than
# quietly returning offset 0.
at, why = bp._pick_window(flat, 6.0, 2.0, 2.0)
assert at is None, f"a flat source produced a window at {at} ({why})"
assert "static or empty" in why, why

# --- and a real one is not ----------------------------------------------
# Vision runs off for this one. The gate now also asks whether the frame shows
# the subject, and synthetic colour bars are not footage of anything — that
# rejection is correct behaviour and _v20 covers it. What is under test here is
# the measured path: motion plus substance must accept busy footage.
bp.VISION = False
try:
    at, why = bp._pick_window(busy, 6.0, 2.0, 2.0)
    assert at is not None, f"busy footage was rejected: {why}"
    assert "motion" in why, why
finally:
    bp.VISION = True

# --- vision must never be able to fail the render ------------------------
# The router is loopback-only and can be down. _vision_ok swallows everything
# and returns None so the caller falls back to the measured numbers.
saved = bp.ai if hasattr(bp, "ai") else None
import ai


def boom(*_a, **_k):
    raise RuntimeError("router down")


real = ai.vision_json
ai.vision_json = boom
try:
    ok, shows = bp._vision_ok(busy, 2.0)
    assert ok is None and shows == "", (ok, shows)
    at, why = bp._pick_window(busy, 6.0, 2.0, 2.0)
    assert at is not None, "a dead router must not block the cutaway"
finally:
    ai.vision_json = real

# --- disabling vision leaves the measured path intact -------------------
bp.VISION = False
try:
    at, why = bp._pick_window(busy, 6.0, 2.0, 2.0)
    assert at is not None and "motion" in why, (at, why)
finally:
    bp.VISION = True

for f in os.listdir(TMP):
    os.remove(os.path.join(TMP, f))
os.rmdir(TMP)

print(f"_v19.py OK — substance separates busy ({b_spread:.0f}/{b_edges:.3f}) "
      f"from flat ({f_spread:.0f}/{f_edges:.3f}); flat source skipped; a dead "
      f"router falls back to motion instead of failing the render")
