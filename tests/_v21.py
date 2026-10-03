"""The b-roll band has to be real, not a filter string that looks right.

0.55 opacity across the whole frame was the wrong middle. A reviewer reading a
delivered clip: "too high in opacity for a background and too low for a
statement, so it neither reads cleanly as Gaza footage nor leaves the speaker
crisp" — the rubble landed on the lectern, the speaker's hands and the state
emblem, and both pictures lost.

Option C is the fix the operator picked: footage confined to the upper band
where there is only backdrop, face and lectern untouched.

This test invokes ffmpeg for real. A filter test that asserts on the STRING
passes while ffmpeg refuses the graph — that has already cost one render here
(filter `hue` has no `eval` option, and the whole graph was rejected after the
download and transcribe had run).
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import broll_place as bp

TMP = "/tmp/_v21"
os.makedirs(TMP, exist_ok=True)
W, H = 360, 640          # same 9:16 shape as the real canvas, cheap to render
BAND_PX = H * bp.BAND_FRAC


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, f"ffmpeg refused:\n{' '.join(cmd)}\n{r.stderr[-900:]}"
    return r


def yavg(path, at, crop):
    """Mean luma of a cropped region of one frame."""
    r = run(["ffmpeg", "-v", "error", "-ss", f"{at}", "-i", path,
             "-frames:v", "1", "-vf", f"crop={crop},signalstats,"
             "metadata=print:key=lavfi.signalstats.YAVG:file=-",
             "-f", "null", "-"])
    vals = [float(m) for m in re.findall(r"YAVG=([0-9.]+)", r.stdout)]
    assert vals, f"no YAVG for {path} @{at} crop={crop}"
    return vals[0]


# Base = black (luma ~16), insert = white (luma ~235). Anywhere the insert
# shows through, luma rises; anywhere it is masked out, luma stays at the base.
base = os.path.join(TMP, "base.mp4")
ins = os.path.join(TMP, "ins.mp4")
run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
     f"color=c=black:size={W}x{H}:rate=25:duration=6",
     "-c:v", "libx264", "-preset", "ultrafast", base])
run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
     f"color=c=white:size={W}x{H}:rate=25:duration=3",
     "-c:v", "libx264", "-preset", "ultrafast", ins])

# --- the band graph has to be accepted by ffmpeg ------------------------
banded = os.path.join(TMP, "banded.mp4")
chain = bp.overlay_chain("[0:v]", 1, 2.0, 5.0, "[out]", canvas_h=H)
run(["ffmpeg", "-v", "error", "-y", "-i", base, "-i", ins,
     "-filter_complex", chain, "-map", "[out]",
     "-c:v", "libx264", "-preset", "ultrafast", banded])

# --- and it has to actually confine the footage ------------------------
# Inside the window: top shows the insert, bottom does not.
top = yavg(banded, 3.0, f"{W}:{int(BAND_PX * 0.5)}:0:0")
bottom = yavg(banded, 3.0, f"{W}:{int(H * 0.3)}:0:{int(H * 0.7)}")
assert top > 90, f"the band did not light up: top luma {top:.1f}"
assert bottom < 30, f"footage leaked below the band: bottom luma {bottom:.1f}"
assert top - bottom > 70, f"band and clean area too close: {top:.1f}/{bottom:.1f}"

# --- the feather must be a ramp, not a hard edge ----------------------
# Sample three thin rows across the fade and require a descending sequence.
solid_end = BAND_PX * (1 - bp.BAND_FEATHER)
rows = []
for frac in (0.1, 0.5, 0.95):
    y = int(solid_end + (BAND_PX - solid_end) * frac)
    rows.append(yavg(banded, 3.0, f"{W}:6:0:{y}"))
assert rows[0] > rows[1] > rows[2], f"feather is not a ramp: {rows}"

# --- outside its window the insert must be gone ------------------------
before = yavg(banded, 0.5, f"{W}:{int(BAND_PX * 0.5)}:0:0")
assert before < 30, f"insert visible before its window: {before:.1f}"

# --- the speaker's half of the frame is untouched ----------------------
# Whole-frame opacity was the old behaviour; prove the new chain is different.
flat = os.path.join(TMP, "flat.mp4")
chain_flat = bp.overlay_chain("[0:v]", 1, 2.0, 5.0, "[out]", opacity=0.55)
run(["ffmpeg", "-v", "error", "-y", "-i", base, "-i", ins,
     "-filter_complex", chain_flat, "-map", "[out]",
     "-c:v", "libx264", "-preset", "ultrafast", flat])
flat_bottom = yavg(flat, 3.0, f"{W}:{int(H * 0.3)}:0:{int(H * 0.7)}")
assert flat_bottom > 80, f"control failed: flat overlay should wash the " \
                         f"bottom, got {flat_bottom:.1f}"
assert flat_bottom - bottom > 50, (
    f"band is no cleaner than the old flat wash: {bottom:.1f} vs "
    f"{flat_bottom:.1f}")

# --- band disabled falls back to the flat wash -------------------------
assert bp._band_filters(H, 0.8, band_frac=1.0) == "", \
    "band_frac >= 1 must disable the mask"

for f in os.listdir(TMP):
    os.remove(os.path.join(TMP, f))
os.rmdir(TMP)

print(f"_v21.py OK — ffmpeg accepts the band graph; inside the window top luma "
      f"{top:.0f} vs bottom {bottom:.0f} (old flat wash left {flat_bottom:.0f} "
      f"over the speaker); feather descends {rows[0]:.0f}->{rows[2]:.0f}")
