"""The jamet freeze must hold to the END of the clip, and be measured there.

"harusnya videonya pause sampe akhir" — the picture froze at 28.80s, shook for
2s, and then the real footage started playing again for the last 3s.

Two separate bugs, and the second one is the expensive one:

1. OUTRO_FREEZE was a fixed 2.0s while the jamet ending is 3.0s, so the still
   ran out before the clip did. Worse, `loop` INSERTS its clones — the real
   tail follows them rather than being replaced, so cloning more frames made
   the clip LONGER (31.81s -> 34.83s) and the tail still played. It needs
   `trim=end=dur` to drop the tail.

2. The edit gate said PASS. Its check was "outro = 'jamet', last 3s" — i.e. it
   confirmed the SETTING it had just chosen, never the file. The operator
   found the moving tail, not the gate.

So this test pins both the filter shape and the probe that now watches it.

The discriminating statistic is the motion FLOOR, not the mean. A shaking still
and real video have similar means; a still returns to ~0 between beats and
video never does. Measured on the renders that drove this:

    frozen stretch, shaking     floor 0.39   mean 8.4
    tail where video resumed    floor 2.09   mean 6.5

A mean-based check cannot separate those two. A floor-based one does.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edit  # noqa: E402
import job  # noqa: E402

DUR = 12.0

_was = edit.OUTRO
edit.OUTRO = "jamet"
try:
    span = edit.OUTRO_JAMET_SECONDS
    start = edit._outro_start(DUR, mood="hype", seconds=span)
    assert start is not None, "no jamet outro on a 12s clip"

    head, chain = edit._outro_filters(DUR, mood="hype", seconds=span)
    assert head == "", "jamet returns its chain in the second element"
    joined = ",".join(chain)

    # --- the freeze covers the whole ending, not a fixed 2s -----------------
    m = re.search(r"loop=loop=(\d+):size=1:start=(\d+)", joined)
    assert m, "no loop filter in %r" % joined
    frames, loop_start = int(m.group(1)), int(m.group(2))
    freeze_secs = frames / float(edit.FPS)
    assert freeze_secs >= DUR - start - 0.05, (
        "freeze is %.2fs but the ending is %.2fs: the video resumes before the "
        "clip ends" % (freeze_secs, DUR - start))
    assert abs(loop_start / float(edit.FPS) - start) < 0.05, (
        "freeze starts at %.2fs, outro starts at %.2fs"
        % (loop_start / float(edit.FPS), start))

    # --- the inserted frames must not push the real tail into the clip ------
    assert re.search(r"trim=end=%.3f" % DUR, joined), (
        "no trim back to %.3fs: loop INSERTS frames, so without it the clip "
        "grows and the moving tail plays after the still" % DUR)

    # --- the shake window covers the whole frozen stretch -------------------
    wins = re.findall(r"between\(t,([0-9.]+),([0-9.]+)\)", joined)
    assert wins, "no shake window"
    lo, hi = float(wins[0][0]), float(wins[0][1])
    assert abs(lo - start) < 0.05, "shake starts at %.2f, freeze at %.2f" % (lo, start)
    assert hi >= start + freeze_secs - 0.05, (
        "shake window ends at %.2f but the still runs to %.2f: the last part "
        "of the freeze sits motionless" % (hi, start + freeze_secs))

    # --- ffmpeg has to ACCEPT it -------------------------------------------
    # A filter test that asserts on the string passes while ffmpeg rejects the
    # graph, and the render dies after the download and transcribe are paid
    # for. So build it for real.
    out = "/tmp/_v48_probe.mp4"
    proc = subprocess.run(
        [edit.FFMPEG, "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=360x640:rate=30:duration=%g" % DUR,
         "-vf", ",".join(["fps=30"] + chain),
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-t", "%g" % DUR, out],
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, "ffmpeg rejected the graph:\n%s" % proc.stderr[-600:]

    probed = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration", "-of", "csv=p=0", out],
        capture_output=True, text=True, timeout=60).stdout.strip()
    assert abs(float(probed) - DUR) < 0.25, (
        "output is %.2fs, asked for %.2fs: the inserted frames changed the "
        "clip length" % (float(probed), DUR))

    # --- the probe that guards this must tell a still from video ------------
    floor_frozen = job._freeze_floor(out, start + 0.05)
    assert floor_frozen is not None, (
        "the freeze probe returned None on a good file — metadata=print writes "
        "to the log, which -v error suppresses, so it needs file=")
    assert floor_frozen <= 1.5, (
        "frozen stretch reads floor %.2f: the probe would reject a correct "
        "ending" % floor_frozen)

    # Negative control: the SAME probe on moving video must come back high,
    # otherwise it passes everything and guards nothing.
    moving = "/tmp/_v48_moving.mp4"
    subprocess.run(
        [edit.FFMPEG, "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=360x640:rate=30:duration=4",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         moving], check=True, timeout=120)
    floor_moving = job._freeze_floor(moving, 0.5)
    assert floor_moving is not None, "probe failed on the control"
    assert floor_moving > 1.5, (
        "moving video reads floor %.2f, under the 1.5 threshold: the probe "
        "cannot tell a freeze from video and the gate is decorative"
        % floor_moving)
finally:
    edit.OUTRO = _was

print("_v48 ok — freeze %.2fs covers the %.2fs ending, trimmed back to %.1fs, "
      "ffmpeg accepts it; probe floor %.2f frozen vs %.2f moving"
      % (freeze_secs, DUR - start, DUR, floor_frozen, floor_moving))
