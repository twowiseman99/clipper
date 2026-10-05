"""Pillar framing must not be re-cropped by the base zoom.

The first pillar render looked wrong in a specific way: the whole point of
pillar is to stop `cover` slicing a 16:9 source, and the delivered frame still
had the news banner cut at both ends ("...RAL GIBRAN SARANKAN SISWA BAWA BEKAL
DARI RUM...") and the speaker's face clipped. Cause: `_zoompan` runs after the
pillar composite, so CLIPPER_ZOOM=1.2 cropped the finished card.

Checked here with real ffmpeg, not by reading the filter string — a graph that
looks right and a file that is 1080x1920 can still have thrown away a third of
the frame.
"""

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import edit  # noqa: E402

SRC_W, SRC_H = 1920, 1080


def probe(path, expr):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", expr, "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True).stdout.strip()
    return out.split(",")


tmp = tempfile.mkdtemp()
src = os.path.join(tmp, "src.mp4")
# A 16:9 source with a horizontal gradient: the left and right thirds carry
# distinct brightness, so a horizontal crop is visible as a change in column
# statistics rather than having to be eyeballed.
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
     f"testsrc2=size={SRC_W}x{SRC_H}:rate=30:duration=2", "-pix_fmt",
     "yuv420p", src], check=True)

w, h = probe(src, "stream=width,height")
assert (int(w), int(h)) == (SRC_W, SRC_H), (w, h)

# --- the zoom pass must step aside in pillar mode ---------------------------
# NOTE: frame_mode is an ARGUMENT, not the module constant. The first version
# of this test set edit.FRAME_MODE and passed, while the real render — which
# gets pillar through --frame-mode and leaves the constant at the .env default
# "cover" — kept the 1.2x base zoom. Two "fixed" renders came out byte-for-byte
# identical (md5 e1ab71f8...) before the graph.txt showed z='1+0.1000-0.1000*
# cos(...)' still in place. So the parameter is what gets exercised here, and
# the constant is deliberately left pointing the other way.
saved_mode, saved_zoom = edit.FRAME_MODE, edit.ZOOM
try:
    edit.ZOOM = 1.2
    edit.FRAME_MODE = "cover"   # the .env default, as during a real render

    cover_zp = edit._zoompan(2.0, fps=30, frame_mode="cover")
    assert cover_zp and "zoompan" in cover_zp, cover_zp
    # The base zoom is a cosine breath, not a linear ramp: ZOOM=1.2 appears as
    # half-amplitude 0.1 either side of 1.0. Asserting on "1.2" was wrong about
    # the shape, which is exactly the kind of guess this suite exists to stop.
    assert "0.1000*cos" in cover_zp, cover_zp

    pillar_zp = edit._zoompan(2.0, fps=30, frame_mode="pillar")
    # No words -> no punches -> nothing left to do once the base zoom is gone.
    assert pillar_zp is None, pillar_zp

    # Punch-ins must still work in pillar mode: they are brief and deliberate,
    # unlike a standing crop. A word at 1.0s with high stress earns one.
    words = [{"word": "BEKAL", "start": 1.0, "end": 1.4, "stress": 2.0}]
    punched = edit._zoompan(2.0, fps=30, words=words, clip_start=0.0,
                            frame_mode="pillar")
    if punched is not None:
        assert "zoompan" in punched
        # The 1.2 standing breath must NOT be in there, only the punch term.
        assert "0.1000*cos" not in punched, punched

    # And the pillar call site must actually pass the argument through.
    import inspect as _inspect
    pillar_src = _inspect.getsource(edit)
    pmark = pillar_src.index('elif frame_mode == "pillar" and not split_screen:')
    pbranch = pillar_src[pmark:pillar_src.index("\n        else:", pmark)]
    assert "frame_mode=frame_mode" in pbranch, (
        "pillar calls _zoompan without frame_mode; it will read the .env "
        "constant and keep the base zoom\n" + pbranch[-300:])
finally:
    edit.FRAME_MODE, edit.ZOOM = saved_mode, saved_zoom

# --- the pillar graph itself still produces 1080x1920 -----------------------
# The card fills PILLAR_COVER of the canvas HEIGHT, not the full width of a
# letterboxed 16:9 frame. The first version showed 32% footage and 68% blur,
# with a head about 13% of the canvas height; the operator's verdict was
# "jelek banget". Scaling by height is the fix and the cost is horizontal
# crop, so the window follows the speaker.
card_h = int(edit.CANVAS_H * edit.PILLAR_COVER) // 2 * 2
pan_x = edit._pillar_pan_x(src, 0.0, 2.0, card_h)
fg = (f"scale=-2:{card_h},"
      f"scale=w='max(iw,{edit.CANVAS_W})':h=-2,"
      f"crop={edit.CANVAS_W}:{card_h}:x={pan_x}:y='(ih-oh)/2'")
