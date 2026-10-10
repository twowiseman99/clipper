"""Akhiran jamet ditutup dip to black, dan diukur LUMINANCE-nya.

Operator: "video full stop tinggal gambar gibran! Terus selesainya dip to
black, outro 3-5s gamasalah".

Konstanta OUTRO_FADE sudah ada sejak kerjaan register, tapi HANYA cabang
melancholy yang memakainya. Akhiran jamet berhenti di tengah goyangan pada
frame terakhir. Ini kelas bug yang sama seperti bgm._CLASH: aturannya ada,
jalurnya tidak pernah lewat situ.

Dua hal yang dijaga, dan keduanya butuh ffmpeg BENERAN dijalankan:

1. Filter `fade` memang muncul di cabang jamet, dan ffmpeg MENERIMA graphnya.
   Tes yang hanya memeriksa string lolos sementara ffmpeg menolak seluruh
   graph — itu pernah terjadi pada `hue=...:eval=frame` dan membunuh render
   setelah unduhan dan transkripsi sudah dibayar.
2. Gambarnya benar-benar sampai HITAM dan menahannya. Fade hanya mencapai nol
   di st+d, jadi kalau klip berakhir tepat di situ frame terakhir masih abu-abu
   gelap — pernah terukur Y=21 pada akhiran melancholy.

Fade dipasang SETELAH trim+setpts, jadi waktunya relatif ke stream yang sudah
dipotong, bukan ke `dur` aslinya. Itu sebabnya tes ini mengukur file keluaran,
bukan menghitung ulang ekspresinya.
"""
import os
import subprocess
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, "/home/ubuntu/clipper")
import edit

DUR = 28.4
OUT = "/tmp/_v64_fade.mp4"
FRAMES = "/tmp/_v64_frames"

edit.OUTRO = "jamet"
bright, filters = edit._outro_filters(DUR, mood="hype", freeze_frame_at=27.2)
assert filters, "cabang jamet tidak menghasilkan filter"

# --- 1. fade ada di cabang jamet ------------------------------------------
fades = [f for f in filters if f.startswith("fade=")]
assert len(fades) == 1, \
    "akhiran jamet harus punya tepat satu fade, dapat %d: %s" % (
        len(fades), fades)
assert "color=black" in fades[0], "fade harus ke hitam: %s" % fades[0]
# Fade adalah filter TERAKHIR: dipasang setelah trim/setpts supaya waktunya
# relatif ke stream yang sudah dipotong.
assert filters[-1] is fades[0] or filters[-1] == fades[0], \
    "fade harus di akhir rantai, setelah trim dan setpts"
print("filter         : %s" % fades[0])

# --- 2. ffmpeg menerima graphnya, bukan cuma stringnya yang rapi ----------
graph = ",".join(filters)
p = subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
     "testsrc=size=1080x1920:rate=30:duration=%s" % (DUR + 1),
     "-vf", graph, "-c:v", "libx264", "-crf", "26", "-t", str(DUR), OUT],
    capture_output=True, text=True)
assert p.returncode == 0, \
    "ffmpeg MENOLAK graph jamet:\n%s" % p.stderr[-800:]
print("ffmpeg         : graph diterima, keluaran %s" % OUT)

# --- 3. gambarnya sampai hitam DAN menahannya ----------------------------
os.makedirs(FRAMES, exist_ok=True)
for f in os.listdir(FRAMES):
    os.remove(os.path.join(FRAMES, f))
subprocess.run(
    ["ffmpeg", "-v", "error", "-y", "-ss", str(DUR - 3.0), "-i", OUT,
     "-vf", "fps=5", os.path.join(FRAMES, "f%03d.png")], check=True)

names = sorted(os.listdir(FRAMES))
assert len(names) >= 10, "terlalu sedikit frame diambil: %d" % len(names)
lum = [float(np.asarray(Image.open(os.path.join(FRAMES, n)).convert("L"),
                        dtype=np.float32).mean()) for n in names]
print("luminance      : awal %.1f -> akhir %.1f (%d frame)"
      % (lum[0], lum[-1], len(lum)))

# Frame terakhir harus benar-benar hitam, bukan abu-abu gelap.
assert lum[-1] <= 2.0, (
    "frame terakhir luminance %.1f — fade berakhir tepat di ujung klip, "
    "jadi gambarnya abu-abu gelap bukan hitam (kasus Y=21 terulang)" % lum[-1])

# Dan hitamnya DITAHAN: minimal dua frame terakhir sudah nol.
assert lum[-2] <= 4.0, (
    "hitamnya tidak ditahan: frame kedua dari akhir masih %.1f" % lum[-2])
print("hitam ditahan  : dua frame terakhir %.1f dan %.1f" % (lum[-2], lum[-1]))

# --- 4. kontrol negatif: awal jendela masih TERANG -----------------------
# Kalau seluruh akhiran redup, yang kita buat adalah fade panjang, bukan
# "dip to black" di ujung. Operator menolak itu sebelumnya ("aneh").
assert lum[0] >= 60.0, (
    "awal jendela 3s terakhir sudah gelap (%.1f) — ini fade panjang, bukan "
    "dip di ujung; gambar harus terbaca sampai detik terakhir" % lum[0])
print("kontrol negatif: awal jendela %.1f (masih terang, dip hanya di ujung)"
      % lum[0])

# --- 5. dip tidak memakan seluruh freeze ---------------------------------
# OUTRO_FADE harus jauh lebih pendek dari freeze, atau goyangannya tidak
# terlihat karena gambarnya sudah gelap.
assert edit.OUTRO_FADE < edit.OUTRO_JAMET_SECONDS * 0.45, (
    "OUTRO_FADE %.2f terlalu panjang untuk freeze %.2f — goyangannya "
    "tenggelam di dalam fade"
    % (edit.OUTRO_FADE, edit.OUTRO_JAMET_SECONDS))
print("proporsi       : fade %.2fs dari freeze %.2fs"
      % (edit.OUTRO_FADE, edit.OUTRO_JAMET_SECONDS))

print("\n_v64 ok — akhiran jamet dip to black, terukur di file keluaran")
