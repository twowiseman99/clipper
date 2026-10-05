"""The jamet ending: freeze, then shake on the beat — and the dip reaching black.

Two operator notes drive this file.

First, from the reviewer: the melancholy ending's last frame measured Y=21, dark
grey rather than black, because a fade only reaches zero at st+d and the clip
ended exactly there. OUTRO_FADE_LEAD now lands the fade early so there is held
black to close on.

Second, a new ending: "outro 2 editan jamet, kayak video viral tiktok, ikutin
beat gambar goyang-goyang setelah di pause bagian gibran". A freeze, then a
beat-synced shake.

The shake is a moving crop scaled back to canvas, never a zoom on the picture
itself, because the output must stay 1080x1920 — "jgn diakalin dgn ratio
videonya diubah ya pantang". This file measures the delivered resolution rather
than trusting the filter string, and measures that the shake MOVES, because a
syntactically valid filter that produces a static frame is the exact failure
this project has shipped before.
"""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import edit


FFMPEG = getattr(edit, "FFMPEG", "ffmpeg")
TMP = "/tmp/_v32"


def render(filters, dur, out, size="540x960"):
    """Render synthetic footage through `filters`; returns (ok, stderr).

    testsrc2, not testsrc: plain testsrc measures 1.25 mean motion and sits
    below the motion floor used elsewhere in these tests.
    """
    os.makedirs(TMP, exist_ok=True)
    res = subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
         f"testsrc2=s={size}:d={dur:.0f}:r={edit.FPS}",
         "-vf", ",".join(f for f in filters if f),
         "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
         out],
        capture_output=True, text=True, timeout=600)
    return res.returncode == 0, res.stderr.strip()[:400]


def probe(path, keys="width,height"):
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v",
         "-show_entries", f"stream={keys}", "-of", "csv=p=0", path],
        capture_output=True, text=True, timeout=120)
    return res.stdout.strip()


def motion(path, at, window=0.4):
    """Mean frame-to-frame difference around `at` — how much the image moves."""
    res = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", f"{at:.2f}", "-t", f"{window:.2f}",
         "-i", path, "-vf",
         "fps=15,scale=96:-2,tblend=all_mode=difference,signalstats,"
         "metadata=print:key=lavfi.signalstats.YAVG:file=-",
         "-f", "null", "-"],
        capture_output=True, text=True, timeout=300)
    vals = [float(l.split("=")[-1]) for l in res.stdout.splitlines()
            if "YAVG" in l]
    return max(vals) if vals else 0.0


# --- the dip now reaches black ---------------------------------------------

assert edit.OUTRO_FADE_LEAD > 0, "the fade must finish before the last frame"

_b, sad = edit._outro_filters(82.0, mood="emotional")
fade = [f for f in sad if f.startswith("fade=")][0]
st = float(fade.split("st=")[1].split(":")[0])
d = float(fade.split("d=")[1].split(":")[0])
stretched_end = 82.0 - edit.OUTRO_SECONDS + edit.OUTRO_SECONDS / edit.OUTRO_SLOWMO
# Black is reached with time to spare, instead of landing on the final frame.
assert st + d < stretched_end - 0.05, \
    f"fade ends at {st + d:.3f} but the clip ends at {stretched_end:.3f}"
assert stretched_end - (st + d) >= 0.2, "too little held black to read as an end"


# --- jamet is opt-in, never automatic --------------------------------------

# A grief clip must not get a shaking ending by accident.
for mood in ("emotional", "sad", "reflective"):
    assert edit._outro_kind(mood) == "melancholy", mood
for mood in ("hype", "funny", None):
    assert edit._outro_kind(mood) != "jamet", mood


# --- the jamet chain renders, and keeps 1080x1920 --------------------------

saved = edit.OUTRO
try:
    edit.OUTRO = "jamet"
    assert edit._outro_kind("funny") == "jamet"
    _b2, jam = edit._outro_filters(14.0, mood="funny", seconds=4.0)
    assert jam, "jamet must produce filters"
    assert _b2 == "", f"jamet carries no brightness term: {_b2!r}"

    out = os.path.join(TMP, "jamet.mp4")
    ok, err = render(jam, 14.0, out, size=f"{edit.CANVAS_W}x{edit.CANVAS_H}")
    assert ok, f"ffmpeg rejected the jamet chain: {err}"

    # Resolution is not negotiable, whatever the look costs.
    assert probe(out) == f"{edit.CANVAS_W},{edit.CANVAS_H}", probe(out)

    # No duplicate-DTS warnings: setpts-based freezing produced
    # "non monotonically increasing dts" and dropped frames.
    assert "monotonic" not in err.lower(), err

    # And the shake must actually move the image. The freeze starts at
    # 14 - 4 = 10s and holds OUTRO_FREEZE, so shaking runs from ~10.5s.
    quiet = motion(out, 4.0)
    shaking = motion(out, 11.0)
    assert shaking > quiet * 3, \
        f"the shake does not move: {shaking:.2f} vs {quiet:.2f} before it"
finally:
    edit.OUTRO = saved


# --- and the other endings still work --------------------------------------

hype_b, hype_f = edit._outro_filters(82.0, mood="hype")
assert "between(" in hype_b and hype_f == [], "the stinger regressed"
assert edit._outro_filters(20.0, mood="emotional") == ("", []), \
    "the short-clip guard regressed"

print("v32 ok — dip reaches black; jamet freeze+shake renders at 1080x1920")
