"""A centred crop is a framing decision, not a neutral default.

"Salah muka woi harusnya kan gibran" — the 31.8s pillar render framed an
escort officer and a bystander instead of the subject.

The cause was not face tracking. PAN is off in .env by the operator's own
choice ("user finds the movement distracting"), and _pillar_pan_x returned a
centred window before it ever looked at a face. The pillar card is 2560 wide
against a 1080 crop, so centre covers source x 0.29-0.71 — and the subject in
this scrum sits around 0.74, outside the rendered frame for 55% of the clip.

With PAN off the window is now PLACED ONCE and never moves. This test pins
both halves: the placement must beat centring, and the expression must contain
no time-varying term, because a crop that drifts is exactly what the operator
asked not to have.

Honest ceiling, measured on this clip — share of samples where the subject
sits inside the middle 60% of the window:

    centred         36%
    placed (0.67)   38%
    PAN on          100%  (7 keyframes)

Placement is a marginal gain, not a fix: the subject travels 0.52 of the frame
width while the window is only 0.42 wide, so no static position can hold him.
The test therefore asserts "better than centred and inside the frame most of
the time", which is all a static window can honestly promise. Choosing between
a still frame at 38% and a panning one at 100% is the operator's call, not a
threshold to tune.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edit  # noqa: E402

CANVAS_W = edit.CANVAS_W

# --- the placement rule, on synthetic tracks (no video needed) --------------
WIN = 1080 / 2560.0          # pillar window as a fraction of source width

# Subject parked on the right: the window must follow him there.
right = [(t * 0.5, 0.74) for t in range(40)]
expr = edit._static_window_x(right, WIN)
m = re.search(r"iw\*([0-9.]+)-ow/2", expr)
assert m, "no static centre in %r" % expr
assert abs(float(m.group(1)) - 0.74) < 0.06, (
    "window at %s for a subject at 0.74" % m.group(1))

# A static window must have NO time term: that is the whole point of PAN off.
assert "lt(" not in expr and "(t" not in expr, (
    "the static window varies with time: %r" % expr)

# Subject genuinely centred: do not shift for nothing.
mid = [(t * 0.5, 0.5) for t in range(40)]
m2 = re.search(r"iw\*([0-9.]+)-ow/2", edit._static_window_x(mid, WIN))
assert m2 and abs(float(m2.group(1)) - 0.5) < 0.02, "drifted off a centred subject"

# Ties go to the centremost window rather than an arbitrary edge.
spread = [(t * 0.5, 0.5 + (0.3 if t % 2 else -0.3)) for t in range(40)]
m3 = re.search(r"iw\*([0-9.]+)-ow/2", edit._static_window_x(spread, WIN))
assert m3 and abs(float(m3.group(1)) - 0.5) < 0.12, (
    "a symmetric split picked an off-centre window: %s" % m3.group(1))

# No samples at all must fall back to centre, not crash or invent a position.
assert edit._static_window_x([], WIN) == "'(iw-ow)/2'"

# --- end to end on the real segment ----------------------------------------
SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "media", "uf0a29714d9fe", "wyvzLKsUNF4.mp4")
try:
    import cv2  # noqa: F401
    have_cv2 = True
except ImportError:
    have_cv2 = False

if not (os.path.exists(SRC) and have_cv2 and os.path.exists(edit.FACE_MODEL)):
    print("_v45 ok (rule only) — placement 0.74, no time term, centre kept, "
          "empty falls back")
    raise SystemExit(0)

START, END = 122.0, 153.81
card_h = int(edit.CANVAS_H * edit.PILLAR_COVER) // 2 * 2

was = edit.PAN
try:
    edit.PAN = False
    x = edit._pillar_pan_x(SRC, START, END, card_h)
finally:
    edit.PAN = was

m = re.search(r"iw\*([0-9.]+)-ow/2", x)
assert m, "PAN off still produced a centred/other expression: %r" % x
assert "lt(" not in x, "PAN off produced a moving crop: %r" % x

centre = float(m.group(1))
pts = edit._sample_pan_faces(SRC, START, END)
cx = [c for _t, c in pts]
half = WIN / 2.0
placed = sum(1 for v in cx if centre - half <= v <= centre + half) / len(cx)
centred = sum(1 for v in cx if 0.5 - half <= v <= 0.5 + half) / len(cx)

assert placed > centred + 0.2, (
    "placement %.0f%% barely beats centring %.0f%%" % (placed * 100, centred * 100))
assert placed > 0.6, "subject only framed %.0f%% of the time" % (placed * 100)

print("_v45 ok — PAN off places the window at %.2f (no time term): subject "
      "framed %.0f%% vs %.0f%% centred, %d samples"
      % (centre, placed * 100, centred * 100, len(cx)))
