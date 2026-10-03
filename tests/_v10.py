"""The ending had the wrong register, and the clip stopped mid-sentence.

v10 ended on "...memicu suatu kehendak," — a comma — and the first outro I
built was a bright flash stinger. The operator's correction: this clip is an
apology for people being killed, so the ending should be quiet and drained of
colour, not jedak-jeduk.

Offline. Data is the real v10 transcript.
"""
import json
import re

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import edit
import segments

WORDS = "media/uf9833efdc72b/PPOKdwOCMLA.words.json"
raw = json.load(open(WORDS))
raw = raw["words"] if isinstance(raw, dict) else raw

# --- The mid-sentence cut ---------------------------------------------------
end = segments._snap_end(raw, 245.34, 329.96)
assert end is not None
assert end > 329.96, f"did not run on to the sentence end: {end}"
assert abs(end - 336.54) < 0.5, end

closing = [w for w in raw if 329.0 < w["start"] <= end]
text = " ".join(str(w.get("word", "")) for w in closing)
assert "sungguh" in text, text
assert text.strip().endswith("."), text

# The grace window does not run on forever.
assert segments._snap_end(raw, 245.34, 300.0, grace=0.2) <= 300.2

# A clip already ending on a full stop is left alone.
fixture = [{"word": "satu", "start": 0.0, "end": 1.0},
           {"word": "dua.", "start": 1.0, "end": 2.0},
           {"word": "tiga", "start": 2.0, "end": 3.0},
           {"word": "empat.", "start": 3.0, "end": 4.0}]
assert segments._snap_end(fixture, 0.0, 2.0) == 2.0

# No sentence boundary nearby: keep the plain cut.
nostop = [{"word": "satu", "start": 0.0, "end": 1.0},
          {"word": "dua", "start": 1.0, "end": 2.0},
          {"word": "tiga", "start": 2.0, "end": 3.0}]
assert segments._snap_end(nostop, 0.0, 2.0) == 2.0

# --- The ending matches the mood --------------------------------------------
# This is the correction: the Gontor clip's mood is "emotional".
assert edit._outro_kind("emotional") == "melancholy"
assert edit._outro_kind("sad") == "melancholy"
assert edit._outro_kind("hype") == "stinger"
assert edit._outro_kind("funny") == "stinger"
assert edit._outro_kind(None) == "stinger"

bright, filters = edit._outro_filters(91.0, mood="emotional")
# The melancholy ending is defined by the colour shift, not by dimming: the
# operator turned the dim off after it read as a fade-to-nothing stacked on top
# of the desaturation. Assert on what must be true (colour moves, no pulses)
# rather than on one tunable being non-zero.
assert filters, "melancholy ending produced no desaturation"
assert "hue=s=" in filters[0], filters
if bright:
    # When a dim IS configured it must darken, not brighten: a positive term
    # here would be a flash.
    assert bright.lstrip().startswith("-"), bright
    assert "between(t," not in bright, bright

# The ramp runs across the final OUTRO_SECONDS and is clamped at both ends, so
# the filter cannot push saturation negative on an early frame. The ramp lives
# in whichever term is active: the dim when one is configured, otherwise the
# desaturation filter.
start = 91.0 - edit.OUTRO_SECONDS
ramped = bright if bright else filters[0]
assert f"{start:.3f}" in ramped, ramped
assert "min(1,max(0," in ramped, ramped

# The stinger still exists for clips that want it.
sb, sf = edit._outro_filters(91.0, mood="hype")
pulses = sb.count("between(t,")
assert pulses >= 8, sb
assert sf == [], sf
starts = [float(m) for m in re.findall(r"between\(t,([0-9.]+),", sb)]
ends = [float(m) for m in re.findall(r"between\(t,[0-9.]+,([0-9.]+)\)", sb)]
assert min(starts) >= start - 0.001, min(starts)
assert max(ends) <= 91.001, max(ends)
gaps = [b - a for a, b in zip(starts, starts[1:])]
assert gaps[0] > gaps[-1], gaps

# Too short a clip gets no ending treatment of either kind.
assert edit._outro_filters(5.0, mood="emotional") == ("", [])
assert edit._outro_filters(5.0, mood="hype") == ("", [])
assert edit._outro_filters(91.0, mood="emotional", seconds=0) == ("", [])

# Beat flashes and the ending combine in one brightness expression without the
# ending eating the flash budget.
flash = edit._flash_expr([20.0, 40.0, 60.0], 91.0)
combined = "+".join(x for x in (flash, sb) if x)
assert combined.count("between(t,") == flash.count("between(t,") + pulses

# render_clip must accept the mood, or none of this reaches ffmpeg.
import inspect
assert "mood" in inspect.signature(edit.render_clip).parameters

# --- ffmpeg has to accept the filters, not just this file ---------------------
# Everything above is string assertions, and string assertions passed while the
# real render died: `hue` has no `eval` option in ffmpeg 6.1, so the graph was
# rejected after the download and transcribe were already paid for. Build the
# actual expressions and run them over two synthetic seconds.
import subprocess
import tempfile

for mood in ("emotional", "hype"):
    b, extra = edit._outro_filters(91.0, mood=mood)
    # Scaled to a 2s probe clip so the window lands inside it.
    b2, extra2 = edit._outro_filters(6.0, mood=mood, seconds=2.0)
    chain = "format=yuv420p"
    if b2:
        chain += f",eq=brightness='{b2}':eval=frame"
    for f in extra2:
        chain += f",{f}"
    with tempfile.NamedTemporaryFile(suffix=".mp4") as out:
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-y",
             "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=6",
             "-vf", chain, "-frames:v", "20", out.name],
            capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, (
        f"ffmpeg rejected the {mood} outro chain:\n{chain}\n{proc.stderr[:400]}")
    assert "Option not found" not in proc.stderr, proc.stderr[:400]

print("_v10.py OK — ends at %.2fs on a full stop (was 329.96 mid-clause); "
      "emotional -> melancholy (dim %.2f, desat %.2f), hype -> %d pulses; "
      "ffmpeg accepts both chains"
      % (end, edit.OUTRO_DIM, edit.OUTRO_DESAT, pulses))
