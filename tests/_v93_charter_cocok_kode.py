"""_v93: charter ga boleh ngeklaim veto yang kodenya ga punya.

Charter dulu nulis "Quality - decides whether it ships" + "VETO POINT. evidence,
or it does not ship". Diukur 22 Okt 2026: NOL jalur kode yang bikin verdict
kualitas jadi render gagal. Tiga `ok: False` di job.py semuanya exception
handler, ledger di-emit SETELAH result dirakit, dan upload_youtube.py ga pernah
baca ledger.

Operator mutusin nurunin bahasa charter (veto = tingkat ASET), BUKAN nambah exit
path. Jadi tes ini ngejaga dua arah:

  1. Charter wajib nyebut batasnya (asset-level, bukan ship-level).
  2. Kalau SUATU HARI kode dikasih exit path kualitas, tes ini MERAH — biar
     charter ikut diupdate di commit yang sama, bukan ketinggalan lagi.

Yang dijaga itu PROPERTI "dokumen cocok sama kode", bukan kata-kata tertentu.
"""
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

CHARTER = os.path.join(REPO, "docs", "ODEN_TAL_COMPANY.md")
JOB = os.path.join(REPO, "job.py")
UP = os.path.join(REPO, "upload_youtube.py")

ok, gagal = 0, []


def cek(nama, syarat):
    global ok
    if syarat:
        ok += 1
        print("  ok   %s" % nama)
    else:
        gagal.append(nama)
        print("  FAIL %s" % nama)


charter = open(CHARTER, encoding="utf-8").read()
job = open(JOB, encoding="utf-8").read()
up = open(UP, encoding="utf-8").read()

# ---------------------------------------------------------------- 1. kode
print("== apa yang kode BENERAN punya ==")

# Tiap `ok: False` di job.py: dia di dalam except, atau keputusan kualitas?
baris = job.splitlines()
idx_ok_false = [i for i, ln in enumerate(baris)
                if re.search(r'"ok":\s*False', ln)]
cek("ada >=1 `ok: False` di job.py (dapet %d)" % len(idx_ok_false),
    len(idx_ok_false) >= 1)

# Cari ke atas maks 12 baris: ini except, validasi argumen, atau keputusan
# kualitas? CATATAN KOREKSI (22 Okt 2026): catatan pertama gw nulis "ketiganya
# except" — SALAH, dan tes ini yang nangkep. Baris ~1547 itu validasi argumen
# CLI ("--content is required"), bukan except. Yang bener dijaga bukan "semua
# except", tapi NOL yang didorong keputusan kualitas.
dari_except, dari_argumen, dari_kualitas = 0, 0, 0
for i in idx_ok_false:
    teks = "\n".join(baris[max(0, i - 12):i])
    if re.search(r"^\s*except\b", teks, re.M):
        dari_except += 1
    elif re.search(r"add_argument|parse_args|is required", teks):
        dari_argumen += 1
    if re.search(r"\b(led|ledger)\.(counts|rejected)\b|audit\.(counts|rejected)",
                 teks):
        dari_kualitas += 1

cek("tiap `ok: False` kekelompokin (except %d + argumen %d = %d)"
    % (dari_except, dari_argumen, len(idx_ok_false)),
    dari_except + dari_argumen == len(idx_ok_false))
cek("NOL `ok: False` yang didorong keputusan kualitas (dapet %d)"
    % dari_kualitas, dari_kualitas == 0)

# upload ga pernah nanya ledger
cek("upload_youtube.py ga baca audit/ledger",
    not re.search(r"\baudit\b|\bledger\b", up))

# ledger di-emit SETELAH result dirakit -> ga bisa ngubah hasil
pos_result = job.find('"elapsed_sec"')
pos_emit = job.find("led.emit(")
cek("led.emit() ada SETELAH result dirakit (%d > %d)" % (pos_emit, pos_result),
    pos_emit > pos_result > 0)

# ---------------------------------------------------------------- 2. charter
print("== charter ga boleh ngeklaim lebih dari itu ==")

cek("charter nyebut veto itu tingkat ASET",
    re.search(r"ASSET", charter) is not None)
cek("charter nyatakan EKSPLISIT veto ga nahan clip ship",
    re.search(r"does NOT stop a clip from shipping", charter) is not None)
cek("charter nyebut warnings[] sebagai jejak rejection",
    "warnings[]" in charter)
cek("charter nunjuk jalur kode kalau trade-off diubah",
    "led.counts()" in charter)

# Klaim lama yang KEBLABASAN ga boleh balik
for frasa in ("decides whether it ships",
              "VETO POINT. evidence, or it does not ship"):
    cek("klaim keblabasan ga ada lagi: %r" % frasa, frasa not in charter)

# ---------------------------------------------------------- 3. dua arah
print("== kontrol: kalau kode DIKASIH exit path, tes ini wajib MERAH ==")
# Simulasi: kode punya `ok: False` yang didorong led.counts() di luar except.
palsu = (
    'def ship(led):\n'
    '    ok_, no_, warn_ = led.counts()\n'
    '    if no_:\n'
    '        return {"ok": False, "error": "quality"}\n'
)
baris_palsu = palsu.splitlines()
i_palsu = [i for i, ln in enumerate(baris_palsu)
           if re.search(r'"ok":\s*False', ln)][0]
konteks_palsu = "\n".join(baris_palsu[max(0, i_palsu - 12):i_palsu])
cek("detektor nangkep exit path kualitas di kode TIRUAN",
    re.search(r"\bled\.(counts|rejected)\b", konteks_palsu) is not None)
cek("detektor ga nyangka itu except",
    not re.search(r"^\s*except\b", konteks_palsu, re.M))

print()
print("%d ok, %d gagal" % (ok, len(gagal)))
for g in gagal:
    print("  - %s" % g)
if gagal:
    sys.exit(1)
print("_v93.py OK — charter cocok sama jalur kode yang bener-bener ada: "
      "veto tingkat aset nyata, veto tingkat ship ga ada, dan kalau kode "
      "dikasih exit path kualitas tes ini bakal merah biar charter ikut "
      "diupdate")
