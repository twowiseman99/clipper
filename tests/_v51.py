"""Captions must cover the speech, and the clip must end on its own sentence.

Two operator reports from the same render:

  "kenapa masi ada subtitlenya dikit-dikit ya?"
  "nanti selesai dari si gibran suruh bawa kotak makan, langsung jedag jedug"

Both had the same shape: a boundary computed from a count rather than from the
speech. Measured on the delivered file:

  captions covered 64.2% of the clip, 12 gaps totalling 10.12s. The two biggest
  (2.84s, 1.80s) had 13 words BEING SPOKEN inside them — the last word of each
  phrase ended on its own `end`, so every pause between phrases blanked the
  lane.

  the clip ran to 31.81s because the only silence >= 1.2s after the payoff was
  3.3s past it, so "tapi dua perempuan rekomisasi apa itu?" came along for the
  ride, and the mechanical "ending starts at dur - span" then put the freeze at
  23.81s — on top of "anaknya membawa kotak dari rumah ... yang dimasak",
  suppressing its captions.

This test pins both properties against the real transcript.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edit  # noqa: E402
import segments as selector  # noqa: E402

WORDS = ("/home/ubuntu/clipper/media/uf0a29714d9fe/"
         "wyvzLKsUNF4.words.json")
if not os.path.exists(WORDS):
    print("_v51 skipped — Gibran transcript not on this box")
    sys.exit(0)

_d = json.load(open(WORDS))
words = _d if isinstance(_d, list) else _d.get("words", [])
CTX = ("Gibran minta maaf ke ibu korban keracunan MBG lalu menitip anak-anak "
       "membawa kotak bekal dari rumah yang dimasak ibunya")
keys = [t for t in re.findall(r"\w+", CTX.lower()) if len(t) > 3]
START = 122.0

# --- 1. the clip ends on its own sentence ----------------------------------
snapped, why = selector.snap_to_speech_end(
    words, START, START + 45, min_dur=9.0, after_words=keys)
assert snapped is not None, "snap_to_speech_end gave up: %s" % why
seg_dur = snapped - START

tail = [w for w in words if START <= w["start"] < snapped]
text = " ".join(w["word"] for w in tail).lower()
assert "dimasak" in text, "the payoff line is not in the clip at all"
# The aside is the thing being cut. It must not survive.
assert "rekomisasi" not in text, (
    "clip is %.2fs and still carries 'rekomisasi apa itu?' — the aside after "
    "the payoff was not cut (%s)" % (seg_dur, why))

# --- 2. the ending starts AFTER the speech ---------------------------------
seg = [w for w in words if START <= w["start"] < snapped]
speech_end = max(w["end"] - START for w in seg)
edit.OUTRO = "jamet"
outro_at = edit._outro_start(seg_dur, mood="hype", words=seg,
                             clip_start=START)
assert outro_at is not None, "no ending placed on a %.2fs clip" % seg_dur
assert outro_at >= speech_end - 0.05, (
    "the ending starts at %.2fs but speech runs to %.2fs: the freeze would "
    "land on the payoff line" % (outro_at, speech_end))

# And the freeze must still be long enough to read. Snapping leaves only 0.35s
# of clip behind the sentence, so the freeze has to EXTEND the output rather
# than fit inside what is left — trimming to `dur` chopped it to 0.35s.
_b, _f = edit._outro_filters(seg_dur, mood="hype", words=seg,
                             clip_start=START)
_loop = [x for x in _f if x.startswith("loop")]
_trim = [x for x in _f if x.startswith("trim")]
assert _loop and _trim, "jamet ending produced no loop/trim: %s" % _f
_frames = int(_loop[0].split("loop=")[2].split(":")[0])
_freeze = _frames / edit.FPS
assert _freeze >= edit.OUTRO_JAMET_SECONDS - 0.05, (
    "freeze is only %.2fs against OUTRO_JAMET_SECONDS=%.1f: the ending is too "
    "short to read" % (_freeze, edit.OUTRO_JAMET_SECONDS))
_final = float(_trim[0].split("=")[-1])
assert _final > seg_dur + 0.5, (
    "output trimmed to %.2fs on a %.2fs body: the freeze was cut back instead "
    "of extending the clip" % (_final, seg_dur))

# ffmpeg has to accept it. A filter test that asserts on the string passes
# while ffmpeg refuses the graph — `hue` has no `eval` option and that killed a
# render after the download and transcribe had already run.
_out = "/tmp/_v51_outro.mp4"
_p = subprocess.run(
    [edit.FFMPEG, "-v", "error", "-y", "-f", "lavfi",
     "-i", "testsrc2=size=540x960:rate=30:duration=%g" % seg_dur,
     "-vf", "fps=30," + ",".join(_f),
     "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", _out],
    capture_output=True, text=True, timeout=400)
assert _p.returncode == 0, "ffmpeg rejected the ending:\n%s" % _p.stderr[-600:]
_got = float(subprocess.run(
    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
     "-of", "csv=p=0", _out],
    capture_output=True, text=True, timeout=120).stdout.strip())
assert abs(_got - _final) < 0.2, (
    "graph says %.2fs but ffmpeg produced %.2fs" % (_final, _got))

# A clip whose speech runs to the final frame has no "after" to freeze on.
_tight = [{"start": START, "end": START + 10.0, "word": "x"}]
assert edit._outro_snap(10.0, _tight, START, 3.0) is None, (
    "snapped an ending onto a clip whose speech runs to the last frame")

# --- 3. captions cover the speech ------------------------------------------
tmp = tempfile.mkdtemp()
ov = edit._editorial_layer(seg, START, tmp)
assert ov, "no caption overlays produced"

wins = sorted((o.t_start, o.t_end) for o in ov)
merged = []
for a, b in wins:
    if merged and a <= merged[-1][1] + 0.01:
        merged[-1][1] = max(merged[-1][1], b)
    else:
        merged.append([a, b])
span = max(b for _, b in merged)
coverage = 100 * sum(b - a for a, b in merged) / span

assert coverage > 85, (
    "captions cover only %.1f%% of the spoken span (was 64.2%% when the "
    "operator said 'subtitlenya dikit-dikit')" % coverage)

# Every gap left over must be real silence. This is the assertion that would
# have caught the original bug: the old gaps had words inside them.
gaps = [(merged[i][1], merged[i + 1][0])
        for i in range(len(merged) - 1)
        if merged[i + 1][0] - merged[i][1] > 0.3]
for a, b in gaps:
    spoken = [w for w in seg
              if w["end"] - START > a + 0.05 and w["start"] - START < b - 0.05]
    assert not spoken, (
        "caption gap %.2f-%.2fs has %d word(s) being spoken in it: %s"
        % (a, b, len(spoken), " ".join(w["word"] for w in spoken)[:60]))

# --- negative control ------------------------------------------------------
# With the hold disabled the coverage must drop, or the hold is not what is
# producing the improvement.
_was = edit.CAPTION_HOLD_MAX
edit.CAPTION_HOLD_MAX = 0.0
try:
    ov0 = edit._editorial_layer(seg, START, tempfile.mkdtemp())
    w0 = sorted((o.t_start, o.t_end) for o in ov0)
    m0 = []
    for a, b in w0:
        if m0 and a <= m0[-1][1] + 0.01:
            m0[-1][1] = max(m0[-1][1], b)
        else:
            m0.append([a, b])
    cov0 = 100 * sum(b - a for a, b in m0) / max(b for _, b in m0)
finally:
    edit.CAPTION_HOLD_MAX = _was

assert cov0 < coverage - 5, (
    "CAPTION_HOLD_MAX=0 still covers %.1f%% against %.1f%%: the hold is not "
    "what closes the gaps" % (cov0, coverage))

print("_v51 ok — clip ends at %.2fs on '...dimasak ikut' (was 31.81s with the "
      "aside), ending starts %.2fs after speech ends %.2fs, captions cover "
      "%.1f%% (was 64.2, control %.1f), %d leftover gap(s) all silent"
      % (seg_dur, outro_at if outro_at else -1, speech_end, coverage, cov0,
         len(gaps)))
