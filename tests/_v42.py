"""Caption text is not optional: a phrase too wide for one line must wrap.

The operator asked "Mana gibran ngomong kasih bekal?" of a clip whose whole
point was Gibran saying children should bring a lunch box from home. The word
"kotak" was in the transcript, survived the language review, was grouped into a
caption phrase — and never reached a frame.

_editorial_layer laid its tiles with:

    for t in tiles_top:
        if cx + t.width > block_w:
            break                      # <- silently drops the rest

emphasis.py uppercases stressed words, and "kotak" scored 1.43 against a 1.15
threshold, so the line became "-anaknya MEMBAWA KOTAK" at 1003px against a
943px limit. The widening came from the emphasis pass, the drop came from the
layout pass, and neither logged anything: dropping a tile was not an error in
this function, so warnings stayed empty and every gate passed.

This test renders the real layer and reads back the tiles, because the bug is
invisible at every level above the pixels.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import ImageFont  # noqa: E402

import edit  # noqa: E402


def words(text, start=10.0, step=0.4):
    out = []
    t = start
    for w in text.split():
        out.append({"word": w, "start": t, "end": t + step * 0.8})
        t += step
    return out


max_w = edit.CANVAS_W - int(edit.EDIT_X_FRAC * edit.CANVAS_W) - edit.PADDING

# Reproduce the exact phrase that lost a word: three words whose uppercase
# widths exceed the line budget, with the fourth as the punchline.
phrase = "-anaknya membawa kotak dari"
ws = words(phrase)
# Mark the same words emphasis.py marked, so the tiles are the bold uppercase
# cut rather than the narrower roman one.
for w in ws:
    if w["word"] in ("membawa", "kotak"):
        w["stress"] = 1.5

f_bold = ImageFont.truetype(edit.EDIT_FONT_SERIF_BOLD, edit.EDIT_SIZE)
f_rom = ImageFont.truetype(edit.EDIT_FONT_SERIF, edit.EDIT_SIZE)
pad = edit.EDIT_BOX_PAD


def tile_w(text, font):
    b = font.getbbox(text)
    return b[2] - b[0] + pad * 2


natural = (tile_w("-anaknya", f_rom) + tile_w("MEMBAWA", f_bold)
           + tile_w("KOTAK", f_bold))
assert natural > max_w, (
    "this fixture no longer overflows (%d <= %d), so it cannot catch the "
    "dropped-word bug — widen it" % (natural, max_w))

tmp = tempfile.mkdtemp()
overlays = edit._editorial_layer(ws, 10.0, tmp)
assert overlays, "no overlays produced"

# Every word must appear SOMEWHERE in the rendered block. Reading glyphs back
# is out of scope here, so check the geometry that carries them: with wrapping,
# the block must be tall enough for two top rows plus the punchline. The broken
# version produced exactly one top row because the overflow was discarded.
from PIL import Image  # noqa: E402

img = Image.open(overlays[0].path)
one_row = max(tile_w("X", f_bold), 1)
h_rom = f_rom.getbbox("Ay")[3] - f_rom.getbbox("Ay")[1] + pad * 2
h_punch = (ImageFont.truetype(edit.EDIT_FONT_SERIF_BOLD, edit.EDIT_PUNCH_SIZE)
           .getbbox("Ay"))
h_punch = h_punch[3] - h_punch[1] + pad * 2

assert img.width <= max_w, (img.width, max_w)
assert img.height > h_rom + edit.EDIT_LINE_GAP + h_punch * 0.8, (
    "block is %dpx tall: only one top row fits, so the third word was "
    "dropped instead of wrapped" % img.height)

# The non-overflowing case must not grow a second row for no reason.
short = words("dan saya titip")
flat = edit._editorial_layer(short, 10.0, tempfile.mkdtemp())
flat_img = Image.open(flat[0].path)
assert flat_img.height < img.height, (
    "a short phrase renders as tall as a wrapped one (%d vs %d): the wrap is "
    "firing when it should not" % (flat_img.height, img.height))

# And the paste loop must no longer contain the silent break.
import inspect  # noqa: E402

src = inspect.getsource(edit._editorial_layer)
assert "if cx + t.width > block_w:" not in src, (
    "the drop-on-overflow break is back in _editorial_layer")

print("_v42 ok — %dpx of tiles on a %dpx line wraps to a %dpx block "
      "(short phrase stays %dpx), no silent drop"
      % (natural, max_w, img.height, flat_img.height))
