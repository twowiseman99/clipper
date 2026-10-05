"""The jamet ending must survive a short clip, and really invoke ffmpeg.

The 22s viral cut shipped with no outro at all. The ledger said only

    ENGINEERING  edit       DID NOT RUN

because _outro_filters returns ("", []) when the clip is shorter than 3x the
outro span, and the span was the melancholy 8s — so the guard wanted 24s from a
22s clip. The freeze-and-shake is not a ramp: it lands in about three seconds,
and tying it to the fade's span silently removed the one thing the operator
asked for ("muka gibrannya di stop jadi image terus goyang").

Two spans now, so the guard scales per ending. The sombre cut still refuses to
squeeze its 8s ramp into a 22s clip, which is correct — that one really does
need the room.

This test invokes ffmpeg for real. A filter test that asserts on the filter
STRING passes while ffmpeg rejects the graph: `hue` has no `eval` option and
ffmpeg refuses the whole chain, which is how a render died after download and
transcription once already.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edit

FFMPEG = os.environ.get("CLIPPER_FFMPEG", "ffmpeg")


def probe_moves(path, t, span=0.25):
    """Peak frame-to-frame difference around t. 0 means frozen."""
    out = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", str(t), "-t", str(span), "-i", path,
         "-vf", "fps=30,scale=96:-2,tblend=all_mode=difference,signalstats,"
                "metadata=print:key=lavfi.signalstats.YAVG:file=-",
         "-f", "null", "-"],
        capture_output=True, text=True).stdout
    vals = [float(l.split("=")[-1]) for l in out.splitlines() if "YAVG" in l]
    return max(vals) if vals else None


# --- the guard scales per ending --------------------------------------------
orig = edit.OUTRO
try:
    edit.OUTRO = "jamet"
    # The clip that shipped bare.
    term, filt = edit._outro_filters(22.0, "hype")
    assert filt, "22s clip still gets no jamet outro"
    assert any("loop=loop=" in f for f in filt), filt
    # Down to 3x its own span.
    assert edit._outro_filters(9.5, "hype")[1], "9.5s should still fit a 3s outro"
    # And below that it correctly refuses: an outro covering a third of the
    # clip is not an ending.
    assert edit._outro_filters(8.0, "hype")[1] == [], "no guard left at all"

    edit.OUTRO = "melancholy"
    # The sombre ramp keeps the longer requirement. This is not a bug: the
    # desaturate/vignette/grain/dip needs the room, and squeezing it into 22s
    # would make the treatment the clip.
    assert edit._outro_filters(22.0, "emotional")[1] == [], \
        "melancholy must not fit a 22s clip"
    assert edit._outro_filters(30.0, "emotional")[1], "30s should fit"
finally:
    edit.OUTRO = orig

# --- ffmpeg must accept the graph, on a clip as short as the real one -------
# testsrc2, not testsrc: plain testsrc moves only ~1.25 and would fail a motion
# floor for reasons that have nothing to do with the outro.
with tempfile.TemporaryDirectory() as tmp:
    src = os.path.join(tmp, "src.mp4")
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc2=size=1080x1920:rate=30:duration=22", "-pix_fmt",
         "yuv420p", src], check=True)

    edit.OUTRO = "jamet"
    try:
        term, filt = edit._outro_filters(22.0, "hype")
    finally:
        edit.OUTRO = orig
    assert filt, "nothing to test"

    out = os.path.join(tmp, "out.mp4")
    chain = ",".join(filt)
    r = subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-i", src, "-vf", chain,
         "-pix_fmt", "yuv420p", out], capture_output=True, text=True)
    assert r.returncode == 0, f"ffmpeg rejected the graph:\n{r.stderr[:600]}"

    # Resolution is non-negotiable: the operator's standing rule is that the
    # look may never be achieved by changing the frame. The shake is a moving
    # crop scaled back to canvas for exactly this reason.
    dims = subprocess.run(
        [os.environ.get("CLIPPER_FFPROBE", "ffprobe"), "-v", "error",
         "-select_streams", "v", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip()
    assert dims.startswith("1080,1920"), dims

    # The freeze must actually freeze, and the shake must actually move.
    # These are measurements on the rendered file, not assertions about a
    # string — but note WHAT is frozen. The shake now runs ON the still
    # (operator: "videonya dah ga di play, jadi image gitu"), so a plain
    # frame-difference reads motion throughout the ending: the picture is
    # being translated on the beat. It is the underlying picture that stops,
    # which _v40 verifies by compensating for that translation.
    #
    # This test asserted frozen < 1.0 at the start of the ending, which only
    # held while the shake began AFTER the still — i.e. while the bug was
    # present. What belongs here is the shake's amplitude, and that the clip
    # grew by the freeze's duration because `loop` inserts real frames.
    span = edit.OUTRO_JAMET_SECONDS
    shaking = probe_moves(out, 22.0 - span + 0.6, 0.25)
    assert shaking is not None, shaking
    assert shaking > 3.0, f"the shake does not move: {shaking}"

    dur = float(subprocess.run(
        [os.environ.get("CLIPPER_FFPROBE", "ffprobe"), "-v", "error",
         "-select_streams", "v", "-show_entries", "format=duration",
         "-of", "csv=p=0", out],
        capture_output=True, text=True).stdout.strip())
    assert dur > 22.0 + edit.OUTRO_FREEZE - 0.4, (
        "the frozen frames were not inserted: %.2fs for a 22s clip plus a "
        "%.2fs hold" % (dur, edit.OUTRO_FREEZE))

print(f"_v36 ok — jamet fits a 22s clip (shake {shaking:.1f}, "
      f"clip grew to {dur:.1f}s), melancholy still needs 24s, 1080x1920 kept")
