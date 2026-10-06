"""The exposure flicker follows the music, goes both ways, and matches the rate.

"efeknya kurang rusuh, guide jedag jedug nya gimana sih? di bedain exposurenya
di goyang goyangin ikutin beat lagu walau agak extream"

Three separate claims in that sentence, and the old flash failed all three.
Measured on the operator's reference (AGv6G13TPUc) using RAW brightness (YAVG
at 20fps), not frame-difference — every earlier measurement in this project
looked at motion, which cannot see an exposure change at all:

    reference   brightness sd 30.6, largest jump 38.2, 0.50 flicker events/s,
                11 jumps brighter and 10 darker, 16 of 21 within 0.3s of a beat
    ours        brightness sd 13.9, largest jump 16.2, 0.17 events/s

So: too few, too weak, one direction only, and timed to stressed WORDS rather
than to the track.

This test pins the three properties, not the constants, and it checks them on
real ffmpeg output. The numeric targets are in the comments on the constants in
edit.py.
"""
import os
import re
import statistics
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edit  # noqa: E402

YAVG = re.compile(r"lavfi\.signalstats\.YAVG=([0-9.]+)")
TRACK = ("/home/ubuntu/background_music/"
         "hype_dj_nansuya_gang_jedag_jedug_ncs_copyrigh.mp3")

if not os.path.exists(TRACK):
    print("_v49 skipped — hype track not on this box")
    sys.exit(0)

DUR = 31.81

# --- beats come from the track, and are real measurements -------------------
# Measure the BPM on ALL onsets, not on the selected flickers. Selection groups
# the flickers into bursts on purpose, so consecutive picks sit a sixteenth
# apart and "60 / median gap" reports 218 — the reference tutorial would read
# 600 by the same arithmetic. The onset stream is where tempo lives.
all_beats = edit._music_beats(TRACK, DUR, fraction=1.0)
assert all_beats, "no beats detected in the hype track"
all_gaps = [b - a for a, b in zip(all_beats, all_beats[1:]) if b - a < 2.0]
assert all_gaps, "beats are not spaced like a beat"
bpm = 60 / statistics.median(all_gaps)
# The track is ~116 BPM. A 3 dB onset gate also catches the half-beats and
# reports 237, which would double the flicker rate.
assert 70 < bpm < 160, (
    "detected %.1f BPM: the onset gate is picking up half-beats or noise" % bpm)

# The onsets must be locked to the music, which is the property the BPM check
# was really standing in for: every gap should be a multiple of one base period.
# Noise would scatter off that grid.
base = statistics.median([g for g in all_gaps if g < 0.45])
off_grid = [abs(g / base - round(g / base)) for g in all_gaps]
on_grid = len([e for e in off_grid if e < 0.2]) / len(off_grid)
assert on_grid > 0.85, (
    "only %.0f%% of onsets land on the %.3fs grid: these are not the track's "
    "beats" % (100 * on_grid, base))

beats = edit._music_beats(TRACK, DUR)
assert beats, "no flicker beats selected"

# An unreadable or missing track must yield nothing, never a synthetic grid —
# invented beats drift against the music within a few bars.
assert edit._music_beats("/nonexistent.mp3", DUR) == []

# --- the flicker rate matches the reference ---------------------------------
# Measure what the RENDERER builds. _music_beats now returns the chosen beats
# only; the burst runs that actually reach the screen come from _burst_times,
# and testing the stage before it reports a rate the viewer never sees.
flicker_times = edit._burst_times(beats)
expr = edit._flash_expr(flicker_times, DUR)
assert expr, "flash is off or produced no terms"
terms = expr.count("between(")
rate = terms / DUR
# The reference measures 1.05 pixel flicker events per second. Each flicker
# shows up as a rise AND a fall, so the term rate it corresponds to is ~0.53.
assert 0.45 <= rate <= 1.00, (
    "%.2f flicker terms/s against the reference's ~0.53: %d terms in %.1fs. "
    "Flickering on every detected beat measured 1.01/s on a delivered render, "
    "and keeping half of them still gave 0.88." % (rate, terms, DUR))

# The flickers must arrive in tight runs, not on a steady interval: that is the
# difference the operator heard as "editannya sepanjang ada lagu? sampah".
# Reference median spacing 0.10s, 80% of intervals under 0.8s.
fgaps = [b - a for a, b in zip(flicker_times, flicker_times[1:])]
assert statistics.median(fgaps) < 0.5, (
    "median flicker spacing %.2fs: this is a drip, not a burst (reference "
    "0.10s)" % statistics.median(fgaps))
