"""The portrait tail, and beats that ARRIVE instead of running on a grid.

Operator, handing over a reference short (UBycjaIlBZk): "ini contoh jedag
jedug, boleh si tambahin foto gibran yg di pake di video ini" — then, on
ordering: "Salah, potret baru dip to black" and "Outro di perpanjang, itu
ibarat outro juga".

So the jamet ending is now four movements in ONE outro, not a clip pasted on:

    footage freeze + beat shake  ->  held portrait  ->  dip to black

Two properties are asserted, both measured off a real ffmpeg render rather
than off the filter string. A filter graph that reads correctly and a file
that plays correctly are different claims; `hue=...:eval=frame` proved that
once by passing a string assertion and being rejected outright by ffmpeg.

1. ORDER AND DIP. The portrait must be on screen before the dip starts, and
   the dip must reach black on the LAST frame, over the portrait. The first
   attempt put the fade inside _outro_filters, which runs UPSTREAM of the
   portrait overlay: the photograph painted straight over it and the
   delivered file held luminance 63 to the final frame with no dip at all.

2. GROUPED, NOT EVEN. The reference does not hit every onset. Measured on
   it: 42 onsets 0.303s apart but only 9 hits, arriving in runs (one, then
   three at 9.90/10.05/10.20, then five at 13.60-14.30) with gaps up to
   3.40s between runs and 0.15s inside them. Hitting every onset is what the
   operator called "rusuh doang gajelas".

   The test is the SPACING SPREAD, not the count and not the rate: a grid
   gives spread 0 at any density, and an even onset-follower gives a small
   spread, while grouping gives a large one. A negative control pins that
   down — the same window with clustering disabled must come out flatter.
"""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edit  # noqa: E402

FFMPEG = edit.FFMPEG
FFPROBE = getattr(edit, "FFPROBE", "ffprobe")
TMP = "/tmp/_v66"
os.makedirs(TMP, exist_ok=True)


def _luma(path, at, dur, fps=10, w=96, h=170):
    """Mean luminance per sampled frame of a real file."""
    out = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", f"{at}", "-t", f"{dur}", "-i", path,
         "-vf", f"fps={fps},scale={w}:{h}", "-f", "rawvideo",
         "-pix_fmt", "gray", "-"],
        capture_output=True).stdout
    fr = np.frombuffer(out, dtype=np.uint8).astype(np.float32)
    fr = fr.reshape(-1, h, w)
    return [float(f.mean()) for f in fr]


# --- 1. the ending's four movements, measured in a rendered file -----------
# A synthetic source: moving footage, so a held frame is distinguishable from
# live video, plus a portrait that is a flat known grey — any frame showing it
# is unambiguous.
src = os.path.join(TMP, "src.mp4")
portrait = os.path.join(TMP, "portrait.png")
# The source needs an AUDIO track: the renderer builds an audio chain from
# [0:a] and ffmpeg rejects the whole graph without it (":a" stream specifier).
# testsrc2 is video only, so a silent tone is muxed in.
subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
                f"testsrc2=size=1080x1920:rate={edit.FPS}:duration=12",
                "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo:d=12",
                "-shortest", "-pix_fmt", "yuv420p", src], check=True)
# Flat grey 200: brighter than testsrc2's mean, so "portrait on screen" and
# "dip to black" are both visible as luminance, in opposite directions.
subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
                "color=c=0xC8C8C8:size=1080x1920:d=1",
                "-frames:v", "1", portrait], check=True)

# The clip has to be LONGER than the jamet span (5.0s) or the ending is not
# applied at all: _outro_start returns None, _outro_filters returns [], and a
# test built on a 6.0s source silently asserts nothing. Speech ends at 6.0s,
# leaving the span its room.
DUR = 12.0
words = [{"word": "satu", "start": 0.4, "end": 0.9},
         {"word": "dua", "start": 1.2, "end": 1.7},
         {"word": "tiga", "start": 2.1, "end": 6.0}]

# edit.OUTRO selects the branch and is read at CALL time, so it has to be set
# before the first _outro_* call, not just before the render. Left at "auto"
# the length queries below take the non-jamet path and report no tail at all.
edit.OUTRO = "jamet"
edit.FLASH = True

_len_plain = edit._outro_output_len(DUR, mood="hype", words=words,
                                    clip_start=0.0)
_len_tail = edit._outro_output_len(DUR, mood="hype", words=words,
                                   clip_start=0.0, portrait=portrait)
assert _len_tail > _len_plain, (
    "the portrait has to LENGTHEN the ending (outro di perpanjang), got "
    "%.3f vs %.3f" % (_len_tail, _len_plain))
assert abs((_len_tail - _len_plain) - edit.OUTRO_PORTRAIT) < 0.05, (
    "the ending grew by %.3fs, expected the portrait tail %.3fs"
    % (_len_tail - _len_plain, edit.OUTRO_PORTRAIT))

# The fade must NOT be in the upstream filter list when a portrait is present:
# that is the bug where the photograph painted over the dip.
_b, _filters = edit._outro_filters(DUR, mood="hype", words=words,
                                   clip_start=0.0, portrait=portrait)
