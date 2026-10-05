"""Is the jamet outro actually freezing the picture?

The shake translates the frame, so a plain frame-difference reads motion even
on a still. Compensate for the translation first: search a small range of
offsets and keep the best match. A frozen picture matches almost exactly once
shifted back; moving video does not, however you shift it.
"""
import itertools
import subprocess
import sys

from PIL import Image, ImageChops

VID = sys.argv[1] if len(sys.argv) > 1 else "jobs/clip_1791214396_143.mp4"


def grab(t, tag):
    path = f"/tmp/fz_{tag}.png"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{t}", "-t", "0.04",
         "-i", VID, "-vf", "crop=900:700:90:300,scale=180:-2",
         "-frames:v", "1", path],
        check=True, capture_output=True)
    return Image.open(path).convert("L")


def best_diff(a, b, reach=14):
    """Lowest mean abs difference over a range of translations."""
    best = None
    for dx, dy in itertools.product(range(-reach, reach + 1, 2), repeat=2):
        shifted = ImageChops.offset(b, dx, dy)
        diff = ImageChops.difference(a, shifted)
        inner = diff.crop((22, 22, diff.width - 22, diff.height - 22))
        px = list(inner.getdata())
        mean = sum(px) / len(px)
        if best is None or mean < best:
            best = mean
    return best


pairs = [
    ("CONTROL moving video 6.0 vs 7.3", 6.0, 7.3),
    ("CONTROL moving video 6.0 vs 6.3", 6.0, 6.3),
    ("FROZEN stretch  19.2 vs 20.9", 19.2, 20.9),
    ("FROZEN stretch  19.2 vs 20.0", 19.2, 20.0),
]
for label, t1, t2 in pairs:
    a = grab(t1, f"{t1}")
    b = grab(t2, f"{t2}")
    print("%-34s best aligned diff %.2f" % (label, best_diff(a, b)))
