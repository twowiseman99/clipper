"""The cutaway was not a photo. The compositor froze it.

The operator said twice that the b-roll "masih ga gerak". The source files
measured fine, which is what made the first diagnosis wrong:

    insert-vd75nAL4NkE.mp4   source motion 14.54
    same insert, in the clip at 18.3s          0.22

An overlay input starts at timeline t=0 regardless of when `enable` opens. A 3s
insert whose window opens at 18.3s has therefore ended 15 seconds earlier, and
ffmpeg holds its last frame for the whole hold. Every cutaway after the first
few seconds was guaranteed to be a frozen frame, no matter how lively the
footage was. The motion gate added earlier measures the SOURCE, so it could
never have caught this.

Run with real ffmpeg on synthetic footage, and the composited result is measured
the same way the shipped clip was measured.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import broll_place

TMP = "/tmp/_v15"
os.makedirs(TMP, exist_ok=True)
base = os.path.join(TMP, "base.mp4")
ins = os.path.join(TMP, "ins.mp4")
out_old = os.path.join(TMP, "old.mp4")
out_new = os.path.join(TMP, "new.mp4")

# 20s base, and a 3s insert that definitely moves.
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
     "color=c=navy:size=240x426:rate=25:duration=20", "-c:v", "libx264",
     "-preset", "ultrafast", base], check=True, capture_output=True)
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
     "testsrc2=size=240x426:rate=25:duration=3", "-c:v", "libx264",
     "-preset", "ultrafast", ins], check=True, capture_output=True)

WINDOW = (11.3, 14.3)


def motion(path, at, seconds):
    res = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{at}", "-t", f"{seconds}", "-i", path,
         "-vf", ("fps=10,scale=96:-1,tblend=all_mode=difference,signalstats,"
                 "metadata=print:key=lavfi.signalstats.YAVG:file=-"),
         "-f", "null", "-"], capture_output=True, text=True)
    vals = [float(m) for m in re.findall(r"YAVG=([0-9.]+)", res.stdout)][1:]
    return sum(vals) / len(vals) if vals else 0.0


def render(graph, out):
    res = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", base, "-i", ins,
         "-filter_complex", graph, "-map", "[vout]", "-t", "20",
         "-c:v", "libx264", "-preset", "ultrafast", out],
        capture_output=True, text=True)
    assert res.returncode == 0, f"ffmpeg rejected the graph: {res.stderr[:400]}"


# The old chain: no PTS shift. This is what shipped.
old = (f"[0:v]null[v0];[v0][1:v]overlay=0:0:shortest=0:"
       f"enable='between(t,{WINDOW[0]},{WINDOW[1]})'[vout]")
render(old, out_old)

# The new chain, straight from the module under test. Pinned to opacity=1.0 so
# this assertion measures the PTS fix alone: the module default is translucent
# now, and a 0.55 overlay legitimately measures lower motion.
new = ("[0:v]null[v0];"
       + broll_place.overlay_chain("[v0]", 1, WINDOW[0], WINDOW[1], "[vout]",
                                   opacity=1.0))
render(new, out_new)

m_old = motion(out_old, WINDOW[0] + 0.2, 2.4)
m_new = motion(out_new, WINDOW[0] + 0.2, 2.4)

assert m_old < 1.0, f"expected the old chain to freeze, measured {m_old:.2f}"
assert m_new > 4.0, f"insert still not moving in the window: {m_new:.2f}"
assert m_new > m_old * 5, f"not a real improvement: {m_old:.2f} -> {m_new:.2f}"

# Opacity has to survive the same path: a see-through cutaway still has to move.
graph_op = ("[0:v]null[v0];"
            + broll_place.overlay_chain("[v0]", 1, WINDOW[0], WINDOW[1],
                                        "[vout]", opacity=0.55))
out_op = os.path.join(TMP, "op.mp4")
render(graph_op, out_op)
m_op = motion(out_op, WINDOW[0] + 0.2, 2.4)
assert m_op > 1.5, f"translucent insert is frozen: {m_op:.2f}"

# And the base must be visible through it: a 0.55 overlay cannot look identical
# to the opaque one.
m_full = motion(out_new, WINDOW[0] + 0.2, 2.4)
assert abs(m_op - m_full) > 0.5, (
    f"opacity had no effect: opaque {m_full:.2f} vs translucent {m_op:.2f}")

for f in os.listdir(TMP):
    os.remove(os.path.join(TMP, f))
os.rmdir(TMP)

print(f"_v15.py OK — old chain froze at {m_old:.2f}, PTS-shifted insert moves "
      f"at {m_new:.2f}; at 55% opacity {m_op:.2f} and the speaker shows through")
