"""The ending must have sound, and the effects must burst instead of drip.

Two operator reports on one delivered render:

  "frame freeze ga ada suara videonya lagi jedag jedug"
  "kenapa editannya sepanjang ada lagu? sampah"

The first was three walls in a row, each hiding the next:

  1. `total = dur + intro_dur` did not know the freeze EXTENDS the clip, so the
     audio fade was computed for 28.55s of a 31.20s file.
  2. amix ran with `duration=first`, ending the mix when the speech track ended.
  3. the BGM input itself was cut with `-t dur + intro_dur`. Fixing only the
     graph left the file silent from 29.0s anyway, because those seconds were
     never decoded — measured at -99 dB with the stream still reporting 31.21s.

The second was the SHAPE of the effect timeline. Taking the N loudest onsets
spreads them by construction; the reference bursts and then goes quiet.

Measured on the reference tutorial (21 flickers over 19.9s):

    median spacing   0.10s
    intervals <0.8s  16/20  (80%)
    longest quiet    4.45s

The complained-about render: median 1.83s, 4/12 tight (33%), flickers from 0.4s
to 26.5s — 84% of the clip.
"""
import array
import json
import math
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import edit  # noqa: E402

NAME = "_v52"
MP3 = "/home/ubuntu/background_music/hype_dj_nansuya_gang_jedag_jedug_ncs_copyrigh.mp3"
WORDS = "/home/ubuntu/clipper/media/uf0a29714d9fe/wyvzLKsUNF4.words.json"
START = 122.0
DUR = 28.55

if not os.path.exists(MP3) or not os.path.exists(WORDS):
    print("%s skipped — needs the jedag-jedug mp3 and the Gibran transcript" % NAME)
    raise SystemExit(0)

_d = json.load(open(WORDS))
words = _d if isinstance(_d, list) else _d.get("words", [])
seg = [w for w in words if START <= w["start"] < START + DUR]
edit.OUTRO = "jamet"

# --- 1. the audio has to cover the whole output ----------------------------
out_len = edit._outro_output_len(DUR, mood="hype", words=seg, clip_start=START)
assert out_len > DUR + 0.5, (
    "the freeze does not extend the clip (%.2f vs %.2f): the rest of this test "
    "proves nothing" % (out_len, DUR))

# The BGM input must be decoded for the OUTPUT length, not the segment length.
# This is the wall that survived the graph fix: `-t` is a hard cut on the input
# and no downstream apad can recover it.
_edit_src = open(edit.__file__).read()
assert "_outro_output_len(dur, mood=mood, words=words" in _edit_src, (
    "nothing asks for the real output length")
_bgm_block = _edit_src.split('"-stream_loop", "-1", "-t", f"{max(dur + intro_dur')
assert len(_bgm_block) == 2, (
    "the BGM input is still cut to the segment length, so the ending will be "
    "silent no matter what the filter graph says")

# --- 2. real ffmpeg: a clip whose freeze extends it keeps its sound ---------
# Built from scratch rather than reusing a render output: media/ files get
# overwritten by the next job and a fixture pinned to one is a time bomb.
tmp = "/tmp/_v52"
os.makedirs(tmp, exist_ok=True)
body = os.path.join(tmp, "body.mp4")
subprocess.run(
    [edit.FFMPEG, "-v", "error", "-y",
     "-f", "lavfi", "-i", "testsrc2=size=540x960:rate=30:duration=%g" % DUR,
     "-f", "lavfi", "-i", "sine=frequency=300:duration=%g" % DUR,
     "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
     "-c:a", "aac", body],
    check=True, capture_output=True, timeout=400)

_b, filters = edit._outro_filters(DUR, mood="hype", words=seg, clip_start=START)
got = os.path.join(tmp, "out.mp4")
# The music input gets the OUTPUT length; the speech input keeps the segment.
p = subprocess.run(
    [edit.FFMPEG, "-v", "error", "-y",
     "-i", body,
     "-stream_loop", "-1", "-t", "%.3f" % out_len, "-i", MP3,
     "-filter_complex",
     "[0:v]fps=30,%s[v];"
     "[1:a]volume=0.2[bgm];"
     "[0:a]apad=whole_dur=%.3f[spad];"
     "[spad][bgm]amix=inputs=2:duration=longest:normalize=0,"
     "atrim=end=%.3f,afade=t=out:st=%.2f:d=1[a]"
     % (",".join(filters), out_len, out_len, out_len - 1),
     "-map", "[v]", "-map", "[a]",
     "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
     "-c:a", "aac", "-t", "%.3f" % out_len, got],
    capture_output=True, text=True, timeout=400)