assert max(fgaps) >= 2.0, (
    "longest quiet stretch %.2fs: without real gaps the effect reads as "
    "running under the whole song" % max(fgaps))
# And no quarter of the clip may be empty — an earlier selection left 15.7s
# with nothing in it while the song had 8 onsets sitting there.
quarters = [len([t for t in flicker_times if DUR * i / 4 <= t < DUR * (i + 1) / 4])
            for i in range(4)]
assert all(q > 0 for q in quarters), (
    "quarters %s: a whole region of the clip has no effects at all" % quarters)

# --- it goes both ways ------------------------------------------------------
dark = len(re.findall(r"-\d\.\d{3}\*between", expr))
bright = terms - dark
assert dark > 0, (
    "every flicker brightens: a white-only pop reads as a camera flash, not as "
    "the exposure being pushed around. The reference had 10 dark against 11 "
    "bright.")
assert abs(bright - dark) <= max(2, terms * 0.3), (
    "%d bright vs %d dark is lopsided against the reference's 11/10"
    % (bright, dark))

# --- and ffmpeg has to accept it, measured on a flat source -----------------
# A flat grey source means every brightness change in the output came from the
# flicker. `testsrc2` reads a 124-point jump on its own and measures nothing —
# an earlier version of this probe used it and reported the control as the
# strongest "flash" in the sweep.
out = "/tmp/_v49_flat.mp4"
proc = subprocess.run(
    [edit.FFMPEG, "-v", "error", "-y", "-f", "lavfi",
     "-i", "color=c=gray:size=360x640:rate=30:duration=%g" % DUR,
     "-vf", "fps=30,eq=brightness='%s':eval=frame" % expr,
     "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", out],
    capture_output=True, text=True, timeout=300)
assert proc.returncode == 0, "ffmpeg rejected the flicker expression:\n%s" % (
    proc.stderr[-600:])

meta = "/tmp/_v49_flat.txt"
subprocess.run(
    [edit.FFMPEG, "-v", "error", "-i", out, "-vf",
     "fps=20,scale=120:-1,signalstats,metadata=print:"
     "key=lavfi.signalstats.YAVG:file=" + meta, "-f", "null", "-"],
    check=True, timeout=300)
vals = [float(v) for v in YAVG.findall(open(meta).read())]
assert vals, "no brightness readings: metadata=print writes to the log, which " \
             "-v error suppresses, so it needs file="
# The encoder emits one near-black frame at the tail; it is not picture content.
med = statistics.median(vals)
vals = [v for v in vals if v > med * 0.1]
jumps = [abs(vals[i] - vals[i - 1]) for i in range(1, len(vals))]
peak = max(jumps)
assert peak > 25, (
    "largest brightness jump is only %.1f on a flat source: the reference's "
    "largest was 38.2 and our old clip managed 16.2" % peak)

# Negative control: with the flicker off, a flat source must not move at all.
# Without this, a probe that measures the SOURCE rather than the effect passes
# every threshold and proves nothing.
_was = edit.FLASH
edit.FLASH = False
try:
    assert edit._flash_expr(beats, DUR) == "", "FLASH=0 still emitted terms"
finally:
    edit.FLASH = _was

ctl = "/tmp/_v49_ctl.mp4"
subprocess.run(
    [edit.FFMPEG, "-v", "error", "-y", "-f", "lavfi",
     "-i", "color=c=gray:size=360x640:rate=30:duration=3",
     "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", ctl],
    check=True, timeout=120)
cmeta = "/tmp/_v49_ctl.txt"
subprocess.run(
    [edit.FFMPEG, "-v", "error", "-i", ctl, "-vf",
     "fps=20,scale=120:-1,signalstats,metadata=print:"
     "key=lavfi.signalstats.YAVG:file=" + cmeta, "-f", "null", "-"],
    check=True, timeout=120)
cvals = [float(v) for v in YAVG.findall(open(cmeta).read())]
cmed = statistics.median(cvals)
cvals = [v for v in cvals if v > cmed * 0.1]
cjumps = [abs(cvals[i] - cvals[i - 1]) for i in range(1, len(cvals))]
assert max(cjumps) < 2.0, (
    "a flat grey source with no flicker reads %.2f: the probe is measuring the "
    "source, not the effect" % max(cjumps))

print("_v49 ok — %d flickers (%d bright / %d dark) at %.2f/s on a %.1f BPM "
      "track, peak jump %.1f on flat grey, control %.2f"
      % (terms, bright, dark, rate, bpm, peak, max(cjumps)))
