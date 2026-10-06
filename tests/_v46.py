"""Panning is on, and the shake stays out of the speaking part of the clip.

The operator picked option A: the crop follows the subject, and the only
movement he wants beyond that is the jedag-jedug on the frozen ending, like
the CapCut tutorial he sent ("jedag jedugnya baru goyang goyang, di freeze
frame gibran dan video").

Two separate things get confused easily, so both are pinned here:

  PAN     the crop window tracking the subject across the clip (slow, 0.6s
          ramps between keyframes). On by operator's choice.
  SHAKE   the punch/offset on the frozen last frame. Confined to the outro
          window and must never reach the speech.

The failure this guards against is the shake leaking backwards into the body
of the clip, which would make the whole thing jitter rather than the ending —
and the pan silently reverting to a fixed window, which is what framed an
escort officer instead of the subject.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edit  # noqa: E402

DUR = 31.81
SEC = edit.OUTRO_JAMET_SECONDS

# The jamet ending is selected by CLIPPER_OUTRO (or --clip-type jamet, which
# sets it), NOT by mood: _outro_kind never returns "jamet" from "auto", because
# freezing and shaking a frame is a stylistic claim about the subject and the
# operator asks for it per clip.
#
# An earlier version of this test passed mood="hype", got the STINGER ending,
# and then "measured" its 4.00 hits/s as though that were the jamet shake. The
# renders were fine the whole time. Force the kind under test.
_was_outro = edit.OUTRO
edit.OUTRO = "jamet"
try:
    KIND = edit._outro_kind("hype")
    assert KIND == "jamet", "CLIPPER_OUTRO=jamet gave %r" % KIND

    start = edit._outro_start(DUR, mood="hype", seconds=SEC)
    assert start is not None, "no outro on a 31.8s jamet clip"
    head, extra = edit._outro_filters(DUR, mood="hype", seconds=SEC)
finally:
    edit.OUTRO = _was_outro

# The jamet ending returns its chain in the SECOND element (a list of filters
# appended to the base chain), not in the first — the stinger is the one that
# returns an expression string. Read both so this cannot pass by inspecting
# the wrong half.
f = head + "," + ",".join(extra)

# --- the shake lives only in the frozen ending ------------------------------
assert "loop=loop=" in f, "the jamet ending has no freeze"

# The jamet shake is a beat-phase expression, not a list of punch windows:
# mod(floor((t-start)/period), 2) flips direction every beat.
beats = re.findall(r"mod\(floor\(\(t-([0-9.]+)\)/([0-9.]+)\)", f)
assert beats, "no beat-phase shake in the jamet outro: %r" % f[:200]

shake_from = float(beats[0][0])
period = float(beats[0][1])
assert abs(shake_from - start) < 0.05, (
    "the shake starts at %.3fs but the freeze at %.3fs — the speech would "
    "shake too" % (shake_from, start))

hz = 1.0 / period
assert 1.5 <= hz <= 2.6, (
    "shake period %.3fs = %.2f hits/s, measured reference is 2.00/s"
    % (period, hz))

# The decay must snap within the beat, or each hit smears into a slide. This
# is why DECAY is tied to the period rather than being an absolute number.
dec = re.findall(r"exp\(-([0-9.]+)\*", f)
assert dec, "no decay envelope on the shake"
assert float(dec[0]) >= 4.0, (
    "decay %.2f over a %.3fs beat drags each hit into a slide"
    % (float(dec[0]), period))

# --- panning is enabled, and produces a moving window ----------------------
env = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   ".env")
if os.path.exists(env):
    with open(env) as fh:
        body = fh.read()
    m = re.search(r"^CLIPPER_PAN=(\S+)", body, re.M)
    assert m and m.group(1) not in ("0", "false", "no"), (
        "CLIPPER_PAN is off in .env: the pillar crop falls back to a fixed "
        "window and a walking subject leaves frame")

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "media", "uf0a29714d9fe", "wyvzLKsUNF4.mp4")
try:
    import cv2  # noqa: F401
    have_cv2 = True
except ImportError:
    have_cv2 = False

if not (os.path.exists(SRC) and have_cv2 and os.path.exists(edit.FACE_MODEL)):
    print("_v46 ok (filter only) — shake confined to %.2f-%.2f at %.2f/s, "
          "CLIPPER_PAN on" % (start, DUR, hz))
    raise SystemExit(0)

card_h = int(edit.CANVAS_H * edit.PILLAR_COVER) // 2 * 2
was = edit.PAN
try:
    edit.PAN = True
    x = edit._pillar_pan_x(SRC, 122.0, 153.81, card_h)
finally:
    edit.PAN = was

assert "lt(t," in x, "PAN on still produced a static crop: %r" % x
keys = x.count("lt(t,")
assert keys >= 3, "only %d pan keyframes: the window is barely moving" % keys

# Ramps must be gradual. A keyframe pair closer than the ramp length would be
# a snap, which reads as a cut rather than a camera move. The expression shape
# is `+(delta)*(t-a)/LEN` — match the divisor that follows a (t-a) term, not
# any trailing number, or this picks up the positions instead.
ramps = [float(v) for v in re.findall(r"\(t-[0-9.]+\)/([0-9.]+)", x)]
assert ramps, "no ramp denominators in the pan expression: %r" % x[:200]
assert min(ramps) >= 0.4, "a pan ramp of %.2fs is a snap, not a move" % min(ramps)

# The pan must stay inside the source, or ffmpeg clamps and the move stalls.
pos = [float(v) for v in re.findall(r"0\.\d{4}", x)]
assert all(0.0 <= p <= 1.0 for p in pos), "a pan position left the source"

print("_v46 ok — jamet freeze+shake confined to %.2f-%.2f (%.2f hits/s, decay "
      "%.1f), pan on with %d keyframes, slowest ramp %.2fs"
      % (start, DUR, hz, float(dec[0]), keys, min(ramps)))
