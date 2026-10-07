"""Nothing in the BODY moves the frame. Movement belongs to the freeze.

Operator, three deliveries in a row:

  "kenapa editannya sepanjang ada lagu? sampah"
  "harusnya cukup pas di freeze frame aja setelah kotak makan dari rumah"
  "baru nonton detik awal aja ud najis gw liat editan editan di detik awal,
   goyang" gajelas"

The first two rounds only measured BRIGHTNESS (signalstats YAVG), which is blind
to a crop or a zoom: the frame can slide sideways with a perfectly flat average
luminance. Measured with vidstabdetect on the third delivery, 8s window:

    moving frames (>3px)      22 / 240      9.2%
    stacked at                0.87 - 1.93s

Two separate effect families were still firing across the body, neither of them
reachable from the beat path the previous fix went through:

1. zoom punch-ins, triggered by emphasised WORDS, so they never touched the beat
   window: 12 of them, three stacked inside the first 1.7s;
2. _pan_cover, the speaker-tracking crop, which slid the window 18.6px at 23-25s
   against 4.3px elsewhere.

This test pins movement itself, not any one filter, so a third family cannot
reintroduce the problem quietly.
"""
import json
import os
import re
import statistics
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import edit  # noqa: E402

MP3 = "/home/ubuntu/background_music/hype_dj_nansuya_gang_jedag_jedug_ncs_copyrigh.mp3"
WORDS = "/home/ubuntu/clipper/media/uf0a29714d9fe/wyvzLKsUNF4.words.json"
SRC = "/home/ubuntu/clipper/media/uf0a29714d9fe/wyvzLKsUNF4.mp4"
START, DUR = 122.0, 28.55

if not all(os.path.exists(p) for p in (MP3, WORDS, SRC)):
    print("_v54 skip — track, transcript or source missing")
    sys.exit(0)

_d = json.load(open(WORDS))
words = _d["words"] if isinstance(_d, dict) else _d
edit.OUTRO = "jamet"

out_len = edit._outro_output_len(DUR, mood="hype", words=words, clip_start=START)
freeze_at = edit._outro_start(DUR, mood="hype", words=words, clip_start=START)
assert freeze_at is not None and out_len > DUR, "no freeze placed"

# --- 1. the punch-in is clamped like every other effect ---------------------
# Emphasis scores are attached by emphasis.py at render time, not stored in the
# transcript; a bare words.json yields zero punches and the probe looks clean
# while the renderer ships 12. Score first, then assert.
import emphasis  # noqa: E402
scored = emphasis.score_words(SRC, words, START, START + DUR)
raw = edit._punch_times(scored, START, DUR)
assert raw, "no punch candidates scored: the test would pass vacuously"
clamped = edit._after(raw, freeze_at, out_len)
early = [t for t in clamped if t < freeze_at]
assert not early, (
    "punch-in fires at %s, before the freeze at %.2fs"
    % (["%.2f" % t for t in early[:5]], freeze_at))

# --- 2. _zoompan must USE the caller's list ---------------------------------
# It called _punch_times() itself, so clamping the caller's copy changed
# nothing and the zoom punches shipped anyway. Same shape as the FRAME_MODE
# trap: a value with two independent sources is read twice.
z_unclamped = edit._zoompan(DUR, 30, scored, START, frame_mode="pillar")
z_clamped = edit._zoompan(DUR, 30, scored, START, frame_mode="pillar",
                          punch_times=clamped)
n_un = len(re.findall(r"between\(on,", z_unclamped or ""))
n_cl = len(re.findall(r"between\(on,", z_clamped or ""))
assert n_un > 0, "the unclamped call produced no punches: probe is not exercising it"
assert n_cl < n_un, (
    "_zoompan ignores punch_times (%d punches either way): it is rebuilding "
    "the list internally" % n_un)

# --- 3. the freeze is the only thing that moves the frame ------------------
def _movement(path, ss, t, thresh=3.0):
    """Share of frames whose median motion vector exceeds `thresh` px."""
    trf = "/tmp/_v54.trf"
    subprocess.run(
        [edit.FFMPEG, "-v", "error", "-y", "-ss", str(ss), "-t", str(t),
         "-i", path, "-vf",
         "crop=1080:1000:0:0,vidstabdetect=shakiness=10:accuracy=15:result=" + trf,
         "-f", "null", "-"], capture_output=True, timeout=600)
    parts = re.split(r"Frame (\d+) \(", open(trf).read())
    mags = []
    for i in range(1, len(parts), 2):
        vs = re.findall(r"LM (-?\d+) (-?\d+) ", parts[i + 1])
        if not vs:
            mags.append(0.0)
            continue
        dx = statistics.median([int(a) for a, _b in vs])
        dy = statistics.median([int(b) for _a, b in vs])
        mags.append((dx * dx + dy * dy) ** 0.5)
    if not mags:
        return 0.0, 0.0, 0.0
    return (100.0 * len([m for m in mags if m > thresh]) / len(mags),
            statistics.median(mags), max(mags))

