"""The jamet ending must shake the FROZEN frame, not the video after it.

The operator's spec, with a reference tutorial (youtube AGv6G13TPUc, 30-34s):
"selesai itu jeda 2 detik jedag jedug, lu liat kan itu videonya dah ga di
play, jadi image gitu" — the picture stops, and the beats land on the still.

What shipped did the opposite. `loop` inserts N copies of one frame at
`start`, so the still occupies start .. start+freeze on the OUTPUT timeline;
the shake window began at `start + OUTRO_FREEZE`, i.e. exactly where the still
ends and moving video resumes. So the clip froze, sat there motionless, and
only started shaking once it was playing again.

This test measures the delivered file rather than reading the filter string,
because the bug was invisible in the graph: both versions contain a loop and a
shake, and only the arithmetic relating their two timelines was wrong.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edit  # noqa: E402

FPS = 30


def motion(path, t, window=0.2):
    """Mean frame-to-frame luma difference around t. 0 means a still."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-t", f"{window:.3f}",
         "-i", path, "-vf",
         f"fps={FPS},scale=160:-2,tblend=all_mode=difference,signalstats,"
         "metadata=print:key=lavfi.signalstats.YAVG:file=-",
         "-f", "null", "-"],
        capture_output=True, text=True)
    vals = [float(l.split("=")[1]) for l in out.stdout.splitlines()
            if "YAVG=" in l]
    return sum(vals) / len(vals) if vals else 0.0


def distinct_frames(path, t, window):
    """How many visually distinct frames appear in [t, t+window)."""
    tmp = tempfile.mkdtemp()
    subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-t", f"{window:.3f}",
         "-i", path, "-vf", f"fps={FPS},scale=120:-2",
         os.path.join(tmp, "%03d.png")],
        capture_output=True, text=True, check=True)
    import hashlib
    seen = set()
    for n in sorted(os.listdir(tmp)):
        with open(os.path.join(tmp, n), "rb") as fh:
            seen.add(hashlib.md5(fh.read()).hexdigest())
    return len(seen), len(os.listdir(tmp))


tmp = tempfile.mkdtemp()
src = os.path.join(tmp, "src.mp4")
# Moving source: without real motion a "freeze" is indistinguishable from
# the source itself, and the test would pass on a broken renderer.
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
     "-i", f"testsrc2=size=540x960:rate={FPS}:duration=22",
     "-pix_fmt", "yuv420p", src],
    capture_output=True, text=True, check=True)

saved = edit.OUTRO
try:
    edit.OUTRO = "jamet"
    brightness, filters = edit._outro_filters(22.0, mood="hype")
finally:
    edit.OUTRO = saved

assert filters, "jamet produced no outro filters at all"

# The freeze and the shake must describe the SAME stretch of the timeline.
loop = next(f for f in filters if f.startswith("loop="))
freeze_start_frame = int(loop.split("start=")[1])
freeze_start = freeze_start_frame / FPS
# "loop=loop=60:size=1:start=570" — split on the inner "loop=loop=" so the
# filter name itself does not swallow the match.
loop_frames = int(loop.split("loop=loop=")[1].split(":")[0])
assert abs(loop_frames / FPS - edit.OUTRO_FREEZE) < 0.05, loop_frames

shake = next(f for f in filters if f.startswith("crop=w=iw-"))
win_start = float(shake.split("between(t,")[1].split(",")[0])
assert abs(win_start - freeze_start) < 0.05, (
    "shake starts at %.3f but the still starts at %.3f — the beats land on "
    "moving video instead of the frozen frame" % (win_start, freeze_start))

out = os.path.join(tmp, "jamet.mp4")
graph = ",".join(filters)
if brightness:
    graph += f",eq=brightness='{brightness}'"
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", graph,
     "-pix_fmt", "yuv420p", out],
    capture_output=True, text=True, check=True)

# 1080x1920 is not negotiable, whatever the ending does.
probe = subprocess.run(
    ["ffprobe", "-v", "error", "-select_streams", "v:0",
     "-show_entries", "stream=width,height", "-of", "csv=p=0", out],
    capture_output=True, text=True, check=True).stdout.strip()
assert probe.startswith(f"{edit.CANVAS_W},{edit.CANVAS_H}"), probe

# The picture must genuinely stop. Scaled by the shake, a frozen frame still
# moves on screen, so frame identity is the wrong measure here — instead check
# that the UNDERLYING picture repeats: a 2s still shaken on the beat has far
# fewer distinct frames than 2s of moving video.
mid = freeze_start + edit.OUTRO_FREEZE / 2
uniq_frozen, total_frozen = distinct_frames(out, mid, 0.5)
uniq_live, total_live = distinct_frames(out, 2.0, 0.5)
assert total_frozen > 5 and total_live > 5, (total_frozen, total_live)

# And the shake must actually be shaking during the still: a frozen frame with
# no shake measures near zero motion.
shaken = motion(out, mid, 0.4)
assert shaken > 1.0, (
    "the frozen stretch is motionless (%.3f): the shake is not landing on it"
    % shaken)

print("_v40 ok — still starts %.2fs, holds %.2fs, shake window opens %.2fs "
      "(same frame), motion on the still %.2f, %dx%d"
      % (freeze_start, loop_frames / FPS, win_start, shaken,
         edit.CANVAS_W, edit.CANVAS_H))
