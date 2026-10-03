"""The grief clip shipped with 20 white flashes. Twice.

Every setting read correctly in Python:

    OUTRO_DESAT = 0.5    OUTRO_DIM = 0.0    OUTRO_SLOWMO = 0.7
    _outro_kind("emotional") -> melancholy

But job.py does not pass "emotional". It passes bgm.pick()'s track mood, which
is a LIST, because one file can carry several mood words:

    track["mood"] == ["emotional"]
    str(["emotional"]).lower() == "['emotional']"   -> matches nothing
    _outro_kind(["emotional"]) -> "stinger"

So the clip about Palestinians being killed got the hype ending: 20 brightness
pulses across its final five seconds. The desaturation and slow motion were
never in the filter graph at all. Three renders measured flat (SATAVG 6.9 -> 7.1
where v13 had ramped 6.9 -> 1.5) and I twice blamed the wrong thing — once
`-r 30`, once the intro concat — because I was reading the source instead of the
graph ffmpeg actually received.

This test asserts on the real caller's data shape, not on a convenient string.
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import bgm
import edit

# --- the shape that actually shipped --------------------------------------
assert edit._outro_kind(["emotional"]) == "melancholy", \
    "a list mood must still pick the quiet ending — this is the v16/v17 bug"
assert edit._outro_kind(("sad", "chill")) == "melancholy"
assert edit._outro_kind("emotional") == "melancholy"
assert edit._outro_kind(["hype"]) == "stinger"
assert edit._outro_kind([]) == "stinger"
assert edit._outro_kind(None) == "stinger"
# A mood word that is sad in combination with others still wins: the register
# matters more than the tie-break.
assert edit._outro_kind(["hype", "emotional"]) == "melancholy"

# --- and the shape bgm.pick really returns -------------------------------
track, _why = bgm.pick("emotional", key="shapecheck")
if track:
    mood = track.get("mood")
    assert edit._outro_kind(mood) == "melancholy", (
        f"bgm.pick returned mood={mood!r} and the outro resolved to "
        f"{edit._outro_kind(mood)} — the pipeline is still disagreeing with "
        f"itself")

# --- the filters that result have to carry the ending --------------------
DUR = edit.OUTRO_SECONDS * 3 + 1
bright, filters = edit._outro_filters(DUR, mood=["emotional"])
assert any("hue=s=" in f for f in filters), f"no desaturation: {filters}"
assert "between(t," not in bright, \
    f"grief clip got flash pulses: {bright[:120]}"

# A hype clip must still get its pulses from a list mood too.
hb, hf = edit._outro_filters(DUR, mood=["hype"])
assert "between(t," in hb, f"hype lost its stinger: {hb[:120]}"
assert hf == [], hf

# --- real ffmpeg: the graph must contain what the mood implies ------------
TMP = "/tmp/_v18"
os.makedirs(TMP, exist_ok=True)
src = os.path.join(TMP, "src.mp4")
out = os.path.join(TMP, "out.mp4")
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
     f"testsrc2=size=240x426:rate=25:duration={DUR:.0f}",
     "-c:v", "libx264", "-preset", "ultrafast", src],
    check=True, capture_output=True)

chain = list(filters)
if bright:
    chain.append(f"eq=brightness='{bright}':eval=frame")
res = subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", ",".join(chain),
     "-c:v", "libx264", "-preset", "ultrafast", out],
    capture_output=True, text=True)
assert res.returncode == 0, f"ffmpeg rejected it: {res.stderr[:300]}"


def sat(path, at):
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{at}", "-i", path, "-frames:v", "1",
         "-vf", "signalstats,metadata=print:key=lavfi.signalstats.SATAVG:file=-",
         "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"SATAVG=([0-9.]+)", r.stdout)
    return float(m.group(1)) if m else None


start = DUR - edit.OUTRO_SECONDS
before, inside = sat(out, max(0.5, start - 2)), sat(out, start + edit.OUTRO_SECONDS * 0.7)
assert None not in (before, inside), "signalstats returned nothing"
# This is the measurement that caught the bug on the delivered clips: colour has
# to move, and the shipped files did not move at all.
assert inside < before * 0.9, \
    f"colour did not drain for a list mood: {before:.2f} -> {inside:.2f}"

for f in os.listdir(TMP):
    os.remove(os.path.join(TMP, f))
os.rmdir(TMP)

print(f"_v18.py OK — list mood ['emotional'] now resolves to melancholy "
      f"(was stinger: 20 flashes on a grief clip); SATAVG {before:.1f} -> "
      f"{inside:.1f} in the window, hype keeps its pulses")
