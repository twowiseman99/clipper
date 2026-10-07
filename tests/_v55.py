"""The freeze runs a full 5 seconds, with picture, on beat.

Operator: "Setelah "Sebab itu yg dimasak ibu" / Lansung freze frame jedag jedug
goyang sama perubahan exposure, ikutin beat selama 5 detik".

The freeze already started in the right place — 28.20s, the end of "...yang
dimasak ikut" — so this is about its LENGTH and about the effects filling it.

Raising OUTRO_JAMET_SECONDS 3.0 -> 5.0 exposed a frame-rate bug that had been
hiding behind the shorter window. The chain was:

    overlay -> loop=loop=150:size=1:start=846 -> trim=end=33.200 -> ... -> fps=30

`loop` counts FRAMES and `start` is computed as start*FPS, so both have to
agree on what a frame is. This source is 60fps and the conversion sat at the
END of the chain, so loop ran on the 60fps stream:

    start=846 @60fps  ->  14.10s, not 28.20s
    loop=150  @60fps  ->   2.50s of clones, not 5.00s

The file then reported 33.20s of audio over 31.07s of video — the last 2.1s had
no picture at all — and the flicker stopped at +2.50s into the freeze. Measured
932 frames out, exactly (28.55 + 150/60) * 30: the arithmetic was right and the
frame RATE was wrong, which is why the graph read as correct.

Confirmed in ffmpeg on a 60fps source, same expressions:

    fps AFTER  loop   ->  932 frames / 31.07s
    fps BEFORE loop   ->  996 frames / 33.20s

This test asserts the output's own duration and frame count, so a rate mismatch
anywhere in the chain cannot pass.
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
START, DUR = 122.0, 28.55

if not all(os.path.exists(p) for p in (MP3, WORDS)):
    print("_v55 skip — track or transcript missing")
    sys.exit(0)

_d = json.load(open(WORDS))
words = _d["words"] if isinstance(_d, dict) else _d
edit.OUTRO = "jamet"

# --- 1. the window is five seconds long ------------------------------------
assert edit.OUTRO_JAMET_SECONDS >= 5.0, (
    "OUTRO_JAMET_SECONDS is %.1f: the operator asked for 5 seconds"
    % edit.OUTRO_JAMET_SECONDS)

out_len = edit._outro_output_len(DUR, mood="hype", words=words, clip_start=START)
freeze_at = edit._outro_start(DUR, mood="hype", words=words, clip_start=START)
assert freeze_at is not None, "no freeze placed"
window = out_len - freeze_at
assert window >= 4.9, (
    "the freeze window is %.2fs, not 5s (starts %.2f, output ends %.2f)"
    % (window, freeze_at, out_len))

# --- 2. fps conversion happens BEFORE loop ---------------------------------
_, filters = edit._outro_filters(DUR, mood="hype", words=words,
                                 clip_start=START)
chain = ",".join(filters)
i_fps = chain.find("fps=")
i_loop = chain.find("loop=loop=")
assert i_loop != -1, "no freeze loop in the jamet outro filters"
assert i_fps != -1 and i_fps < i_loop, (
    "fps conversion is not ahead of the loop: loop counts frames and start is "
    "start*FPS, so on a 60fps source the freeze lands at half its intended "
    "time and length")

# --- 3. the effects fill the window, evenly --------------------------------
flashes = edit._window_beats(MP3, freeze_at, out_len, 0.0)
slams = edit._window_beats(MP3, freeze_at, out_len, 0.0,
                           fraction=edit.SLAM_BEAT_FRACTION)
assert len(flashes) >= 5, (
    "only %d exposure hits in a %.1fs window" % (len(flashes), window))
assert slams, "no slams in the freeze"

gaps = [flashes[i + 1] - flashes[i] for i in range(len(flashes) - 1)]
assert max(gaps) <= 1.0, (
    "largest gap between exposure hits is %.2fs: a hole that long reads as the "
    "effect having stopped" % max(gaps))

# Every second of the freeze carries something, so the ending cannot be
# front-loaded and then die.
per_second = [0] * int(window)
for t in sorted(set(flashes) | set(slams)):
    k = int(t - freeze_at)
    if 0 <= k < len(per_second):
        per_second[k] += 1
assert all(per_second), (
    "empty seconds inside the freeze: %s" % per_second)

# --- 4. the delivered file, if given --------------------------------------
CLIP = os.environ.get("V55_CLIP", "")
if not CLIP or not os.path.exists(CLIP):
    print("_v55 ok (static checks) — %.2fs window, %d exposure hits (largest "
          "gap %.2fs) + %d slams, every second filled, fps ahead of loop; set "
          "V55_CLIP=<render> for the file check"
          % (window, len(flashes), max(gaps), len(slams), ))
    sys.exit(0)


def _probe(stream, fields):
    """{field: value} for one stream. ffprobe returns csv in ITS declared
    order, not the order you asked for, so positional unpacking silently
    mismatched width against duration here."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream,
         "-show_entries", "stream=" + fields, "-of", "default=nw=1", CLIP],
        capture_output=True, text=True, timeout=300)
    out = {}
    for line in r.stdout.strip().splitlines():
        if "=" in line:
            k, _, val = line.partition("=")
            out[k.strip()] = val.strip()
    return out


