"""The effects belong to the freeze, and nowhere else.

Operator, on a delivered render, after being asked to check frame by frame:

  "itu kenapa efeknya dari awal sampe akhir? harusnya cukup pas di freeze frame
   aja setelah kotak makan dari rumah, masih kelebihan terus"

Measured frame-by-frame on that file (936 frames, every frame's YAVG):

    brightness jumps in the body   51   from 0.47s to 26.07s
    brightness jumps in the freeze  0

The exact inverse of the request. This test pins the direction so it cannot
flip back: the body runs clean, the ending carries the jedag-jedug.
"""
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import edit  # noqa: E402

MP3 = "/home/ubuntu/background_music/hype_dj_nansuya_gang_jedag_jedug_ncs_copyrigh.mp3"
WORDS = "/home/ubuntu/clipper/media/uf0a29714d9fe/wyvzLKsUNF4.words.json"
START, DUR = 122.0, 28.55

if not (os.path.exists(MP3) and os.path.exists(WORDS)):
    print("_v53 skip — track or transcript missing")
    sys.exit(0)

_d = json.load(open(WORDS))
words = _d["words"] if isinstance(_d, dict) else _d
seg = [w for w in words if START <= w["start"] < START + DUR]

# The jamet ending is what creates the freeze. OUTRO defaults to "auto" and
# resolves by mood at render time; pinning it here cost a debugging round when a
# probe with the default returned 0 filters and an output length equal to the
# body, which read as "the freeze does not exist".
edit.OUTRO = "jamet"

out_len = edit._outro_output_len(DUR, mood="hype", words=seg, clip_start=START)
freeze_at = edit._outro_start(DUR, mood="hype", words=seg, clip_start=START)
assert freeze_at is not None, "no ending placed, nothing to test"
assert out_len > DUR, (
    "output %.2fs is not longer than the body %.2fs: the freeze is supposed to "
    "EXTEND the clip" % (out_len, DUR))

# --- 1. the effects are inside the freeze, all of them ----------------------
flicker = edit._burst_times(edit._window_beats(MP3, freeze_at, out_len))
slams = edit._window_beats(MP3, freeze_at, out_len,
                           fraction=edit.SLAM_BEAT_FRACTION)
assert flicker, "no flicker in the closing window"
assert slams, "no slams in the closing window"
for name, times in (("flicker", flicker), ("slam", slams)):
    early = [t for t in times if t < freeze_at]
    assert not early, (
        "%s fires at %s, before the freeze at %.2fs — this is the bug the "
        "operator caught frame by frame" % (
            name, ["%.2f" % t for t in early[:5]], freeze_at))
    late = [t for t in times if t >= out_len]
    assert not late, "%s fires past the end of the file" % name

# --- 2. the window is measured against the OUTPUT, not the body -------------
# Clamping against `dur` leaves a 0.35s window holding zero beats, so the
# effects vanish instead of moving. That failure looks identical to "the fix
# worked" if you only check that the body is clean.
assert out_len - freeze_at >= 1.0, (
    "closing window is %.2fs: too short to hold a burst, the effects would "
    "disappear rather than move" % (out_len - freeze_at))

# --- 3. the freeze is covered, not just touched ----------------------------
# A single burst at the start of the freeze left 2.4s of the ending still.
assert flicker[0] - freeze_at < 0.6, (
    "first flicker is %.2fs into the freeze: the ending starts dead"
    % (flicker[0] - freeze_at))
gaps = [b - a for a, b in zip(flicker, flicker[1:])]
assert max(gaps) < 1.6, (
    "longest gap inside the freeze is %.2fs: one burst and silence, not "
    "jedag-jedug" % max(gaps))
bursts = [[flicker[0]]]
for t in flicker[1:]:
    (bursts[-1].append(t) if t - bursts[-1][-1] <= 0.5 else bursts.append([t]))
assert len(bursts) >= 2, (
    "%d burst in a %.2fs ending: the window fraction is too small"
    % (len(bursts), out_len - freeze_at))

# --- 4. the window gets its own share of the onsets ------------------------
# FLASH_BEAT_FRACTION is tuned for a whole clip: 12% of the 6 onsets inside a 3s
# freeze is ONE. The window needs its own constant or the ending is empty.
assert edit.FLASH_WINDOW_FRACTION > edit.FLASH_BEAT_FRACTION, (
    "FLASH_WINDOW_FRACTION %.2f must exceed FLASH_BEAT_FRACTION %.2f: a 3s "
    "window holds far fewer onsets than a whole clip"
    % (edit.FLASH_WINDOW_FRACTION, edit.FLASH_BEAT_FRACTION))

# --- 5. the flicker is written BELOW the freeze loop -----------------------
# Probed in real ffmpeg: an eq=brightness above `loop` produced 0 flicker events
# inside the freeze, the same expression below it produced 10. The loop clones
# the frame it is given, flicker included.
src = open(edit.__file__).read()
chain = src[src.index("elif frame_mode == \"pillar\" and not split_screen"):]
chain = chain[:chain.index("base_label}]")]
i_loop = chain.find("for f in p_filters")
# Search for the flicker's own variable, not a substring of it: "p_bright"
# also matches "p_outro_bright", which is emitted ABOVE the loop on purpose,
# so the naive find() reported the wrong order on correct code.
i_flash = chain.find("'{p_bright}'")
assert i_loop != -1 and i_flash != -1, "pillar chain shape changed"
assert i_loop < i_flash, (
    "the flicker eq is emitted before the outro filters: the freeze loop will "
    "clone the flickering frame and the ending holds still again")

print("_v53 ok — %d flickers in %d bursts and %d slams, all inside the "
      "%.2fs freeze (body carries none), first hit %.2fs in, longest gap "
      "%.2fs" % (len(flicker), len(bursts), len(slams), out_len - freeze_at,
                 flicker[0] - freeze_at, max(gaps)))
