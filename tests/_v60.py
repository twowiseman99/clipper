"""Beku bertahan 5 detik DI FILE, dan still yang dipilih yang terlihat.

Versi pertama tes ini lulus sementara render aslinya rusak. Dia memeriksa
`loop=loop=150` di string filter dan menyimpulkan "panjang beku tidak berubah".
Yang memotong beku bukan `loop`, melainkan `trim=end=` di hilirnya: klon
disisipkan di frame 816, trim berhenti di frame 846, jadi beku nyata 30 frame =
1,0s. Tes memeriksa angka yang sedang diatur, bukan sifat yang diinginkan.

Jadi tes ini merender dengan ffmpeg nyata dan MENGHITUNG frame identik di file
keluaran. Itu pertanyaan yang sama dengan yang ditanyakan penonton.
"""
import hashlib
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, "/home/ubuntu/clipper")
import edit
import freeze_pick

TMP = tempfile.mkdtemp(prefix="v60_")
FPS = edit.FPS


def _src(path, seconds=12.0):
    """Klip uji dengan gerakan terus-menerus: frame beku jadi kentara."""
    # Butuh trek audio: renderer merujuk `0:a`, dan klip tanpa audio membuat
    # ffmpeg menolak SELURUH graph dengan pesan yang terlihat seperti bug
    # filter ("Stream specifier ':a' in filtergraph description").
    #
    # Frame diberi NOMOR dan sumbernya `testsrc` (bukan `testsrc2`): pola
    # testsrc2 berulang secara periodik, jadi ~175 frame dari 570 punya md5
    # kembar walaupun tidak ada beku sama sekali. Diukur pada kontrol telanjang
    # tanpa kode repo: testsrc2 -> deretan identik terpanjang 3 frame; testsrc
    # bernomor -> 211 frame, yang memang panjang loop-nya. Fixture yang salah
    # membuat instrumen melaporkan kerusakan yang tidak ada.
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc=size=1280x720:rate=%d:duration=%.1f" % (FPS, seconds),
         "-f", "lavfi", "-i",
         "sine=frequency=220:duration=%.1f" % seconds,
         "-shortest", "-vf",
         # Nomor frame harus di TENGAH. Di sudut (x=40:y=40) ia dibuang oleh
         # crop pillar, dan video uji jadi praktis statis: selisih antar-frame
         # median 0.0 pada 300 frame, sehingga tes membaca "beku 10,00s" pada
         # render yang tidak membekukan apa pun. Fixture harus bergerak DI
         # DAERAH YANG BERTAHAN setelah komposisi.
         "drawtext=text='%{n}':fontsize=240:fontcolor=white:"
         "box=1:boxcolor=black:x=(w-text_w)/2:y=(h-text_h)/2",
         "-pix_fmt", "yuv420p", "-crf", "0", "-c:a", "aac", path],
        check=True, capture_output=True)
    return path


def _frame_hashes(path):
    """Tanda tangan per frame yang TAHAN encoder lossy.

    md5 adalah instrumen yang salah di sini. Diukur pada kontrol telanjang:
    `loop` yang mengklon 210 frame menghasilkan 211 md5 identik ketika ditulis
    lossless (ffv1), tapi hanya 16 lewat libx264 crf20 — encoder memberi bit
    berbeda pada frame yang piksel-nya sama. Instrumen md5 akan melaporkan
    "beku 0,03s" pada render yang bekunya sempurna.

    Jadi frame dibandingkan lewat rata-rata selisih absolut piksel; nol-nyaris
    berarti gambar yang sama. Yang diukur adalah "gambarnya berhenti", bukan
    "byte-nya sama".
    """
    d = os.path.join(TMP, "fr")
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(d):
        os.unlink(os.path.join(d, f))
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", path, "-vsync", "0",
         os.path.join(d, "f%05d.png")], check=True, capture_output=True)
    import numpy as np
    from PIL import Image
    arrs = []
    for name in sorted(os.listdir(d)):
        im = Image.open(os.path.join(d, name)).convert("L")
        arrs.append(np.asarray(im, dtype=np.int16))
    return arrs


# Ambang selisih piksel rata-rata, DIKALIBRASI pada file nyata, bukan ditebak:
#   frame identik lewat x264 crf20 .............. 0.00 - 0.60
#   dua frame berbeda pada fixture ini .......... 8.29
#   frame beku dengan still vs tanpa still ...... 11.0
# 1.5 sempat dipakai dan membuat SELURUH 300 frame terbaca "sama" meski fixture
# bergerak — ambang yang longgar membuat tes melaporkan beku 10,00s pada render
# tanpa beku sama sekali. 3.0 duduk di tengah jurang 0.6 -> 8.29.
SAME = 3.0


