import os
import subprocess
import sys

# _v95: salinan cron di repo WAJIB sama dengan yang benar-benar dijalankan.
#
# Kenapa gate ini perlu: Hermes cron hanya mau menjalankan script dari
# ~/.hermes/scripts/ (path absolut ditolak), dan folder itu nol version
# control. scripts/cron/ di repo adalah salinan untuk riwayat. Dua salinan
# yang menyimpang = git memperlihatkan versi yang TIDAK PERNAH JALAN, kelas
# kesalahan yang sama dengan "file di disk bukan kode yang dieksekusi" dan
# sudah menipu di repo ini sebelumnya (fix masuk file, render tetap rusak).
#
# Gate ini membandingkan BYTE, bukan "ada file-nya".

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.join(BASE, "scripts", "cron")
HIDUP = os.path.expanduser("~/.hermes/scripts")

cek = 0
beda = []
hilang = []

names = sorted(f for f in os.listdir(REPO) if f.endswith(".sh"))
assert names, "scripts/cron/ kosong — salinan riwayat hilang"

for n in names:
    a = os.path.join(REPO, n)
    b = os.path.join(HIDUP, n)
    if not os.path.exists(b):
        hilang.append(n)
        continue
    isi_a = open(a, "rb").read()
    isi_b = open(b, "rb").read()
    if isi_a != isi_b:
        beda.append((n, len(isi_a), len(isi_b)))
    cek += 1

assert not hilang, (
    f"script ada di repo tapi TIDAK ada di {HIDUP}: {hilang} — "
    "cron tidak akan pernah menjalankannya")

assert not beda, (
    "salinan repo menyimpang dari yang dijalankan cron: "
    + "; ".join(f"{n} (repo {x}B vs hidup {y}B)" for n, x, y in beda)
    + " — git memperlihatkan versi yang tidak pernah jalan. Sinkronkan: "
      "cp ~/.hermes/scripts/<nama> scripts/cron/")

# Pagar memori harus benar-benar terpasang di yang DIJALANKAN, bukan cuma
# di salinan repo. Dibaca dari file hidup, bukan dari salinan.
wajib_pagar = ("clipper_render_tick.sh", "bio1_render_broll.sh",
               "stockstory_scene_filler.sh")
for n in wajib_pagar:
    p = os.path.join(HIDUP, n)
    if not os.path.exists(p):
        continue
    isi = open(p, encoding="utf-8").read()
    pakai = ("CLIPPER_FFMPEG" in isi or "scripts/shim" in isi
             or "ffguard" in isi)
    assert pakai, (
        f"{n} yang DIJALANKAN cron tidak memakai pagar memori — satu ffmpeg "
        "bisa menarik hermes-gateway mati lagi (terjadi 3x pada 23 Okt 2026)")
    assert "export FFGUARD_THREADS=" not in isi, (
        f"{n} menyuntik FFGUARD_THREADS; itu menggeser bit keluaran render "
        "dan operator minta hasil clip tidak berubah")
    cek += 2

print(f"_v95_cron_salinan_sinkron.py OK — {cek} cek; {len(names)} script "
      f"salinan identik byte dengan yang dijalankan cron, pagar terpasang "
      f"di yang hidup")
