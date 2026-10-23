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
    # Komentar DIBUANG dulu. Versi pertama gate ini membaca seluruh file dan
    # lolos pada bio1_render_broll.sh karena kata "shim" ada di sebuah
    # KOMENTAR yang mengklaim shim terpasang — padahal PATH shim belum pernah
    # dipasang di sana. Satu jam kemudian ffmpeg bio1 memegang 7,2 GB dan
    # kernel mencatat global_oom lagi (19:06). Komentar bukan pagar.
    kode = "\n".join(b for b in isi.split("\n")
                     if not b.lstrip().startswith("#"))

    # DUA syarat, bukan salah satu. `ffguard` saja tidak cukup: bio1 memakai
    # "$FFG" untuk ffmpeg-nya sendiri sementara ffmpeg DI DALAM
    # build_video_scenes.py (5 pemanggilan "ffmpeg" literal) lewat begitu saja.
    # Pemanggil yang tidak punya env hook hanya tertangkap oleh PATH shim.
    ada_env = "CLIPPER_FFMPEG" in kode
    ada_shim = "scripts/shim" in kode
    ada_wrap = "ffguard" in kode
    # PATH shim menangkap SEMUA pemanggilan (termasuk "ffmpeg" literal di dalam
    # modul Python), jadi shim sendirian sudah cukup. env CLIPPER_FFMPEG sendirian
    # TIDAK cukup: 7 modul clipper (broll.py, emphasis.py, freeze_pick.py, ...)
    # memanggil "ffmpeg" literal dan tidak pernah membaca env itu.
    assert ada_shim or (ada_env and ada_wrap), (
        f"{n} yang DIJALANKAN cron tidak memakai pagar memori — satu ffmpeg "
        "bisa menarik hermes-gateway mati lagi (terjadi 3x pada 23 Okt 2026). "
        f"env={ada_env} shim={ada_shim} wrapper={ada_wrap}")

    # Skrip yang memanggil Python yang punya ffmpeg literal WAJIB punya PATH
    # shim; env saja tidak menjangkau mereka.
    if "python" in kode or ".venv/bin/python" in kode:
        assert ada_shim, (
            f"{n} menjalankan Python tapi tidak memasang PATH shim. Modul "
            "Python di repo ini memanggil \"ffmpeg\" literal dan TIDAK membaca "
            "CLIPPER_FFMPEG, jadi ffmpeg-nya lolos dari pagar. Inilah yang "
            "menyebabkan OOM 19:06 pada 23 Okt 2026. Tambahkan: "
            "export PATH=/home/ubuntu/clipper/scripts/shim:$PATH")
        cek += 1

    assert "export FFGUARD_THREADS=" not in kode, (
        f"{n} menyuntik FFGUARD_THREADS; itu menggeser bit keluaran render "
        "dan operator minta hasil clip tidak berubah")
    cek += 2

print(f"_v95_cron_salinan_sinkron.py OK — {cek} cek; {len(names)} script "
      f"salinan identik byte dengan yang dijalankan cron, pagar terpasang "
      f"di yang hidup")
