# Gate gaya podcast: tinta antar kata ga boleh numpuk, diukur di PIKSEL.
# Tiap kata dirender ke layer sendiri di posisi dari layout(); overlap alpha
# antar layer dihitung. Render v2 26 Okt: "TIDAK" nimpa "sekarang jika kamu".
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from PIL import Image
import caption_podcast as cp


def layers(screen, key):
    placed, block_h = cp.layout(screen, key)
    out = []
    for (i, t, size, font, x, y) in placed:
        canvas = Image.new("L", (1080, block_h + 400), 0)
        im = cp._tile(t, size, font).getchannel("A")
        # cuma tinta huruf (alpha tinggi), bayangan lembut ga dihitung
        ink = im.point(lambda v: 255 if v > 200 else 0)
        canvas.paste(ink, (int(x) - cp.PAD, int(y) + 100), ink)
        out.append((t, np.asarray(canvas) > 0))
    return out


def overlap(screen, key):
    ls = layers(screen, key)
    worst = (0, "", "")
    for a in range(len(ls)):
        for b in range(a + 1, len(ls)):
            n = int((ls[a][1] & ls[b][1]).sum())
            if n > worst[0]:
                worst = (n, ls[a][0], ls[b][0])
    return worst


def W(*ws):
    return [{"word": w, "start": i, "end": i + 0.5} for i, w in enumerate(ws)]


KASUS = [
    (W("sekarang", "jika", "kamu", "TIDAK", "percaya"), 3),
    (W("mari", "kita", "melihat", "nombor"), 3),
    (W("my", "height", "in", "inches"), 1),
    (W("gua", "ENGGAK", "malu", "kayak", "ada"), 1),
]
gagal = []
for scr, key in KASUS:
    n, a, b = overlap(scr, key)
    teks = " ".join(w["word"] for w in scr)
    print(f"  {teks:34s} kunci={scr[key]['word']:8s} tinta numpuk {n:4d} px  ({a}/{b})")
    if n > 0:
        gagal.append(teks)
assert not gagal, f"tinta numpuk di: {gagal}"
print("_v96 ok: nol piksel tinta numpuk di", len(KASUS), "layar")