def _longest_run(frames):
    """Deretan frame "gambar yang sama" terpanjang, dan di mana ia mulai."""
    import numpy as np
    best = best_at = run = 0
    at = 0
    for i, f in enumerate(frames):
        same = i and float(np.abs(f - frames[i - 1]).mean()) <= SAME
        if same:
            run += 1
        else:
            run, at = 1, i
        if run > best:
            best, best_at = run, at
    return best, best_at


# Simpan graph yang BENAR-BENAR dipakai tes ini. Membaca graph.txt dari
# temp_subs_* terbaru pernah menyesatkan: yang terbaru milik render produksi
# sebelumnya, bukan milik tes.
os.environ["CLIPPER_KEEP_TMP"] = "1"

src = _src(os.path.join(TMP, "src.mp4"))
words = [{"word": "satu", "start": 0.4, "end": 0.9},
         {"word": "dua", "start": 1.2, "end": 1.8},
         {"word": "tiga", "start": 2.4, "end": 3.0}]

# --- sifat 1: panjang beku di FILE, bukan di string ---
edit.OUTRO = "jamet"
edit.FLASH = False
# Matikan guncangan dan kedip: keduanya mengubah SETIAP frame beku, sehingga
# "deretan frame identik" terbaca 1 walaupun beku bekerja sempurna. Instrumen
# harus mengukur satu hal; goyangnya diukur terpisah oleh /tmp/dm.py.
edit.OUTRO_SHAKE_PX = 0
edit.SLAM_PX = 0
edit.FLASH_BURST = 0
# OUTRO_PUNCH_ZOOM juga hidup DI HILIR loop (`scale=...:eval=frame`), jadi ia
# menskalakan ulang setiap frame beku dan md5-nya berubah semua. Ditemukan
# dengan membaca graph yang benar-benar dipakai tes, bukan graph produksi
# terbaru di temp_subs_*. Tiga keluarga efek beroperasi pada beku: guncangan,
# kedip, dan zoom punch — semuanya harus mati agar instrumen mengukur SATU hal.
edit.OUTRO_PUNCH_ZOOM = 0.0
out = os.path.join(TMP, "plain.mp4")
edit.render_clip(src, 0.0, 10.0, words, out, bgm=False, frame_mode="pillar")
hashes = _frame_hashes(out)
run, at = _longest_run(hashes)
held = run / float(FPS)
print("tanpa still : %d frame total, deretan identik %d = %.2fs (mulai %.2fs)"
      % (len(hashes), run, held, at / float(FPS)))
assert held >= 4.5, "beku hanya %.2fs, harus ~5s" % held

# --- sifat 2: still pilihan yang muncul, beku tetap panjang ---
still = os.path.join(TMP, "still.png")
assert freeze_pick.render_still(src, 1.0, still), "still gagal dirender"
w, h = subprocess.run(
    ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
     "stream=width,height", "-of", "csv=p=0", still],
    capture_output=True, text=True).stdout.strip().split(",")
assert (int(w), int(h)) == (edit.CANVAS_W, edit.CANVAS_H), \
    "still %sx%s bukan kanvas" % (w, h)
print("still       : %sx%s, sesuai kanvas" % (w, h))

out2 = os.path.join(TMP, "still.mp4")
edit.render_clip(src, 0.0, 10.0, words, out2, bgm=False, frame_mode="pillar",
                 freeze_still=still)
h2 = _frame_hashes(out2)
run2, at2 = _longest_run(h2)
held2 = run2 / float(FPS)
print("dengan still: %d frame total, deretan identik %d = %.2fs (mulai %.2fs)"
      % (len(h2), run2, held2, at2 / float(FPS)))
assert held2 >= 4.5, "beku menyusut jadi %.2fs saat still dipakai" % held2

# Frame beku harus BERBEDA dari render tanpa still: itu bukti still-nya dipakai
# dan bukan no-op. Perbandingan md5 adalah detektor no-op yang sama dengan yang
# dipakai untuk menangkap "perbaikan" yang menghasilkan file byte-identik.
import numpy as _np
_delta = float(_np.abs(h2[at2] - hashes[at]).mean())
assert _delta > SAME, \
    ("frame beku sama dengan render tanpa still (selisih %.2f) — "
     "still tidak terpakai" % _delta)
print("frame beku berbeda dari render tanpa still, selisih %.1f" % _delta)
print("frame beku berubah saat still diberikan (bukan no-op)")

# --- sifat 3: panjang beku tidak bergantung pada still ---
assert abs(held2 - held) < 0.4, \
    "panjang beku berubah %.2f -> %.2f" % (held, held2)
print("panjang beku tidak terpengaruh pilihan frame")

print("\n_v60 ok — beku diukur di file keluaran, bukan di string filter")
