"""Adding music made the clip quieter.

v14 shipped with BGM for the first time and measured 5.7 dB QUIETER overall
than v13, which had no music at all:

    v13 (no music)  RMS -23.13 dB
    v14 (with BGM)  RMS -28.79 dB

Cause: amix defaults to normalize=1, which divides every input by the number of
inputs. Mixing speech with music therefore halved the speech instead of laying
music under it. The phase-subtraction probe came back near-silent for the same
reason: v14 is not v13 plus music, it is v13 scaled down plus music scaled down.

Measured with ffmpeg rather than asserted on the filter string, because a
string-only assertion already passed once while ffmpeg rejected the graph
(`hue=...:eval=frame`).
"""
import math
import os
import struct
import subprocess
import sys
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import edit

TMP = "/tmp/_v14"
os.makedirs(TMP, exist_ok=True)


def rms_db(path):
    w = wave.open(path)
    n = w.getnframes()
    d = struct.unpack("<%dh" % n, w.readframes(n))
    w.close()
    if not d:
        return -999.0
    return 20 * math.log10(max(1e-9, (sum(v * v for v in d) / len(d)) ** 0.5) / 32768)


def mix(normalize, out):
    """Mix a 1kHz 'speech' tone with a 200Hz 'music' tone the way edit.py does."""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=1000:duration=4",
         "-f", "lavfi", "-i", "sine=frequency=200:duration=4",
         "-filter_complex",
         f"[1:a]volume=0.2[bgm];[0:a][bgm]amix=inputs=2:duration=first:"
         f"normalize={normalize}:dropout_transition=0[a]",
         "-map", "[a]", "-ac", "1", "-ar", "16000", out],
        check=True, capture_output=True)
    return rms_db(out)


# The speech track alone is the reference: music must not push it down.
speech_only = os.path.join(TMP, "speech.wav")
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
     "sine=frequency=1000:duration=4", "-ac", "1", "-ar", "16000", speech_only],
    check=True, capture_output=True)
ref = rms_db(speech_only)

bad = mix(1, os.path.join(TMP, "norm1.wav"))
good = mix(0, os.path.join(TMP, "norm0.wav"))

# normalize=1 is the bug: the mix ends up quieter than the speech alone.
assert bad < ref - 3, (
    f"expected normalize=1 to lose level: speech {ref:.2f} vs mix {bad:.2f}")
# normalize=0 keeps the speech where it was, and music only adds.
assert good >= ref - 0.5, (
    f"normalize=0 should preserve speech level: speech {ref:.2f} vs mix {good:.2f}")
assert good > bad + 3, f"normalize=0 must be louder: {good:.2f} vs {bad:.2f}"

# And the real render chain has to carry the flag, or none of this applies.
# Checked against the assembled filter string rather than the source lines: the
# f-string is split across lines, so a line-by-line grep reports a false
# failure on the half that holds `amix=inputs=`.
src = open(os.path.join(os.path.dirname(os.path.dirname(
                             os.path.abspath(__file__))), "edit.py"),
           encoding="utf-8").read()
flat = src.replace("\\\n", "").replace('"\n', '"').replace("\n", " ")
assert "amix=inputs=" in flat, "no amix in the render chain at all"
# Every amix in the file must be followed by normalize=0 before the next filter
# boundary, so a second mix added later cannot quietly reintroduce the bug.
for chunk in flat.split("amix=inputs=")[1:]:
    head = chunk.split(",")[0]
    assert "normalize=0" in head, f"amix without normalize=0: ...{head[:90]}"

for f in os.listdir(TMP):
    os.remove(os.path.join(TMP, f))
os.rmdir(TMP)

print(f"_v14.py OK — speech alone {ref:.2f} dB; amix normalize=1 drops it to "
      f"{bad:.2f} dB (the v14 bug), normalize=0 holds {good:.2f} dB; "
      f"render chain carries the flag")
