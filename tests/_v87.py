#!/usr/bin/env python3
"""Perbaikan UI putaran ini: outro ngikut preset, counter judul, median nyata.

Tiap cek di sini ada karena SATU hal yang kelihatan di screenshot halaman
hidup, bukan karena bagus di teori:

  1. Field "Gambar outro" dulu selalu nyala sambil labelnya nyuruh jangan
     dipakai -- kontrol yang nawarin aksi lalu nyalahin yang make.
  2. Label "maks 100 karakter" tanpa penunjuk posisi; YouTube motong judul
     kepanjangan tanpa ngasih tau.
  3. "median 2,4 menit dari 257 render": dua angka yang dua-duanya ga ada
     di box ini (konstanta mesin lain; DB cuma punya 2 render kelar).

Yang DIJAGA properti, bukan angka: tes ini sengaja ga ngunci 144 atau 443,
karena dua-duanya berubah sendiri begitu ada render baru.
"""
import json
import os
import re
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import render_console as rc  # noqa: E402
import render_queue as q  # noqa: E402

ok = fail = 0


def cek(nama, syarat, bukti=""):
    global ok, fail
    if syarat:
        ok += 1
        print("  ok   %s" % nama)
    else:
        fail += 1
        print("  FAIL %s" % nama)
        if bukti:
            print("       %s" % bukti)


# ---------------------------------------------------------------- outro
# PRESETS adalah satu-satunya sumber: kalau nanti ada preset ketiga, skrip
# halaman harus ikut sendiri tanpa disentuh.
html = rc._form("dalmi")

tabel = json.dumps({k: v["pakai_outro"] for k, v in q and rc.PRESETS.items()})
cek("tabel pakai_outro dikirim ke halaman, bukan nama preset dihardcode",
    tabel in html, "ga ketemu: %s" % tabel)

for nama, p in rc.PRESETS.items():
    cek("preset %r ada di tabel outro halaman" % nama,
        ('"%s":' % nama) in html)

cek("ada preset yang pakai outro (kalau nol, field itu mati permanen)",
    any(v["pakai_outro"] for v in rc.PRESETS.values()))
cek("ada preset yang NOLAK outro (kalau nol, skripnya ga ada guna)",
    any(not v["pakai_outro"] for v in rc.PRESETS.values()))

cek("field outro punya id yang dipegang skrip", 'id=outro' in html)
cek("hint outro punya id yang dipegang skrip", 'id=hint-outro' in html)
cek("select preset punya id yang dipegang skrip", 'id=preset' in html)

# Alasan field mati JANGAN cuma lewat warna: pembaca layar ga lihat redup.
cek("input outro nunjuk ke hint-nya buat pembaca layar",
    'aria-describedby=hint-outro' in html)
cek("hint outro diumumin waktu isinya ganti", 'role=status' in html)

# Label statis yang lama HARUS hilang: dia nyuruh user jangan pakai kontrol
# yang dia sendiri biarin nyala.
#
# JEBAKAN yang kena di putaran pertama: `grep` di SUMBER kena komentar yang
# nyeritain bug lama ("dulu nulis ... bakal ditolak job.py sendiri"), jadi
# tes merah padahal halamannya bener. Teks UI diukur di HTML yang DIKIRIM;
# sumber cuma dipakai buat hal yang ga punya jejak di halaman.
cek("label outro ga lagi nyalahin user di teks statis",
    "bakal ditolak job.py sendiri" not in html,
    "teks lama masih ada")

# Larangan server TETAP ada. JS itu lapis kejelasan, bukan lapis keamanan:
# POST bisa dateng tanpa halaman ini.
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "render_console.py")).read()
cek("server tetep nolak outro di preset yang salah (JS bukan satpam)",
    'pakai_outro' in src and 'Gambar outro cuma kepakai' in src)

# ---------------------------------------------------------------- counter
up = rc._panel_upload({"meta": "{}", "out_path": "/x.mp4"}, 5)
cek("judul punya id buat counter", 'id=judul' in up)
cek("counter punya wadah sendiri", 'id=sisa-judul' in up)
cek("maxlength 100 tetep dipasang (pagar keras, bukan cuma angka)",
    'maxlength=100' in up)
