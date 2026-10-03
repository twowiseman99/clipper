"""The ending the operator asked for: half-grey, no dim, eased into slow motion.

Full greyscale read as "aneh" on playback. The operator's call: desaturate
halfway and slow the closing seconds down, so the ending shifts register
instead of looking like an obituary card.

Three things have to be true, and all three are measured on real ffmpeg output
rather than asserted on the filter string, because a string-only assertion has
already passed while ffmpeg rejected the graph (`hue=...:eval=frame`):

  1. colour drops, but only partway - a fully grey final frame is the old bug
  2. brightness does NOT drop - the dim is off now
  3. the closing window plays longer than its source span - that is the slowmo
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import edit

TMP = "/tmp/_v16"
os.makedirs(TMP, exist_ok=True)
src = os.path.join(TMP, "src.mp4")
out = os.path.join(TMP, "out.mp4")

# --- the settings themselves ----------------------------------------------
assert 0.3 <= edit.OUTRO_DESAT <= 0.7, \
    f"partial desaturation expected, got {edit.OUTRO_DESAT}"
assert edit.OUTRO_DIM == 0.0, f"dim should be off, got {edit.OUTRO_DIM}"
assert 0 < edit.OUTRO_SLOWMO < 1, f"slowmo must be a slowdown: {edit.OUTRO_SLOWMO}"

DUR = edit.OUTRO_SECONDS * 3 + 1
bright, filters = edit._outro_filters(DUR, mood="emotional")
assert bright == "", f"no brightness term expected, got {bright!r}"
assert any("hue=s=" in f for f in filters), filters
assert any("setpts=" in f for f in filters), f"no slowmo in the chain: {filters}"

# A hype clip must still get the stinger, and must NOT get slow motion: the
# mood split is the whole reason this function takes a mood.
hb, hf = edit._outro_filters(DUR, mood="hype")
assert hb and not hf, f"hype should be a brightness stinger only: {hb!r} {hf}"

# --- real render, saturated source so a drop is measurable ----------------
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
     f"testsrc2=size=240x426:rate=25:duration={DUR:.0f}",
     "-c:v", "libx264", "-preset", "ultrafast", src],
    check=True, capture_output=True)

chain = list(filters)
if bright:
    chain.append(f"eq=brightness='{bright}':eval=frame")
res = subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", ",".join(chain),
     "-c:v", "libx264", "-preset", "ultrafast", out],
    capture_output=True, text=True)
assert res.returncode == 0, f"ffmpeg rejected the ending: {res.stderr[:400]}"


def stat(path, at, key):
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{at}", "-i", path, "-frames:v", "1",
         "-vf", f"signalstats,metadata=print:key=lavfi.signalstats.{key}:file=-",
         "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(rf"{key}=([0-9.]+)", r.stdout)
    return float(m.group(1)) if m else None


start = DUR - edit.OUTRO_SECONDS
sat_before = stat(out, max(0.5, start - 2), "SATAVG")
sat_mid = stat(out, start + edit.OUTRO_SECONDS * 0.6, "SATAVG")
y_before = stat(out, max(0.5, start - 2), "YAVG")
y_mid = stat(out, start + edit.OUTRO_SECONDS * 0.6, "YAVG")

assert None not in (sat_before, sat_mid, y_before, y_mid), "signalstats gave nothing"
# Colour has to actually come down inside the window.
assert sat_mid < sat_before * 0.92, \
    f"colour did not drain: {sat_before:.2f} -> {sat_mid:.2f}"
# But not all the way: half-grey is the point. The old full-greyscale ending
# measured 0.61 on the delivered clip.
assert sat_mid > sat_before * 0.25, \
    f"too grey, this is the obituary look again: {sat_before:.2f} -> {sat_mid:.2f}"
# Brightness must be left alone now that the dim is off.
assert abs(y_mid - y_before) < y_before * 0.25, \
    f"brightness moved although dim is off: {y_before:.2f} -> {y_mid:.2f}"

# --- the slowmo has to lengthen the output --------------------------------
def duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(r.stdout.strip())


d_src, d_out = duration(src), duration(out)
expected = edit.OUTRO_SECONDS * (1.0 / edit.OUTRO_SLOWMO - 1.0)
assert d_out > d_src + expected * 0.6, (
    f"ending did not slow down: {d_src:.2f}s -> {d_out:.2f}s, "
    f"expected about +{expected:.2f}s")

for f in os.listdir(TMP):
    os.remove(os.path.join(TMP, f))
os.rmdir(TMP)

print(f"_v16.py OK — desat {edit.OUTRO_DESAT} drops SATAVG {sat_before:.1f} -> "
      f"{sat_mid:.1f} (not to zero), brightness held {y_before:.1f} -> "
      f"{y_mid:.1f}, slowmo {edit.OUTRO_SLOWMO} stretched {d_src:.1f}s -> "
      f"{d_out:.1f}s; hype still gets the stinger")