assert not any(f.startswith("fade=") for f in _filters), (
    "with a portrait tail the dip must be applied DOWNSTREAM of the overlay, "
    "not in the outro filters that run before it — found %s"
    % [f for f in _filters if f.startswith("fade=")])
_b2, _f2 = edit._outro_filters(DUR, mood="hype", words=words, clip_start=0.0)
assert any(f.startswith("fade=") for f in _f2), (
    "without a portrait the dip belongs in the outro filters, and is missing")

print("_v66: the portrait lengthens the ending and moves the dip downstream")

# --- 2. rendered: portrait on screen, then black on the last frame ---------
out = os.path.join(TMP, "tail.mp4")
edit.OUTRO = "jamet"
edit.FLASH = True
edit.render_clip(src, 0.0, DUR, words, out, mood="hype",
                 frame_mode="pillar", portrait=portrait)
assert os.path.exists(out), "render produced no file"

_dur = float(subprocess.run(
    [FFPROBE, "-v", "error", "-show_entries", "format=duration",
     "-of", "default=nw=1:nk=1", out],
    capture_output=True, text=True).stdout.strip())
assert _dur > _len_plain + 0.5, (
    "the delivered file is %.2fs, which is not long enough to hold a %.1fs "
    "portrait tail" % (_dur, edit.OUTRO_PORTRAIT))

# The portrait window: bright grey 200 while it holds, then driven to black.
_tail = _luma(out, max(0.0, _dur - edit.OUTRO_PORTRAIT), edit.OUTRO_PORTRAIT)
assert _tail, "no frames sampled in the portrait tail"
_first, _last = _tail[0], _tail[-1]
assert _first > 120, (
    "the portrait should be on screen when the tail starts (flat grey 200), "
    "got luminance %.1f — the overlay is not firing" % _first)
assert _last < 25, (
    "the dip must reach black on the LAST frame, over the portrait: got "
    "%.1f. This is the exact failure where the photograph painted over a "
    "fade written upstream of it." % _last)
# Negative control: the dip must not have started yet at the top of the tail,
# or the "dip" is just the whole portrait being dark.
assert _first - _last > 80, (
    "luminance has to TRAVEL across the tail (portrait bright -> black), got "
    "%.1f -> %.1f" % (_first, _last))

print("_v66: portrait held at %.0f luminance, black at %.0f on the last frame"
      % (_first, _last))

# --- 3. the hits arrive in groups, and the control is flatter --------------
# _cluster_beats is given an EVEN onset grid, so any spread in the output is
# the grouping's doing and nothing else.
_even = [28.0 + i * 0.30 for i in range(18)]
_grouped = edit._cluster_beats(_even)
assert _grouped, "clustering dropped every onset"
assert set(_grouped) <= set(_even), (
    "every kept hit must still be a REAL onset — clustering may only drop, "
    "never invent")
assert len(_grouped) < len(_even), (
    "grouping has to drop the onsets between runs, kept all %d"
    % len(_even))

_gaps = np.diff(_grouped)
_spread = float(max(_gaps) - min(_gaps))
_ctl = float(np.diff(_even).max() - np.diff(_even).min())
assert _spread >= 0.10, (
    "grouped hits must NOT be evenly spaced — spread %.3fs. A fixed grid "
    "gives 0.00 at any rate, which is the 'rusuh doang gajelas' texture."
    % _spread)
assert _spread > _ctl + 0.10, (
    "the clustered output (spread %.3fs) has to be less even than the onset "
    "grid it came from (%.3fs), or the grouping is a no-op"
    % (_spread, _ctl))
# Runs: at least one gap must be tight and at least one wide, which is what
# "saves up, then lands a cluster" means numerically.
assert min(_gaps) <= 0.35 and max(_gaps) >= 0.70, (
    "the shape has to be runs separated by rests: tightest gap %.2fs, "
    "widest %.2fs" % (min(_gaps), max(_gaps)))

print("_v66: %d of %d onsets kept, spread %.2fs vs %.2fs even control"
      % (len(_grouped), len(_even), _spread, _ctl))

# --- 4. the portrait is HELD, not thrown -----------------------------------
# The shake window has to end where the portrait begins. A thrown photograph
# reads as footage and undoes the reason for showing it.
_pt = [f for f in _filters if "between(t," in f]
_start = edit._outro_start(DUR, mood="hype", words=words, clip_start=0.0)
assert _start is not None
_shake_end = _len_tail - edit.OUTRO_PORTRAIT
for f in _pt:
    for tok in f.split("between(t,")[1:]:
        hi = float(tok.split(")")[0].split(",")[1])
        assert hi <= _shake_end + 0.1, (
            "a beat window runs to %.3fs, past the start of the portrait at "
            "%.3fs — the held photograph would be shaken" % (hi, _shake_end))

print("_v66: no beat window reaches into the portrait (ends by %.2fs)"
      % _shake_end)
print("_v66 ok")
