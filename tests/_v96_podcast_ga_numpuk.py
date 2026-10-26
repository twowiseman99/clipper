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


# Gate kedua: tinta ga boleh keluar tepi layar. Render v3 Gibran 26 Okt:
# kunci "IBU" pendek, 4 kata kecil di baris atas rata kanan ke "IBU" ->
# "tertangani" kepotong jadi "rtangani" (tinta x -52 di kode lama).
def tepi(screen, key):
    placed, h = cp.layout(screen, key)
    can = np.zeros((h + 400, 1080 + 1600), bool)
    for (i, t, size, font, x, y) in placed:
        a = np.asarray(cp._tile(t, size, font))[:, :, 3] > 128
        X = int(x) - cp.PAD + 800
        can[int(y):int(y) + a.shape[0], X:X + a.shape[1]] |= a
    cols = np.where(can.any(axis=0))[0] - 800
    return int(cols.min()), int(cols.max())


TEPI = KASUS + [
    (W("tertangani", "dengan", "baik,", "ya,", "ibu"), 4),       # baris atas panjang, kunci pendek
    (W("ibu", "tertangani", "dengan", "baik", "sekali"), 0),     # baris bawah panjang
    (W("jangan", "bisa", "dipaksakan", "masuk", "dulu"), 2),     # kunci panjang
]
luar = []
for scr, key in TEPI:
    l, r = tepi(scr, key)
    teks = " ".join(w["word"] for w in scr)
    print(f"  {teks:34s} kunci={scr[key]['word']:10s} tinta x {l:5d}..{r:5d}")
    if l < 0 or r >= 1080:
        luar.append(f"{teks} ({l}..{r})")
assert not luar, f"tinta keluar tepi layar: {luar}"
print("_v96 ok: nol tinta keluar tepi di", len(TEPI), "layar")
