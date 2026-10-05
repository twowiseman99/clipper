"""The pan tracker must not be WORSE than largest-face, and must stay sane.

This test started life asserting the tracker was a large improvement. That
claim was wrong and this file records why, because the same mistake is easy to
repeat.

With three hand-checked subject positions (t=122/140/146) the numbers looked
decisive: largest-face 0.344 mean error, appearance tracker 0.110. Two more
checked frames reversed it:

    ground truth             largest-face   tracker
    3 points (122,140,146)        0.344       0.110
    5 points (+132,+150)          0.094       0.079

t=132 was the frame that mattered: the subject is at cx 0.78 there, on the
RIGHT, so "the biggest face is on the right" was correct and the three-point
sample had no example of it. Three points were not a measurement, they were a
story that fitted.

So the tracker is kept — it is no worse and it holds identity across the
frames where the subject is undetected — but it is NOT the fix for the
operator's "salah muka". That was a centred crop window; see _v45.

What this test actually guards:
  - the tracker does not regress below largest-face on 5 checked points
  - it never emits a centre outside the frame or out of time order
  - _pan_anchor stays inert (it measured worse; kept only as a record)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edit  # noqa: E402

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "media", "uf0a29714d9fe", "wyvzLKsUNF4.mp4")
if not os.path.exists(SRC):
    print("_v44 skip — source not downloaded")
    raise SystemExit(0)

try:
    import cv2
except ImportError:
    print("_v44 skip — cv2 missing")
    raise SystemExit(0)

if not os.path.exists(edit.FACE_MODEL):
    print("_v44 skip — face model missing")
    raise SystemExit(0)

START, END = 122.0, 153.81

# Hand-checked from the source frames. 132 and 150 are the two that corrected
# the original three-point reading — do not drop them.
TRUTH = {122.0: 0.67, 132.0: 0.78, 140.0: 0.51, 146.0: 0.37, 150.0: 0.36}


def error(pts):
    assert pts, "no pan samples at all"
    return sum(abs(min(pts, key=lambda p: abs(START + p[0] - t))[1] - want)
               for t, want in TRUTH.items()) / len(TRUTH)


def largest_per_frame():
    """The rule this replaced: biggest face in each sampled frame."""
    cap = cv2.VideoCapture(SRC)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    scale = min(1.0, 960.0 / W)
    dw, dh = int(W * scale), int(H * scale)
    det = cv2.FaceDetectorYN_create(edit.FACE_MODEL, "", (dw, dh), 0.6, 0.3, 5000)
    every = max(1, int(round(fps * edit.PAN_STEP)))
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(START * fps))
    pts, idx = [], 0
    while True:
        ok, frame = cap.read()
        if not ok or START + idx / fps >= END:
            break
        if idx % every == 0:
            small = cv2.resize(frame, (dw, dh))
            _ok, faces = det.detect(small)
            if faces is not None and len(faces):
                f = max(faces, key=lambda f: float(f[2]) * float(f[3]))
                pts.append((idx / fps, (float(f[0]) + float(f[2]) / 2) / dw))
        idx += 1
    cap.release()
    return pts


base = error(largest_per_frame())
pts = edit._sample_pan_faces(SRC, START, END)
now = error(pts)

# No regression. The margin is small and that is the finding, not a defect —
# assert the direction, not an invented improvement factor.
assert now <= base + 0.01, (
    "the tracker (%.3f) is worse than largest-face (%.3f)" % (now, base))

# Both are usable on this clip; a tracker that drifted off the subject (an
# earlier position-only version reached 0.221) must fail here.
assert now < 0.15, "mean error %.3f: the track is not on the subject" % now

# Structural guarantees: a rejected sample is skipped, never invented.
assert all(0.0 <= cx <= 1.0 for _t, cx in pts), "a centre fell outside the frame"
assert all(b[0] > a[0] for a, b in zip(pts, pts[1:])), "samples out of order"
assert len(pts) >= len(TRUTH), "too few samples to follow anyone"

# _pan_anchor measured worse (it locked onto the escort); it must stay inert so
# nobody wires it back in by accident.
assert edit._pan_anchor(SRC, START, END) is None, (
    "_pan_anchor is documented as measuring worse but is returning a value")

print("_v44 ok — tracker %.3f vs largest-face %.3f on %d checked points "
      "(no regression, both usable), %d samples in order, anchor inert"
      % (now, base, len(TRUTH), len(pts)))
