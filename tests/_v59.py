"""Hook footage must be judged AFTER the crop, not before it.

Operator: "Pas hook coba pakai scene lain ... di video ini cari scene gibran"

The scene search worked and still shipped the wrong hook twice. Gibran was in
the file — 5 of 5 frames, verified — but he was standing on the LEFT of a 16:9
frame, and the pillar composite keeps the middle. What survived the crop was
Megawati walking through the centre.

So the subject check ran on footage nobody would ever see. Same shape as the
b-roll gate reading the first frame of a window: the thing measured was not the
thing delivered.

This pins the rule that costs the least to keep: when a verified cut is handed
in as --opening, its aspect must already match what the renderer will keep, so
that passing the check and surviving the crop are the same event.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import edit  # noqa: E402

HOOK = ("/home/ubuntu/clipper/media/u4f8ae6b26d58/gibran_hook_crop.mp4")


def probe(path, stream, fields):
    q = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream,
         "-show_entries", "stream=" + ",".join(fields),
         "-of", "default=nw=1", path],
        capture_output=True, text=True, timeout=300)
    return dict(l.split("=", 1) for l in q.stdout.strip().splitlines()
                if "=" in l)


if not os.path.exists(HOOK):
    print("_v59 skip — verified hook cut not on disk")
    raise SystemExit(0)

v = probe(HOOK, "v", ["width", "height", "duration"])
w, h = int(v["width"]), int(v["height"])

# --- 1. the cut is not wider than it is tall ---------------------------------
# A 16:9 cut handed to a 9:16 renderer loses its left and right thirds. The
# subject check then measures footage that never reaches the viewer.
assert w <= h, (
    "hook cut is %dx%d (landscape): the pillar composite keeps the middle, so "
    "a subject standing off-centre is cropped away after passing the check"
    % (w, h))

# --- 2. no audio stream at all -----------------------------------------------
# The mute rule stops depending on a flag being set correctly when there is
# nothing to mute.
a = probe(HOOK, "a", ["codec_name"])
assert not a, (
    "hook cut carries an audio stream (%s): muting then depends on "
    "CLIPPER_MUTE_BROLL_HOOK staying on" % a.get("codec_name"))

# --- 3. the mute guard is still in place for link-sourced openings -----------
# Local cuts are silent by construction, but a YouTube --opening still relies
# on the guard.
esrc = open(os.path.join(os.path.dirname(__file__), "..", "edit.py")).read()
assert edit.BGM_MUTE_BROLL_HOOK, (
    "CLIPPER_MUTE_BROLL_HOOK defaults to off: a link-sourced opening would "
    "play its own audio under the hook")
i_guard = esrc.find("if intro_idx is not None and not BGM_MUTE_BROLL_HOOK")
assert i_guard > 0, "the hook-audio guard is gone"

# --- 4. duration survives the trim -------------------------------------------
dur = float(v["duration"])
assert 2.0 <= dur <= 6.0, (
    "hook cut is %.2fs: outside the range a hook can hold attention" % dur)

print("_v59 ok — hook cut is %dx%d (not landscape, survives the pillar crop), "
      "carries no audio stream, %.2fs long, and the mute guard still covers "
      "link-sourced openings" % (w, h, dur))
