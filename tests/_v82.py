"""autoclean: bersihin unduhan tanpa pernah nyentuh yang dipegang kode lain.

Yang dijaga di sini BUKAN angka GB-nya, tapi sifatnya:
  - DIEM pas ga ada yang perlu dibuang (cron yang nyetak tiap tick = spam)
  - file yang disebut file TES ga pernah kebuang
  - bukti bug yang disebut KNOWN_ISSUES ga pernah kebuang
  - fixture yang ke-commit ga pernah kebuang
  - audio + source + kode ga pernah kebuang
  - dry-run default: tanpa --apply, ga ada yang ilang
  - N klip terbaru disisain

Tes ini kerja di folder TIRUAN, bukan di repo asli -- tes yang ngehapus
file repo buat nguji penghapus itu cara baru buat ngulang bug yang sama.
"""
import os
import shutil
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import autoclean  # noqa: E402

# --- bikin repo tiruan -------------------------------------------------
tiruan = tempfile.mkdtemp(prefix="clean_")
os.makedirs(os.path.join(tiruan, "jobs"))
os.makedirs(os.path.join(tiruan, "media"))
os.makedirs(os.path.join(tiruan, "tests", "fixtures"))

TUA = time.time() - 48 * 3600


def tulis(rel, byte=1024, tua=True):
    p = os.path.join(tiruan, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(b"x" * byte)
    if tua:
        os.utime(p, (TUA, TUA))
    return p


# 8 klip, yang paling tua harusnya kebuang (sisain 5)
for i in range(8):
    p = tulis("jobs/clip_17910000%02d_1.mp4" % i, 2_000_000)
    os.utime(p, (TUA + i * 60, TUA + i * 60))

# b-roll ke-download: boleh kebuang
tulis("media/uDOWNLOAD01/video.mp4", 3_000_000)
tulis("media/uDOWNLOAD01/video.words.json", 5_000)

# fixture yang DIPAKAI TES: ga boleh kebuang
tulis("media/uFIXTURE01/penting.mp4", 1_000_000)
tulis("tests/fixtures/penting.words.json", 4_000)
with open(os.path.join(tiruan, "tests", "_v99.py"), "w") as f:
    f.write('P = "media/uFIXTURE01/penting.mp4"\n')

# bukti bug yang masih open: ga boleh kebuang
tulis("jobs/clip_BUKTI_9.mp4", 9_000_000)
tulis("jobs/clip_BUKTI_9.audit.json", 8_000)
with open(os.path.join(tiruan, "KNOWN_ISSUES.md"), "w") as f:
    f.write("clip : %s/jobs/clip_BUKTI_9.mp4\n" % tiruan)

# audio + kode: ga boleh kebuang
tulis("background_music/lagu.mp3", 5_000_000)
tulis("job.py", 50_000)

autoclean.BASE = tiruan
autoclean.MIN_UMUR_JAM = 24
autoclean.SISAIN_KLIP = 5
autoclean.LAPOR_MIN_MB = 1

# --- 1. dry-run GA BOLEH ngehapus apa pun ------------------------------
sebelum = set()
for dp, _d, fs in os.walk(tiruan):
    for f in fs:
        sebelum.add(os.path.join(dp, f))

n, mb, pesan = autoclean.jalan(apply=False)
sesudah = set()
for dp, _d, fs in os.walk(tiruan):
    for f in fs:
        sesudah.add(os.path.join(dp, f))
assert sebelum == sesudah, "dry-run ngehapus file! yang ilang: %s" % (
    sebelum - sesudah)
assert n > 0, "dry-run ga nemu kandidat sama sekali"
print("dry-run       : %d kandidat ketemu, NOL file kehapus" % n)

# --- 2. yang disebut tes / KNOWN_ISSUES masuk daftar jaga --------------
jaga = autoclean.daftar_jaga()
harus_jaga = [
    "media/uFIXTURE01/penting.mp4",
    "tests/fixtures/penting.words.json",
    "jobs/clip_BUKTI_9.mp4",
]
for rel in harus_jaga:
    p = os.path.join(tiruan, rel)
    aman = p in jaga or any(
        p.startswith(j.rstrip("/") + "/") or j.startswith(p.rstrip("/") + "/")
        for j in jaga)
    assert aman, "%s GA masuk daftar jaga" % rel
print("daftar jaga   : fixture + bukti bug kekenalin dari tes & KNOWN_ISSUES")

# --- 3. hapus beneran: yang boleh ilang, yang dijaga tetep ------------
n2, mb2, pesan2 = autoclean.jalan(apply=True)
assert n2 > 0, "apply ga hapus apa pun"


def ada(rel):
    return os.path.exists(os.path.join(tiruan, rel))


assert ada("media/uFIXTURE01/penting.mp4"), "FIXTURE KEHAPUS -- ini bug yang sama kayak _v65"
assert ada("tests/fixtures/penting.words.json"), "fixture ke-commit kehapus"
assert ada("jobs/clip_BUKTI_9.mp4"), "BUKTI BUG KEHAPUS"
assert ada("jobs/clip_BUKTI_9.audit.json"), "ledger bukti bug kehapus"
assert ada("background_music/lagu.mp3"), "AUDIO KEHAPUS -- operator bilang audio jangan"
assert ada("job.py"), "KODE KEHAPUS"
print("apply         : fixture, bukti bug, audio, kode semua MASIH ADA")

assert not ada("media/uDOWNLOAD01/video.mp4"), "b-roll unduhan ga kebuang"
print("apply         : b-roll unduhan kebuang, bener")

# --- 4. N klip terbaru disisain ---------------------------------------
import glob  # noqa: E402

sisa = sorted(glob.glob(os.path.join(tiruan, "jobs", "clip_17910000*.mp4")))
assert len(sisa) == 5, "harusnya sisa 5 klip terbaru, dapet %d" % len(sisa)
# yang disisain harus yang BARU, bukan sembarang 5. Nomornya diambil pakai
# regex, bukan potong indeks -- potong indeks pernah kena '3_' dan bikin
# tesnya gagal karena salah baca, bukan karena kodenya rusak.
import re as _re  # noqa: E402

nomor = sorted(int(_re.search(r"clip_1791000(\d+)_", os.path.basename(p)).group(1))
               for p in sisa)
assert nomor == [3, 4, 5, 6, 7], "yang disisain bukan yang terbaru: %s" % nomor
print("sisain klip   : 5 terbaru (nomor %s), 3 paling tua kebuang" % nomor)

# --- 5. DIEM pas udah bersih -----------------------------------------
n3, mb3, pesan3 = autoclean.jalan(apply=True)
assert pesan3 == "", "cron ngomong padahal ga ada yang dibuang -- ini spam"
print("tick kedua    : DIEM, ga ada yang dilaporin")

# --- 6. KONTROL: tanpa daftar jaga, fixture MESTINYA kebuang ----------
# Tanpa kontrol ini, "fixture aman" bisa cuma kebetulan.
tulis("media/uFIXTURE01/penting.mp4", 1_000_000)
_asli = autoclean.daftar_jaga
autoclean.daftar_jaga = lambda: set()
try:
    autoclean.jalan(apply=True)
finally:
    autoclean.daftar_jaga = _asli
assert not ada("media/uFIXTURE01/penting.mp4"), (
    "fixture ga kebuang bahkan tanpa daftar jaga -- berarti tes di atas ga "
    "ngebuktiin daftar jaganya kepakai")
print("kontrol       : tanpa daftar jaga fixture KEBUANG, jadi jaganya nyata")

shutil.rmtree(tiruan, ignore_errors=True)
print("\n_v82 ok — auto-clean: dry-run aman, daftar jaga dibaca dari kode, "
      "diem pas bersih")