v = _probe("v", "duration,nb_frames,width,height")
a = _probe("a", "duration")
v_dur, v_frames = float(v["duration"]), int(v["nb_frames"])
w, h = int(v["width"]), int(v["height"])
a_dur = float(a["duration"])

assert (w, h) == (1080, 1920), "resolution is %dx%d, not 1080x1920" % (w, h)
# Video and audio must agree. They differed by 2.13s in the broken render, and
# a duration field alone would not have caught it: the container reported the
# audio's 33.20s while the picture ran out at 31.07s.
assert abs(v_dur - a_dur) < 0.1, (
    "video is %.2fs but audio is %.2fs: %.2fs of the clip has no picture"
    % (v_dur, a_dur, a_dur - v_dur))
assert abs(v_dur - out_len) < 0.15, (
    "file is %.2fs, expected %.2fs" % (v_dur, out_len))
assert abs(v_frames - round(out_len * edit.FPS)) <= 2, (
    "file has %d frames, expected %d" % (v_frames, round(out_len * edit.FPS)))

# Exposure changes: a spike that RETURNS within ~0.1s is ours; a step that
# holds is the footage cutting to a new shot.
subprocess.run(
    [edit.FFMPEG, "-v", "error", "-y", "-i", CLIP, "-vf",
     "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=/tmp/_v55.txt",
     "-f", "null", "-"], capture_output=True, timeout=600)
d = [(float(t), float(y)) for t, y in re.findall(
    r"pts_time:([0-9.]+)\s*\nlavfi\.signalstats\.YAVG=([0-9.]+)",
    open("/tmp/_v55.txt").read())]
assert d, "no luminance samples"


def _is_spike(i):
    if i < 1 or i + 3 >= len(d):
        return False
    jump = abs(d[i][1] - d[i - 1][1])
    if jump <= 8.0:
        return False
    return any(abs(d[i + k][1] - d[i - 1][1]) < jump * 0.5 for k in (1, 2, 3))


spikes = [d[i][0] for i in range(1, len(d)) if _is_spike(i)]
body = [t for t in spikes if t < freeze_at]
inside = [t for t in spikes if t >= freeze_at]
assert not body, "exposure changes in the body at %s" % ["%.2f" % t for t in body[:5]]
assert len(inside) >= 12, "only %d exposure frames inside the freeze" % len(inside)
assert max(inside) - freeze_at > window * 0.75, (
    "the last exposure hit is %.2fs into a %.2fs freeze: the ending dies early"
    % (max(inside) - freeze_at, window))

print("_v55 ok — %.2fs video == %.2fs audio, %d frames, freeze %.2f-%.2f with "
      "%d exposure hits (last at +%.2fs) and none in the body"
      % (v_dur, a_dur, v_frames, freeze_at, out_len, len(inside),
         max(inside) - freeze_at))
