"""A longer, layered sad outro — verified by running ffmpeg, not by reading it.

The operator asked for two things: "outro sedihnya panjangin" and "kasih
efek-efek agak norak gamasalah tapi jgn terlalu rusuh". Longer and showier, but
not busy — and on a clip about people being killed, "not busy" has a hard floor:
no pulses, no flashes, no strobe. Those belong to the stinger ending, which this
mood must never get.

So the layers added are monotonic: a vignette angle that only opens, grain that
only sits there. Both ramp with the same expression as the desaturation, so the
ending is one gesture in four parts rather than four effects.

Why this file runs ffmpeg for real: a previous outro test asserted on the filter
STRING and passed, while ffmpeg rejected the graph outright — `hue` has no
`eval` option and the whole render died after the download and transcribe were
already paid for. A filter test that does not invoke ffmpeg proves nothing.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import edit


FFMPEG = getattr(edit, "FFMPEG", "ffmpeg")


def graph_runs(filters, dur=30.0):
    """True when ffmpeg accepts this chain on synthetic video.

    testsrc2 rather than testsrc: plain testsrc measures only 1.25 mean motion
    and fails the b-roll motion floor elsewhere in these tests, so testsrc2 is
    the house default for synthetic footage.
    """
    chain = ",".join(f for f in filters if f)
    res = subprocess.run(
        [FFMPEG, "-v", "error", "-f", "lavfi", "-i",
         f"testsrc2=s=480x854:d={dur:.0f}:r=30",
         "-vf", chain, "-frames:v", "90", "-f", "null", "-"],
        capture_output=True, text=True, timeout=300)
    return res.returncode == 0, res.stderr.strip()[:300]


# --- the window is longer than it was --------------------------------------

assert edit.OUTRO_SECONDS >= 8.0, \
    f"the operator asked for a longer ending: {edit.OUTRO_SECONDS}"

# The 3x guard has to scale with it, or an 18s clip gets an ending covering
# half its length. 82s clips are the current product; 24s is the new floor.
assert edit._outro_filters(20.0, mood="emotional") == ("", []), \
    "a 20s clip is too short for an 8s ending"
_bright, filters = edit._outro_filters(82.0, mood="emotional")
assert filters, "an 82s emotional clip must get the melancholy ending"


# --- ffmpeg actually accepts the whole chain --------------------------------

ok, err = graph_runs(filters)
assert ok, f"ffmpeg rejected the real outro chain: {err}"

# Each layer on its own, so a future failure names the guilty filter instead of
# just "the outro is broken".
for one in filters:
    ok, err = graph_runs([one])
    assert ok, f"ffmpeg rejected {one.split('=')[0]!r}: {err}"


# --- the layers are present, and ramped -------------------------------------

chain = " ".join(filters)
assert "hue=s=" in chain, chain
assert "vignette=" in chain, chain
assert "noise=" in chain, chain
assert "setpts=" in chain, chain

# vignette must re-evaluate per frame or the ramp is a constant. This is the
# asymmetry that bit us: hue rejects eval, vignette requires it.
vig = [f for f in filters if f.startswith("vignette")][0]
assert "eval=frame" in vig, vig
# noise takes no expression at all, so it is gated by enable= instead.
noi = [f for f in filters if f.startswith("noise")][0]
assert "enable=" in noi and "alls=" in noi, noi
assert "eval=" not in noi, f"noise has no eval option: {noi}"


# --- a grief ending must not pulse -----------------------------------------

# The brightness term carries the stinger's flashes. For a sad mood it must be
# empty: no between() windows, no pow() falloff, nothing that blinks.
assert _bright == "", f"the sad ending must not flash: {_bright!r}"
assert "between(" not in chain, chain

# And the hype path still gets its stinger, so this change did not quietly
# disable the other ending.
hype_bright, hype_filters = edit._outro_filters(82.0, mood="hype")
assert "between(" in hype_bright, hype_bright
assert hype_filters == [], hype_filters


# --- the ramp starts where the window starts --------------------------------

# 82 - 8 = 74. Every layer that ramps must reference the same start, or the
# ending arrives in pieces.
assert "74.000" in chain, chain


# --- the dip to black sits at the very end, not across the window -----------

fade = [f for f in filters if f.startswith("fade=")]
assert fade, f"the operator asked for a dip to black: {chain}"
fade = fade[0]
assert "c=black" in fade and "t=out" in fade, fade

# The fade must be the LAST filter. It operates on the timeline it receives, so
# running before setpts would have slow-motion stretch the fade itself.
assert filters[-1].startswith("fade="), [f.split("=")[0] for f in filters]

# st= has to come off the STRETCHED end (82 - 8 + 8/0.7 = 85.43), not off dur.
# Reading it off 82 would start the fade at 80.8 and finish it 4.6s before the
# final frame — a dip to black in the middle of the ending, then back up.
#
# It must land just SHORT of the end, not exactly on it: the reviewer measured
# the final frame at Y=21 (dark grey) when the fade finished on the last frame,
# because fade only reaches zero at st+d. _v32 owns that margin; here we just
# check the fade is anchored to the stretched timeline rather than to `dur`.
st = float(fade.split("st=")[1].split(":")[0])
d = float(fade.split("d=")[1].split(":")[0])
stretched_end = 82.0 - edit.OUTRO_SECONDS + edit.OUTRO_SECONDS / edit.OUTRO_SLOWMO
assert st + d <= stretched_end + 0.01, \
    f"fade ends at {st + d:.3f}, past the clip end {stretched_end:.3f}"
assert st + d > stretched_end - 1.0, \
    f"fade ends at {st + d:.3f}, nowhere near the clip end {stretched_end:.3f}"
assert st > 82.0 - edit.OUTRO_SECONDS + 1.0, \
    f"fade starts at {st:.3f}, too early to be a closing dip"

# Short: a dim spread over the whole window is the "aneh" ending that was
# removed. The dip is a final beat, so it must occupy a small part of the span.
assert d <= edit.OUTRO_SECONDS / 4, \
    f"a {d}s dip over an {edit.OUTRO_SECONDS}s window is a drain, not a dip"
assert st > 82.0 - edit.OUTRO_SECONDS, "the dip must not start with the window"

print("v31 ok — 8s layered sad outro + end dip to black, ffmpeg-verified")