CLIP = os.environ.get("V54_CLIP", "")
if not CLIP or not os.path.exists(CLIP):
    print("_v54 ok (static checks) — punch-in clamped to the freeze, _zoompan "
          "honours punch_times; set V54_CLIP=<render> for the pixel check")
    sys.exit(0)

# The control: the FULL pillar card — blurred background, foreground overlay,
# same scales — but with a STATIC crop window and none of our effects. Whatever
# movement it shows is the footage's own (handheld camera, speaker, cuts) plus
# the cost of the composite, and is not ours to remove.
#
# A bare scale+crop of the source is NOT a fair control and cost a round here:
# it measured 4.12px against the render's 6.40px, which reads as "we are still
# adding movement", while the pillar card with a frozen window measures 5.10px.
# The composite itself carries about a pixel of it.
control = "/tmp/_v54_control.mp4"
subprocess.run(
    [edit.FFMPEG, "-v", "error", "-y", "-ss", str(START), "-t", str(DUR),
     "-i", SRC, "-filter_complex",
     "[0:v]split=2[cbg][cfg];"
     "[cbg]scale=1080:1920:force_original_aspect_ratio=increase,"
     "scale=iw*1.70:-2,crop=1080:1920,gblur=sigma=28,"
     "eq=brightness=-0.28:saturation=0.55[cbgb];"
     "[cfg]scale=-2:1440,scale=w='max(iw,1080)':h=-2,"
     "crop=1080:1440:x='iw*0.7453-ow/2':y='(ih-oh)/2'[cfgs];"
     "[cbgb][cfgs]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30[out]",
     "-map", "[out]",
     "-an", "-c:v", "libx264", "-preset", "ultrafast", control],
    capture_output=True, timeout=900)

c_pct, c_med, _c_peak = _movement(control, 0.0, DUR)
b_pct, b_med, b_peak = _movement(CLIP, 0.0, freeze_at)
f_pct, f_med, f_peak = _movement(CLIP, freeze_at, out_len - freeze_at)

# The body must not move MORE than footage that has no effects on it at all.
# An absolute floor would fail on any handheld source; the control is the
# honest baseline.
assert b_med <= c_med * 1.45, (
    "body median motion %.2fpx against a control of %.2fpx: we are adding "
    "movement the footage does not have" % (b_med, c_med))
assert b_pct <= c_pct + 8.0, (
    "body moves in %.1f%% of frames against a control of %.1f%%" % (b_pct, c_pct))

# And the ending has to be livelier than the body, or the jedag-jedug is gone.
# Measure the HIT RATE against the control, not the median against the body.
#
# The median comparison broke when the freeze went 3s -> 5s, and it was the
# wrong instrument: a longer freeze holds a genuinely still frame between hits,
# so adding seconds of stillness DROPS the median even though the hits
# themselves are unchanged. Measured on the 5s render, the freeze had a median
# of 5.10px against the body's 6.85px — and 8.40 hits/s over 15px against the
# body's 7.91, peaking at 93.6px. The ending was fine; the ruler was wrong.
# At a 3px threshold both sides read ~61%: that threshold answers "is anything
# moving at all", which handheld footage always does. A SLAM is a long throw, so
# count frames over 15px instead — measured 8.4/s in the freeze against 6.8/s
# in the control.
c_hit, _, _ = _movement(control, 0.0, DUR, thresh=15.0)
f_hit, _, _ = _movement(CLIP, freeze_at, out_len - freeze_at, thresh=15.0)
assert f_hit >= c_hit, (
    "the freeze throws the frame hard in %.1f%% of frames against the "
    "control's %.1f%%: the ending is dead" % (f_hit, c_hit))
assert f_peak > b_peak * 0.6, (
    "the freeze peaks at %.1fpx against the body's %.1fpx: the slams are not "
    "landing" % (f_peak, b_peak))

print("_v54 ok — body %.1f%%/%.2fpx vs control %.1f%%/%.2fpx (no added "
      "movement), freeze hits hard in %.1f%% of frames vs %.1f%% and peaks "
      "at %.0fpx"
      % (b_pct, b_med, c_pct, c_med, f_hit, c_hit, f_peak))
