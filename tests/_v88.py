#!/usr/bin/env python3
"""Kontrol negatif buat _v87: balikin tiap bug, _v87 WAJIB merah.

Tes yang belum pernah kebukti bisa gagal itu bukan tes — dan putaran ini
udah ngebuktiin sendiri: tiga cek pertama gua "lolos"/"gagal" bukan karena
halamannya, tapi karena gua ngegrep sumber. Tiap sabotase di sini balikin
SATU bug asli, dan _v87 harus nangkep.
"""
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "render_console.py")
QSRC = os.path.join(REPO, "render_queue.py")
V87 = os.path.join(REPO, "tests", "_v87.py")

# (nama, file, dari, ke) -- tiap entri satu bug yang beneran pernah ada.
SABOTASE = [
    ("field outro nyala terus + label nyalahin user",
     SRC,
     '  <label id=lbl-outro><span class=lab>Gambar outro (optional)</span>\n'
     '    <input type=file name=image accept="image/*" id=outro\n'
     '           aria-describedby=hint-outro>\n'
     '    <span class=hint id=hint-outro role=status></span></label>',
     '  <label><span class=lab>Gambar outro (optional) — cuma kepakai di '
     'Jedag jedug</span>\n'
     '    <input type=file name=image accept="image/*">\n'
     '    <span class=hint>Dikasih ke preset Mengharukan bakal ditolak '
     'job.py sendiri.</span></label>'),

    ("counter judul dicabut, balik ke label batas doang",
     SRC,
     '  <label><span class=lab>Judul <span class=hint id=sisa-judul></span>'
     '</span>\n    <input type=text name=judul maxlength=100 value="%s" '
     'id=judul></label>',
     '  <label><span class=lab>Judul (maks 100 karakter)</span>\n'
     '    <input type=text name=judul maxlength=100 value="%s"></label>'),

    ("median balik jadi konstanta beku (ngarang 257 sampel)",
     QSRC,
     '    d = sorted(r["lama"] for r in rows if r["lama"] and r["lama"] > 0)\n'
     '    if len(d) < minimal:\n'
     '        return MEDIAN_RENDER_SEC, len(d)',
     '    d = sorted(r["lama"] for r in rows if r["lama"] and r["lama"] > 0)\n'
     '    return MEDIAN_RENDER_SEC, 257'),
]


def jalan():
    p = subprocess.run([sys.executable, V87], capture_output=True, text=True,
                       cwd=REPO)
    gagal = [l.strip() for l in p.stdout.splitlines() if "FAIL" in l]
    return p.returncode, gagal


rc_code, _ = jalan()
if rc_code != 0:
    print("  SETUP SALAH: _v87 udah merah sebelum disabotase")
    sys.exit(1)
print("  baseline: _v87 ijo (exit 0)")

ok = fail = 0
for nama, path, dari, ke in SABOTASE:
    asli = open(path).read()
    if dari not in asli:
        print("  FAIL  pola sabotase ga ketemu: %s" % nama)
        fail += 1
        continue
    try:
        open(path, "w").write(asli.replace(dari, ke, 1))
        code, gagal = jalan()
        if code != 0:
            ok += 1
            print("  ok    kenangkep: %s" % nama)
            for g in gagal[:2]:
                print("          -> %s" % g)
        else:
            fail += 1
            print("  FAIL  LOLOS padahal disabotase: %s" % nama)
    finally:
        open(path, "w").write(asli)

code, _ = jalan()
print("  pulih: _v87 %s" % ("ijo" if code == 0 else "MASIH MERAH"))
if code != 0:
    fail += 1

print("\n  %d sabotase kenangkep, %d gagal" % (ok, fail))
sys.exit(1 if fail else 0)