graph = (
    f"split=2[pbg][pfg];"
    f"[pbg]scale={edit.CANVAS_W}:{edit.CANVAS_H}:"
    f"force_original_aspect_ratio=increase,"
    f"scale=iw*{edit.PILLAR_BG_ZOOM:.2f}:-2,"
    f"crop={edit.CANVAS_W}:{edit.CANVAS_H},"
    f"gblur=sigma={edit.PILLAR_BLUR:.0f},"
    f"eq=brightness=-{edit.PILLAR_BG_DIM:.2f}:"
    f"saturation={edit.PILLAR_BG_SAT:.2f}[pbgb];"
    f"[pfg]{fg}[pfgs];"
    f"[pbgb][pfgs]overlay=(W-w)/2:(H-h)/2"
)
out = os.path.join(tmp, "pillar.mp4")
r = subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", graph,
     "-frames:v", "20", "-pix_fmt", "yuv420p", out],
    capture_output=True, text=True)
assert r.returncode == 0, r.stderr[-700:]
w, h = probe(out, "stream=width,height")
assert (int(w), int(h)) == (edit.CANVAS_W, edit.CANVAS_H), (w, h)

# The sharp card must dominate the canvas. Anything much under half and the
# subject is back to thumbnail size with the screen given over to blur.
assert card_h >= edit.CANVAS_H * 0.6, (card_h, edit.CANVAS_H)
blur_frac = 1 - card_h / edit.CANVAS_H
assert blur_frac <= 0.4, blur_frac

# A centred fallback is acceptable (no cv2 / no face found), but the
# expression must be a real crop position either way.
assert "iw" in pan_x, pan_x

# --- pillar must not fall into the fill branch and get re-cropped ----------
# The first fix was a no-op and the suite stayed green, because _v39 only
# checked _zoompan and a hand-built graph. The real render took a different
# path: `pillar` fell through to the "fill" else-branch, which scales the
# already-composed pillar frame to a band and crops it to canvas width —
# cropping the finished card a second time. Two renders came out byte-for-byte
# identical (md5 e1ab71f8...), which is what proved the fix never ran.
#
# So this asserts on the graph the renderer actually builds.
import inspect  # noqa: E402

src = inspect.getsource(edit)
mark = src.index('elif frame_mode == "pillar" and not split_screen:')
# Stop at the next branch rather than guessing a character count: too short
# and the assertions never reach the code, too long and they read the fill
# branch's filters as pillar's. Both happened while writing this test.
branch = src[mark:src.index("\n        else:", mark)]
assert "[0:v]" in branch, "pillar branch does not consume the source stream"
assert "[mnsrc]" not in branch, "pillar is being re-cropped by the fill branch"
# The pillar branch must terminate the chain itself, so the shared
# "[bg][mn]overlay" line below cannot touch it.
assert f"[{{base_label}}]" in branch or "base_label" in branch, branch[:200]

# The shared overlay line is guarded on cover only; pillar must be excluded
# from it too, or it would look for [bg]/[mn] labels that pillar never made.
gi = src.index("[bg][mn]overlay")
guard = src[max(0, gi - 420):gi]
assert "pillar" in guard, (
    "the [bg][mn] overlay still runs for pillar; it has no such labels\n"
    + guard[-260:])

# --- the editorial caption must clear the source's own banner --------------
# In pillar the source keeps its lower-third chyron. With the card 1440px tall
# and centred, that banner sits around y=1377; the 206px editorial block at
# the 0.62 default lands 1190-1396 and overlaps it. Reviewed on a delivered
# frame: "practically touching... the eye has to work to separate your caption
# from the broadcaster's headline".
BLOCK_H = 206           # measured from a real _editorial_layer render
card_top = (edit.CANVAS_H - card_h) // 2
banner_top = card_top + card_h * 0.79    # chyron at ~79% of source height

pillar_y = int(edit.EDIT_Y_FRAC_PILLAR * edit.CANVAS_H)
assert pillar_y + BLOCK_H <= banner_top, (
    "pillar caption overlaps the source banner: block ends %d, banner starts %d"
    % (pillar_y + BLOCK_H, banner_top))

# And the call site must actually pick the pillar value, not the default.
cap_mark = src.index("if caption_style == \"editorial\" and not split_screen:")
cap_branch = src[cap_mark:cap_mark + 420]
assert "EDIT_Y_FRAC_PILLAR" in cap_branch, (
    "editorial captions ignore pillar framing\n" + cap_branch)

print("_v39 ok — pillar skips the %.2fx base zoom (cover keeps it), "
      "graph renders %dx%d, card %dpx tall (%.0f%% footage / %.0f%% blur), "
      "own branch not re-cropped, caption clears the banner by %dpx"
      % (1.2, int(w), int(h), card_h, card_h / edit.CANVAS_H * 100,
         blur_frac * 100, banner_top - (pillar_y + BLOCK_H)))
