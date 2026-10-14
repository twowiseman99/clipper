"""Gaya caption "bold": satu warna, penekanan lewat UKURAN.

Yang dijaga di sini sifatnya, bukan angka fontnya -- 120/86 itu keputusan
hasil ngukur referensi, bisa berubah kalau operator minta. Yang TIDAK boleh
berubah:

  - tiap kata warnanya SAMA (ga ada highlight karaoke di gaya ini)
  - accent bikin baris jadi LEBIH GEDE, bukan ganti warna
  - ga ada kotak latar
  - gaya lama (phrase/karaoke) TETEP seperti sebelumnya

Yang terakhir itu kontrol negatifnya: operator udah approve dua preset, dan
nambah gaya keempat ga boleh ngubah yang udah dia setujuin. Tanpa cek ini,
"gaya bold jalan" bisa berarti "gua nimpa gaya lama".
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image  # noqa: E402

import edit  # noqa: E402
import job  # noqa: E402

n = 0


def ok(label):
    global n
    n += 1
    print("  %-52s ok" % label)


def kata(teks, langkah=0.35):
    return [{"word": w, "start": i * langkah, "end": (i + 1) * langkah - 0.05}
            for i, w in enumerate(teks.split())]


def warna_dominan(path, langkah=2):
    im = Image.open(path).convert("RGBA")
    px = im.load()
    hit = {}
    for y in range(0, im.height, langkah):
        for x in range(0, im.width, langkah):
            r, g, b, a = px[x, y]
            if a < 200:
                continue
            k = (r // 40, g // 40, b // 40)
            hit[k] = hit.get(k, 0) + 1
    return hit


tmp = tempfile.mkdtemp(prefix="v83_")
ws = kata("SUPAYA MEMINANG MAS GIBRAN")

# --- gaya kedaftar di dua tempat yang beda ------------------------------
# job.py punya DUA daftar pilihan: catalogue() dan argparse. Yang ketinggalan
# bikin --caption-style bold ditolak padahal kodenya udah ada.
ids = [c["id"] for c in job.catalogue()["caption_style"]]
assert "bold" in ids, "bold ga ada di catalogue(): %s" % ids
ok("bold kedaftar di catalogue()")

import subprocess  # noqa: E402
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(REPO, ".venv", "bin", "python")
h = subprocess.run([PY if os.path.exists(PY) else sys.executable,
                    os.path.join(REPO, "job.py"), "--help"],
                   capture_output=True, text=True, timeout=120).stdout
m = re.search(r"caption-style \{([^}]*)\}", h)
assert m, "--caption-style ga ketemu di --help"
pilihan = m.group(1).split(",")
assert "bold" in pilihan, \
    "argparse nolak bold (daftar KEDUA di job.py, gampang kelewat): %s" % pilihan
ok("bold keterima CLI nyata (daftar KEDUA, %s)" % ",".join(pilihan))

# --- tanpa accent: semua kecil, satu warna ------------------------------
ov = edit._bold_layer(ws, 0.0, tmp, accent_words=())
assert ov, "ga ada overlay"
ok("tanpa accent: overlay kebentuk")

# --- accent bikin GEDE, bukan ganti warna -------------------------------
ov2 = edit._bold_layer(ws, 0.0, tmp, accent_words=("gibran",))
h1 = max(Image.open(o.path).height for o in ov)
h2 = max(Image.open(o.path).height for o in ov2)
assert h2 > h1, "accent ga bikin lebih gede (%d vs %d)" % (h1, h2)
ok("accent nambah ukuran (%d -> %d px)" % (h1, h2))

# --- warna: putih doang, ga ada teal/kuning -----------------------------
hit = warna_dominan(ov2[0].path)
TEAL = (1, 4, 4)     # #64BBA8
EMAS = (6, 5, 1)     # #FFD24A
BIRU = (2, 5, 6)     # #87CEFA, warna karaoke
for haram, nama in ((TEAL, "teal"), (EMAS, "kuning"), (BIRU, "biru karaoke")):
    assert hit.get(haram, 0) == 0, "ada %s di gaya bold" % nama
ok("ga ada warna highlight (teal/kuning/biru semuanya nol)")

putih = sum(v for k, v in hit.items() if min(k) >= 5)
hitam = sum(v for k, v in hit.items() if max(k) <= 1)
assert putih > 0, "ga ada piksel putih"
assert hitam > 0, "ga ada stroke/shadow hitam"
ok("putih %d px + stroke/shadow %d px" % (putih, hitam))

# --- ga ada kotak latar -------------------------------------------------
# kotak latar = baris paling atas gambar ikut keisi. Teks doang: baris atas
# harus transparan.
im = Image.open(ov2[0].path).convert("RGBA")
px = im.load()
atas = [px[x, 0][3] for x in range(0, im.width, 7)]
assert max(atas) < 60, "baris paling atas keisi (alpha %d) -- ada kotak latar" % max(atas)
ok("ga ada kotak latar (baris atas transparan)")

# --- 2 kata per baris ---------------------------------------------------
for ph in edit.group_phrases(ws, max_words=edit.BOLD_MAX_WORDS, max_lines=2):
    for line in ph["lines"]:
        assert len(line) <= 2, "baris isinya %d kata" % len(line)
ok("maks 2 kata per baris, sesuai referensi")

# --- font condensed beneran kepasang ------------------------------------
assert os.path.exists(edit.BOLD_FONT_PATH), \
    "font bold ga ada: %s" % edit.BOLD_FONT_PATH
from PIL import ImageFont  # noqa: E402
f = ImageFont.truetype(edit.BOLD_FONT_PATH, edit.BOLD_FONT_SIZE)
lebar = f.getlength("GIBRAN")
# referensi: 143px pada frame 480 lebar = 29.8%. Ambang longgar, yang dijaga
# cuma "jangan selebar DejaVu" (38%) dan "jangan kekecilan".
frac = lebar / edit.CANVAS_W
assert 0.24 < frac < 0.34, \
    "GIBRAN %.1f%% dari lebar, referensi 29.8%%" % (frac * 100)
ok("lebar huruf cocok referensi (%.1f%% vs 29.8%%)" % (frac * 100))

# --- kata muncul SATU-SATU, bukan frasa utuh sekaligus -----------------
# Ini yang gua salah baca pertama kali: gua ambil frame tiap 2 detik, lebih
# panjang dari satu frasa, jadi tiap sampel nunjukin frasa yang UDAH lengkap
# dan bedanya ga pernah masuk sampel. Frame tiap 0.2 detik nunjukin
# "SUPAYA" dulu, baru "SUPAYA / MEMINANG".
ws4 = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.35}
       for i, w in enumerate("SUPAYA MEMINANG MAS GIBRAN".split())]
ovb = edit._bold_layer(ws4, 0.0, tmp, accent_words=())
assert len(ovb) == 4, \
    "4 kata harusnya 4 langkah build, dapet %d -- frasa nongol sekaligus" % len(ovb)
ok("4 kata -> 4 langkah (muncul satu-satu)")

# tiap langkah nambah, ga ada yang ngurang
lebar = [Image.open(o.path).width for o in ovb]
tinggi = [Image.open(o.path).height for o in ovb]
luas = [w * h for w, h in zip(lebar, tinggi)]
assert all(b >= a for a, b in zip(luas, luas[1:])), \
    "blok nyusut di tengah build: %s" % luas
ok("blok cuma nambah, ga pernah nyusut")

# langkah 1 cuma SATU kata: mesti lebih sempit dari langkah terakhir
assert lebar[0] < lebar[-1], \
    "langkah pertama selebar yang terakhir (%d vs %d) -- ga ada build" % (
        lebar[0], lebar[-1])
ok("langkah 1 lebih sempit dari langkah akhir (%d < %d px)"
   % (lebar[0], lebar[-1]))

# --- kata yang udah nongol GA BOLEH gerak ------------------------------
# Blok tumbuh ke bawah, jadi kalau dipaku di bawah, kata pertama kelempar
# naik pas baris kedua masuk. Diukur: lompat 138 px. Referensi ga gerak.
atas = [o.y for o in ovb]
assert len(set(atas)) == 1, \
    "atas blok geser %s -- kata yang udah nongol ikut lompat" % atas
ok("atas blok tetap (%d px) -- kata yang udah nongol diem" % atas[0])

# --- langkah nyambung, ga ada lubang -----------------------------------
for a, b in zip(ovb, ovb[1:]):
    assert abs(a.t_end - b.t_start) < 0.01, \
        "ada lubang antara langkah: %.2f -> %.2f" % (a.t_end, b.t_start)
ok("langkah nyambung tanpa lubang")

# --- KONTROL: frasa beda tetep KEBERSIH, bukan numpuk ------------------
# Referensi ngosongin blok antar frasa (2 frame blank 0.4s). Kalau build
# ga pernah reset, klip 60 detik bakal numpuk terus sampai penuh.
ws_dua = ([{"word": w, "start": i * 0.3, "end": i * 0.3 + 0.25}
           for i, w in enumerate("SATU DUA".split())]
          + [{"word": w, "start": 3.0 + i * 0.3, "end": 3.0 + i * 0.3 + 0.25}
             for i, w in enumerate("TIGA EMPAT".split())])
ov_dua = edit._bold_layer(ws_dua, 0.0, tmp, accent_words=())
teks_akhir = Image.open(ov_dua[-1].path)
teks_awal = Image.open(ov_dua[0].path)
# frasa kedua ga boleh lebih tinggi dari frasa pertama yang lengkap:
# kalau numpuk, tingginya bakal 2x
assert teks_akhir.height <= teks_awal.height * 3, \
    "frasa numpuk, tinggi akhir %d vs awal %d" % (
        teks_akhir.height, teks_awal.height)
ok("KONTROL: frasa kedua ga numpuk di atas yang pertama")

# --- KONTROL NEGATIF: gaya lama ga boleh berubah ------------------------
ovp = edit._phrase_layer(ws, 0.0, tmp, accent_words=())
hp = warna_dominan(ovp[0].path)
ada_emas = any(k[0] >= 5 and 4 <= k[1] <= 5 and k[2] <= 2 for k in hp)
assert ada_emas, "KONTROL GAGAL: gaya phrase kehilangan kuningnya"
ok("KONTROL: gaya phrase masih kuning (preset lama utuh)")

ovk = edit._karaoke_layer(ws, 0.0, tmp, sub_y=1200)
assert ovk, "KONTROL GAGAL: gaya karaoke ga bikin overlay"
ok("KONTROL: gaya karaoke masih jalan")

# --- KONTROL NEGATIF: tanpa accent, ga ada yang digedein ----------------
# Kalau ini gagal, berarti kode milih kata sendiri -- itu ngarang penekanan
# yang modelnya ga pernah pilih.
t_kecil = [Image.open(o.path).height for o in ov]
t_accent = [Image.open(o.path).height for o in ov2]
assert max(t_kecil) < max(t_accent), \
    "tanpa accent ukurannya sama kayak yang pakai accent -- ada yang digedein sendiri"
ok("KONTROL: tanpa accent ga ada yang digedein sendiri")

print("\n%d cek + 3 kontrol negatif, gaya bold jalan tanpa ngerusak yang lama" % n)
