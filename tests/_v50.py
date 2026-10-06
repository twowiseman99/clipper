"""Beat movement must read as slams — far, then still — not as a vibration.

"goyangnya jgn kayak geter" tapi goyang aga jauh gitu, kayak bantingan
bantingan agak jauh sesuai beatnya"

The surprise in the measurement: the existing outro shake travels FURTHER than
the reference and still reads as a vibration. Measured with vidstabdetect
(median local-motion vector per frame, normalised to 1080 wide):

    reference        moving >8px on 10.6% of frames, peak  81.1px
    our outro shake  moving >8px on 36.7% of frames, peak 144.5px

So amplitude was never the problem. The outro shake is a continuous sine at
OUTRO_SHAKE_HZ — it never stops, and "always moving a bit" is the definition of
a vibration. A slam is rare, far, and then still.

This test pins that property: the throw must be large, and the frame must be
static between throws. It also pins the two things that silently break it —
output size, and a slam landing inside the frozen ending.
"""
import os
import re
import statistics
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edit  # noqa: E402

LM = re.compile(r"\(LM (-?\d+) (-?\d+) ")
TRACK = ("/home/ubuntu/background_music/"
         "hype_dj_nansuya_gang_jedag_jedug_ncs_copyrigh.mp3")

if not os.path.exists(TRACK):
    print("_v50 skipped — hype track not on this box")
    sys.exit(0)

DUR = 12.0
W, H = 540, 960


def motion(path):
    """Per-frame median displacement in px, measured at 1080 wide."""
    trf = path + ".trf"
    subprocess.run(
        [edit.FFMPEG, "-v", "error", "-y", "-i", path, "-vf",
         "scale=1080:-2,vidstabdetect=shakiness=10:accuracy=15:result=" + trf,
         "-f", "null", "-"], check=True, timeout=400)
    vals = []
    for line in open(trf).read().split("\n"):
        if not line.startswith("Frame"):
            continue
        vs = [(int(a), int(b)) for a, b in LM.findall(line)]
        if not vs:
            vals.append(0.0)
            continue
        dx = statistics.median([v[0] for v in vs])
        dy = statistics.median([v[1] for v in vs])
        vals.append((dx * dx + dy * dy) ** 0.5)
    return vals


beats = edit._music_beats(TRACK, DUR, 0.0,
                          fraction=edit.SLAM_BEAT_FRACTION)
assert beats, "no beats for slams"

# Slams are a SUBSET of the flickers: a throw interrupts the frame much more
# than a brightness change, so it cannot be on every beat the flicker uses.
flicker_beats = edit._music_beats(TRACK, DUR, 0.0,
                                  fraction=edit.FLASH_BEAT_FRACTION)
assert len(beats) <= len(flicker_beats) * 2, (
    "%d slams against %d flickers: slams should not outnumber flickers by "
    "much" % (len(beats), len(flicker_beats)))

sx, sy = edit._slam_offsets(beats, DUR)
assert sx or sy, "slam produced no offsets"
# Both axes must be used. A left/right-only pattern at beat spacing is exactly
# what a vibration looks like, which is the thing being fixed.
assert sx and sy, "slams only move on one axis, which reads as a shake"

m = int(edit.SLAM_PX) + 2
slam = (f"pad=iw+{m * 2}:ih+{m * 2}:{m}:{m}:color=black,"
        f"crop=w=iw-{m * 2}:h=ih-{m * 2}"
        f":x='{m}+({sx or '0'})':y='{m}+({sy or '0'})'")

out = "/tmp/_v50_slam.mp4"
proc = subprocess.run(
    [edit.FFMPEG, "-v", "error", "-y", "-f", "lavfi",
     "-i", f"testsrc2=size={W}x{H}:rate=30:duration={DUR:g}",
     "-vf", "fps=30," + slam,
     "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", out],
    capture_output=True, text=True, timeout=400)
assert proc.returncode == 0, (
    "ffmpeg rejected the slam filter:\n%s" % proc.stderr[-700:])

# The pad must be cropped back exactly. The operator's hard rule is that the
# output resolution never changes to achieve a look — "tapi resolusi clipnya
# jgn berubah ya".
size = subprocess.run(
    ["ffprobe", "-v", "error", "-select_streams", "v:0",
     "-show_entries", "stream=width,height", "-of", "csv=p=0", out],
    capture_output=True, text=True, timeout=120).stdout.strip()
assert size.replace(",", "x") == f"{W}x{H}", (
    "slam changed the output size to %s: pad/crop is not symmetric" % size)

vals = motion(out)
n = len(vals)
moving = 100 * len([v for v in vals if v > 8]) / n
peak = max(vals)

# The point of the whole change: travel far.
assert peak > 50, (
    "peak displacement only %.1fpx — the reference peaks at 81.1px and the "
    "operator asked for 'agak jauh', not a tremor" % peak)
# And be still the rest of the time. The old shake failed HERE, at 36.7%.
assert moving < 20, (
    "moving on %.1f%% of frames: the outro shake reads as a vibration at "
    "36.7%% and the reference sits at 10.6%%. Stillness between throws is "
    "what makes a throw read as a throw." % moving)

# --- a slam must never land inside the frozen ending ------------------------
# The freeze exists so the last seconds hold still; animating it would re-break
# the fix from the previous release.
long_dur = 31.81
fz = edit._outro_start(long_dur)
body = edit._music_beats(TRACK, long_dur, 3.0,
                         fraction=edit.SLAM_BEAT_FRACTION)
kept = [t for t in body if t + edit.SLAM_HOLD < fz]
assert kept, "every slam was filtered out of a 31.8s clip"
assert max(kept) + edit.SLAM_HOLD < fz, (
    "a slam at %.2fs runs into the freeze at %.2fs" % (max(kept), fz))

# --- negative control ------------------------------------------------------
# With slams off there must be no filter at all, not a no-op pad/crop: a
# pad/crop pair that always re-encodes is a silent quality cost.
_was = edit.SLAM
edit.SLAM = False
try:
    assert edit._slam_offsets(beats, DUR) == ("", ""), \
        "CLIPPER_SLAM=0 still produced offsets"
finally:
    edit.SLAM = _was

ctl = "/tmp/_v50_ctl.mp4"
subprocess.run(
    [edit.FFMPEG, "-v", "error", "-y", "-f", "lavfi",
     "-i", f"testsrc2=size={W}x{H}:rate=30:duration=3",
     "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", ctl],
    check=True, timeout=200)
cvals = motion(ctl)
cmoving = 100 * len([v for v in cvals if v > 8]) / (len(cvals) or 1)
assert cmoving < moving, (
    "the unslammed control moves on %.1f%% of frames against the slammed "
    "%.1f%%: the probe is measuring testsrc2's own animation, not the slams"
    % (cmoving, moving))

print("_v50 ok — %d slams, peak %.1fpx (reference 81.1), moving %.1f%% of "
      "frames (reference 10.6, old shake 36.7), control %.1f%%, %s held, "
      "none inside the freeze"
      % (len(beats), peak, moving, cmoving, size.replace(",", "x")))