cek("label ga lagi cuma nulis batas tanpa posisi",
    "maks 100 karakter" not in up)

# Urutan: penjelasan kotak kosong harus DI ATAS field, bukan di bawah tombol.
i_asal = up.find("dibikin sebelum console nyimpen")
i_judul = up.find("name=judul")
cek("penjelasan kotak kosong muncul SEBELUM field judul",
    i_asal != -1 and i_judul != -1 and i_asal < i_judul,
    "asal=%d judul=%d" % (i_asal, i_judul))

# ---------------------------------------------------------------- median
db = tempfile.mkdtemp()
conn = sqlite3.connect(os.path.join(db, "t.db"))
conn.row_factory = sqlite3.Row
conn.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, status TEXT, "
             "started_at REAL, finished_at REAL)")

med, n = q.median_render_sec(conn)
cek("DB kosong -> jatuh ke konstanta, n=0",
    n == 0 and med == q.MEDIAN_RENDER_SEC, "med=%s n=%s" % (med, n))

for i, (s, f) in enumerate([(0, 100), (0, 200)], start=1):
    conn.execute("INSERT INTO jobs VALUES (?,'done',?,?)", (i, s, f))
med, n = q.median_render_sec(conn)
cek("2 sampel -> MASIH konstanta (median dari 2 render gampang kebawa satu "
    "video aneh)", n == 2 and med == q.MEDIAN_RENDER_SEC,
    "med=%s n=%s" % (med, n))

conn.execute("INSERT INTO jobs VALUES (3,'done',0,300)")
med, n = q.median_render_sec(conn)
cek("3 sampel -> pindah ke median NYATA", n == 3 and med == 200.0,
    "med=%s n=%s" % (med, n))

# Yang dijaga PROPERTI: median harus ngikut data, bukan sama dengan 200.
conn.execute("INSERT INTO jobs VALUES (4,'done',0,900)")
conn.execute("INSERT INTO jobs VALUES (5,'done',0,1000)")
med2, n2 = q.median_render_sec(conn)
cek("median naik waktu render lambat masuk (ngikut data, bukan angka beku)",
    med2 > med, "sebelum=%s sesudah=%s" % (med, med2))

# Job gagal/batal ga boleh keitung: durasinya bukan durasi kerja selesai.
conn.execute("INSERT INTO jobs VALUES (6,'failed',0,5)")
conn.execute("INSERT INTO jobs VALUES (7,'canceled',0,5)")
med3, n3 = q.median_render_sec(conn)
cek("job failed/canceled ga keitung di median", n3 == n2,
    "n sebelum=%s sesudah=%s" % (n2, n3))

# ---------------------------------------------------------------- kalimat
cek("n=0 nyebut angka bawaan, ga ngaku punya sampel",
    "bawaan" in rc._dasar_median(144.0, 0)
    and "render yang kelar" not in rc._dasar_median(144.0, 0))
cek("n=2 ngaku belum cukup", "belum cukup" in rc._dasar_median(144.0, 2))
cek("n=5 nyebut jumlah sampel NYATA",
    "5 render" in rc._dasar_median(443.0, 5))

# Klaim "257 render" dan "2,4 menit" diukur di HTML yang DIKIRIM, bukan di
# sumber: docstring yang nyeritain bug lama itu ga pernah nyampe browser,
# dan ngegrep sumber bikin tes merah buat halaman yang bener (kena di
# putaran pertama, tiga kali).
halaman = rc._form("dalmi") + rc._panel_upload(
    {"meta": "{}", "out_path": "/x.mp4"}, 5)
cek("klaim '257 render' ga ada di halaman yang dikirim",
    "257 render" not in halaman)
cek("angka median beku '2,4 menit' ga ada di halaman yang dikirim",
    "2,4 menit" not in halaman)
# Satu-satunya tempat angka itu boleh muncul: dihitung lewat _dasar_median.
cek("kalimat median dibikin _dasar_median, bukan ditulis tangan di halaman",
    "_dasar_median" in src)

print("\n  %d ok, %d gagal" % (ok, fail))
sys.exit(1 if fail else 0)
