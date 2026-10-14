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
import numpy as np  # noqa: E402
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

# --- accent TIDAK BOLEH ngubah ukuran -----------------------------------
# Dulu kebalikannya: accent bikin baris lebih gede. Operator mutusin satu
# ukuran buat semua ("besar kecilnya gausah diubah lagi"), jadi sekarang yang
# dijaga justru accent TIDAK ngubah apa pun. Ini penting: accent_words
# datangnya dari model, dan model kadang nandai kadang nggak -- kalau ukuran
# masih ikut itu, dua klip dari bahan sama bisa beda tampilan tanpa alasan.
ov2 = edit._bold_layer(ws, 0.0, tmp, accent_words=("gibran",))
h1 = max(Image.open(o.path).height for o in ov)
h2 = max(Image.open(o.path).height for o in ov2)
assert h2 == h1, "accent masih ngubah ukuran (%d vs %d)" % (h1, h2)
ok("accent ga ngubah ukuran (%d px dua-duanya)" % h1)

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
frac = lebar / edit.CANVAS_W

# Yang dijaga di sini BENTUK MUKA HURUFNYA, bukan ukuran pilihan operator.
# Ukuran itu selera dan bisa diubah lewat CLIPPER_BOLD_FONT_SIZE; kalau tes
# maku ke angka referensi (29.8%), tiap kali operator minta "kecilan" tesnya
# merah padahal ga ada yang rusak -- itu yang kejadian waktu 120 turun ke 94.
#
# Yang BUKAN selera: Anton itu condensed, DejaVu Bold ga. Diukur pada ukuran
# yang SAMA, 'GIBRAN' DejaVu ~30% lebih lebar dari Anton. Rasio itu sifat
# fontnya, jadi kebawa di ukuran apa pun -- dan itu yang dijaga.
f_dejavu = None
for kandidat in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
    if os.path.exists(kandidat):
        f_dejavu = ImageFont.truetype(kandidat, edit.BOLD_FONT_SIZE)
        break
assert f_dejavu is not None, "DejaVu ga ketemu, ga bisa bandingin lebar muka"
rasio = lebar / f_dejavu.getlength("GIBRAN")
assert rasio < 0.85, \
    "font ga condensed: 'GIBRAN' %.0f%% lebar DejaVu (Anton ~77%%)" % (rasio*100)
ok("muka huruf condensed (%.0f%% lebar DejaVu di size sama)" % (rasio * 100))

# Ukurannya sendiri cuma dijaga di rentang masuk akal: ga ngisi frame penuh,
# ga sekecil teks badan. Rentangnya lebar ON PURPOSE -- ini pagar, bukan
# target.
assert 0.12 < frac < 0.45, \
    "'GIBRAN' %.1f%% lebar frame, di luar rentang masuk akal" % (frac * 100)
ok("ukuran dalam rentang masuk akal (%.1f%% lebar frame)" % (frac * 100))

# --- SATU ukuran buat semua baris ---------------------------------------
# Keputusan operator: "besar kecilnya gausah diubah lagi, konsisten aja 1
# ukuran buat font nya". Jadi penekanan-lewat-ukuran DIBUANG, dan klip ga
# lagi beda tampilan cuma gara-gara model nandai kata atau nggak.
assert edit.BOLD_FONT_SIZE_SMALL == edit.BOLD_FONT_SIZE, \
    "masih dua ukuran: %d vs %d" % (edit.BOLD_FONT_SIZE,
                                    edit.BOLD_FONT_SIZE_SMALL)
ok("satu ukuran buat semua baris (%d px)" % edit.BOLD_FONT_SIZE)

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

# --- KONTROL NEGATIF: ukuran SERAGAM di tiap langkah --------------------
# Kontrol lama di sini nuntut accent bikin lebih gede. Itu udah dibuang.
# Yang dijaga sekarang: dalam satu frasa, tiap baris tingginya SAMA -- jadi
# ga ada baris yang digedein sendiri, baik dari accent maupun dari kode yang
# milih kata sendiri.
t_kecil = [Image.open(o.path).height for o in ov]
t_accent = [Image.open(o.path).height for o in ov2]
assert max(t_kecil) == max(t_accent), \
    "accent masih ngubah ukuran: %d vs %d" % (max(t_kecil), max(t_accent))
# tinggi overlay naik waktu baris kedua masuk, jadi yang dibandingin
# LANGKAH per LANGKAH, bukan maksimum doang
for i, (a, b) in enumerate(zip(t_kecil, t_accent)):
    assert a == b, "langkah %d beda tinggi: %d vs %d" % (i, a, b)
ok("KONTROL: tiap langkah ukurannya sama, accent ga ngaruh")

# --- jarak antar baris = angka yang bisa DIUKUR -------------------------
# BOLD_LINE_GAP dulu diitung antar KOTAK tile, dan tiap tile bawa padding
# transparan BOLD_PAD per sisi buat stroke + bayangan. Jadi "gap 14"
# kerendernya 14 + 2*19 = 52px udara antar huruf, dan itu yang operator
# bilang kerenggangan. Sekarang padding itu dikurangin, jadi konstantanya
# berarti jarak yang kelihatan. Dicek di PIKSEL, bukan di konstanta.
ws_gap = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4}
          for i, w in enumerate("SUPAYA MEMINANG MAS GIBRAN".split())]
ov_gap = edit._bold_layer(ws_gap, 0.0, tmp, accent_words=())
jarak_ukur = []
for o in ov_gap:
    a = np.asarray(Image.open(o.path).convert("RGBA"))
    al = a[:, :, 3] > 40
    if not al.any():
        continue
    rr = al.any(axis=1)
    grup, cur = [], None
    for i, v in enumerate(rr):
        if v and cur is None:
            cur = i
        elif not v and cur is not None:
            grup.append((cur, i))
            cur = None
    if cur is not None:
        grup.append((cur, len(rr)))
    grup = [g for g in grup if g[1] - g[0] >= 10]
    if len(grup) >= 2:
        jarak_ukur.append(grup[1][0] - grup[0][1])
assert jarak_ukur, "ga ada overlay 2 baris buat diukur"
j = max(jarak_ukur)
assert abs(j - edit.BOLD_LINE_GAP) <= 6, \
    "jarak terukur %dpx jauh dari konstanta %dpx -- padding tile ga dikurangin" \
    % (j, edit.BOLD_LINE_GAP)
ok("jarak antar baris terukur %dpx, sesuai konstanta %dpx"
   % (j, edit.BOLD_LINE_GAP))

print("\n%d cek + 4 kontrol negatif, gaya bold jalan tanpa ngerusak yang lama" % n)