assert p.returncode == 0, "ffmpeg rejected the ending:\n%s" % p.stderr[-700:]

# Decode the audio and look for digital silence in the freeze. astats stops
# reporting before the end of this file, so read the samples directly — the
# stream duration was 31.21s while the content died at 29.0s.
raw = subprocess.run(
    [edit.FFMPEG, "-v", "error", "-i", got, "-ac", "1", "-ar", "8000",
     "-f", "s16le", "-"],
    capture_output=True, timeout=400).stdout
pcm = array.array("h")
pcm.frombytes(raw)
SR = 8000
assert len(pcm) / SR > DUR + 0.5, (
    "audio is only %.2fs on a %.2fs output" % (len(pcm) / SR, out_len))

freeze_at = edit._outro_start(DUR, mood="hype", words=seg, clip_start=START)
assert freeze_at is not None, "no ending was placed, nothing to measure"
silent = total = 0
for i in range(int(freeze_at * SR), len(pcm), SR // 2):
    chunk = pcm[i:i + SR // 2]
    if len(chunk) < SR // 4:
        break
    rms = math.sqrt(sum(x * x for x in chunk) / len(chunk))
    db = 20 * math.log10(rms / 32768) if rms > 0 else -99.0
    total += 1
    silent += db < -70
assert total >= 3, "not enough freeze to measure (%d chunks)" % total
assert silent == 0, (
    "%d of %d half-second chunks in the freeze are digitally silent: the "
    "jedag-jedug has no music under it" % (silent, total))

# --- 3. the flickers burst; they do not drip -------------------------------
# Measure the stage the renderer actually screens: _music_beats picks the hits,
# _burst_times turns each into the tight run you see.
beats = edit._burst_times(edit._music_beats(MP3, DUR, 0.0))
assert len(beats) >= 8, "only %d flicker beats" % len(beats)
gaps = [beats[i + 1] - beats[i] for i in range(len(beats) - 1)]
tight = len([g for g in gaps if g < 0.8]) / len(gaps)
# The reference sits at 0.80. The drip that drew the complaint sat at 0.33.
assert tight >= 0.55, (
    "only %.0f%% of flicker intervals are tight (reference 80%%, the rejected "
    "render 33%%): this is a drip, not a burst" % (100 * tight))
assert max(gaps) >= 2.5, (
    "longest quiet stretch is %.2fs: without real gaps the effects read as "
    "running under the whole song" % max(gaps))

# And the onset gate must not pre-thin the track. At 0.35s the song's 63 onsets
# became 43 with a median spacing of 0.53s, which makes a burst impossible to
# express before any selection runs.
assert "> 0.18" in _edit_src, "the onset gate is back to thinning the track"

# Guard the knob that creates the bursts.
assert edit.FLASH_BURST >= 3, (
    "FLASH_BURST=%d is too small to read as a burst" % edit.FLASH_BURST)
# A burst is tighter than the song's own onsets: no arrangement of real beats
# gets below 0.25s, and the reference sits at 0.10s.
assert edit.FLASH_SUBBEAT <= 0.15, (
    "FLASH_SUBBEAT=%.2f is wider than the reference's 0.10s spacing"
    % edit.FLASH_SUBBEAT)
# No quarter of the clip may be empty: an earlier selection left the second
# quarter with nothing for 15.7s while the song had 8 onsets in it.
quarters = [len([t for t in beats if DUR * i / 4 <= t < DUR * (i + 1) / 4])
            for i in range(4)]
assert all(q > 0 for q in quarters), (
    "quarters %s: a whole region has no effects" % quarters)
# Flicker windows must not touch, or a burst fuses into one long bright block.
hold = edit.FLASH_HOLD
wins = [(max(0.0, t - hold / 2), max(0.0, t - hold / 2) + hold) for t in beats]
overlap = sum(1 for i in range(len(wins) - 1) if wins[i][1] > wins[i + 1][0])
assert overlap == 0, (
    "%d flicker windows overlap at FLASH_HOLD=%.2f: the burst fuses into one "
    "continuous block" % (overlap, hold)
)
lit = sum(e - s for s, e in wins) / DUR
assert lit < 0.30, "the effect is lit %.0f%% of the clip" % (100 * lit)

print("%s ok — %.2fs output from a %.2fs body, 0/%d freeze chunks silent, "
      "flickers %.0f%% tight (ref 80, rejected 33), longest quiet %.2fs, "
      "%d windows overlap, lit %.0f%%"
      % (NAME, out_len, DUR, total, 100 * tight, max(gaps), overlap, 100 * lit))
