"""Compare a fresh render against the APPROVED jamet baseline.

The operator's question is "is the script still behaving" — that is a
regression question, so it needs the numbers the approved file produced, not an
impression of the new one.

Baseline is jobs/clip_1791642180_122_small.mp4, the file the operator approved
with "Cakep ni untuk preset jedag jedug sempurna".

Usage:  .venv/bin/python scripts/compare_to_baseline.py NEW.mp4 [BASELINE.mp4]
"""
import json
import os
import subprocess
import sys

import numpy as np

FFMPEG = "ffmpeg"
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_BASELINE = os.path.join(
    BASE, "jobs", "clip_1791642180_122_small.mp4")

# Approved values, measured off the baseline file. Tolerances are per-metric
# because they come from different instruments: x264 is not deterministic
# frame-for-frame, so motion figures wobble a few percent while geometry and
# duration must not move at all.
APPROVED = {
    "duration": (38.666667, 0.15),
    "width": (1080, 0),
    "height": (1920, 0),
}


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=width,height",
         "-of", "json", path],
        capture_output=True, text=True).stdout
    d = json.loads(out)
    st = [s for s in d["streams"] if s.get("width")][0]
    return (float(d["format"]["duration"]), int(st["width"]),
            int(st["height"]))


def frames(path, start, dur, scale=240):
    """Decode a window to greyscale arrays."""
    w = scale
    h = int(scale * 16 / 9)
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", "%.3f" % start, "-t", "%.3f" % dur,
         "-i", path, "-vf", "scale=%d:%d,format=gray" % (w, h),
         "-f", "rawvideo", "-"],
        capture_output=True).stdout
    n = len(raw) // (w * h)
    if n == 0:
        return np.empty((0, h, w), dtype=np.uint8)
    return np.frombuffer(raw[:n * w * h], dtype=np.uint8).reshape(n, h, w)


def motion(path, start, dur):
    """Mean and peak frame-to-frame difference -- how hard the picture moves."""
    a = frames(path, start, dur).astype(np.int16)
    if len(a) < 2:
        return 0.0, 0.0
    d = np.abs(np.diff(a, axis=0)).mean(axis=(1, 2))
    return float(d.mean()), float(d.max())


def hits(path, start, dur, floor=6.0):
    """Count displacement spikes -- the jedag-jedug hits."""
    a = frames(path, start, dur).astype(np.int16)
    if len(a) < 3:
        return 0, []
    d = np.abs(np.diff(a, axis=0)).mean(axis=(1, 2))
    peaks = []
    for i in range(1, len(d) - 1):
        if d[i] >= floor and d[i] > d[i - 1] and d[i] >= d[i + 1]:
            peaks.append(start + (i + 1) / 30.0)
    return len(peaks), peaks


def brightness(path, t):
    a = frames(path, t, 0.1)
    return float(a[0].mean()) if len(a) else -1.0


def report(path, label):
    dur, w, h = probe(path)
    # Windows are relative to the DELIVERED file: hook ~2.8s then the body,
    # freeze from ~31.3s, portrait from ~36.1s, dip at the very end.
    body = motion(path, 10.0, 6.0)
    freeze = motion(path, 31.5, 4.0)
    portr = motion(path, 36.3, 2.0)
    nhits, times = hits(path, 31.3, 4.8)
    print("%s" % label)
    print("  duration        %.3fs   %dx%d" % (dur, w, h))
    print("  body motion     mean %6.2f  peak %6.2f" % body)
    print("  freeze motion   mean %6.2f  peak %6.2f" % freeze)
    print("  portrait motion mean %6.2f  peak %6.2f" % portr)
    print("  hits in freeze  %d" % nhits)
    if times:
        print("  hit times       %s" % " ".join("%.2f" % t for t in times))
        if len(times) > 1:
            gaps = np.diff(times)
            print("  gap spread      %.2fs  (min %.2f max %.2f)"
                  % (float(gaps.max() - gaps.min()), float(gaps.min()),
                     float(gaps.max())))
    print("  bright @36.5    %6.2f   (portrait held)" % brightness(path, 36.5))
    print("  bright @last    %6.2f   (dip to black)"
          % brightness(path, max(0.0, dur - 0.1)))
    return {
        "duration": dur, "width": w, "height": h,
        "body": body, "freeze": freeze, "portrait": portr,
        "hits": nhits, "times": times,
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    new = sys.argv[1]
    base = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_BASELINE

    n = report(new, "NEW      %s" % os.path.basename(new))
    print()
    if os.path.exists(base):
        b = report(base, "BASELINE %s" % os.path.basename(base))
    else:
        print("BASELINE missing: %s" % base)
        b = None

    print()
    bad = []
    for key, (want, tol) in APPROVED.items():
        got = n[key]
        if abs(got - want) > tol:
            bad.append("  %-10s %s (approved %s)" % (key, got, want))
    # Shape questions, not tuning questions: the ending must still be an
    # ending. A held portrait that stopped moving means the shake regressed; a
    # last frame that is not black means the dip is being painted over again.
    if n["portrait"][1] < 2.0:
        bad.append("  portrait is HELD STILL (peak %.2f) -- the shake on the "
                   "photograph regressed" % n["portrait"][1])
    if brightness(new, max(0.0, n["duration"] - 0.1)) > 12.0:
        bad.append("  last frame is not black -- the dip is being painted "
                   "over")
    if n["hits"] < 3:
        bad.append("  only %d hits in the freeze -- clustering may have "
                   "collapsed" % n["hits"])
    if b and len(n["times"]) > 1 and len(b["times"]) > 1:
        sn = float(np.diff(n["times"]).std())
        sb = float(np.diff(b["times"]).std())
        print("hit-spacing std: new %.3f  baseline %.3f" % (sn, sb))

    if bad:
        print("DIVERGED from the approved preset:")
        print("\n".join(bad))
        return 1
    print("MATCHES the approved preset on every checked property.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
