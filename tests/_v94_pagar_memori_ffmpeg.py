import os
import re
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFGUARD = os.path.join(BASE, "scripts", "ffguard.sh")
SHIM = os.path.join(BASE, "scripts", "ffmpeg_guarded.sh")
PATHSHIM = os.path.join(BASE, "scripts", "shim", "ffmpeg")
SCRIPTS = os.path.expanduser("~/.hermes/scripts")
ok = 0


def cek(nama, cond, rinci=""):
    global ok
    assert cond, f"{nama} GAGAL {rinci}"
    ok += 1


# --- 1. ketiga pagar ada dan bisa dieksekusi -------------------------------
for p in (FFGUARD, SHIM, PATHSHIM):
    cek(f"ada {os.path.basename(p)}", os.path.exists(p), p)
    cek(f"executable {os.path.basename(p)}", os.access(p, os.X_OK), p)

ff = open(FFGUARD, encoding="utf-8").read()

# --- 2. batas memori betul-betul dipasang ----------------------------------
cek("MemoryMax dipasang", "MemoryMax" in ff)
cek("MemorySwapMax=0 dipasang", "MemorySwapMax=0" in ff,
    "tanpa ini box swap-thrash dulu sebelum ffmpeg mati, dan ITU yang "
    "bikin SSH ga bisa masuk")
cek("systemd-run --scope", "systemd-run" in ff and "--scope" in ff)

# --- 3. NOL suntikan argumen secara default -------------------------------
m = re.search(r"^THREADS=\$\{FFGUARD_THREADS(.-?)\}", ff, re.M)
cek("THREADS default KOSONG", bool(m) and ":-2" not in (m.group(0) if m else ""),
    "diukur 23 Okt: `-threads 2` yang disuntik menggeser bit keluaran; "
    "operator minta hasil render tidak berubah")
cek("suntikan dijaga -n THREADS", '[ -n "$THREADS" ]' in ff)

# --- 4. ketiga job render memakai pagar -----------------------------------
for nama in ("clipper_render_tick.sh", "bio1_render_broll.sh",
             "stockstory_scene_filler.sh"):
    p = os.path.join(SCRIPTS, nama)
    if not os.path.exists(p):
        continue
    isi = open(p, encoding="utf-8").read()
    pakai = ("CLIPPER_FFMPEG" in isi or "scripts/shim" in isi
             or "ffguard" in isi)
    cek(f"{nama} lewat pagar", pakai,
        "job render tanpa pagar = satu ffmpeg bisa menarik gateway mati lagi")
    cek(f"{nama} tidak menyuntik threads",
        "export FFGUARD_THREADS=" not in isi,
        "menyetel ini mengubah bit keluaran render")

print(f"_v94 bagian statis ok ({ok} cek)")
# --- 5. PAGAR BENERAN MEMOTONG, bukan cuma tertulis ------------------------
# Gate yang cuma membaca string tidak membuktikan apa pun. Diukur 22 Okt pada
# masalah lain: tes yang assert STRING filter lolos sementara ffmpeg menolak
# graph-nya. Jadi pagar ini harus DIJALANKAN.
#
# Kontrol dua arah di satu gate:
#   A batas kecil + kerja besar  -> WAJIB dibunuh (rc 137) dan tercatat
#   B batas wajar + kerja kecil  -> WAJIB sukses  (rc 0)
# Tanpa B, gate ini puas oleh pagar yang membunuh SEMUANYA.
if os.environ.get("CLIPPER_SKIP_FFGUARD_RUN"):
    print("_v94 bagian jalan DILEWATI (CLIPPER_SKIP_FFGUARD_RUN)")
    sys.exit(0)

tmp = tempfile.mkdtemp(prefix="_v94_")
log = os.path.join(tmp, "ffguard.log")
env = dict(os.environ, FFGUARD_LOG=log,
           FFGUARD_LOCK=os.path.join(tmp, "lock"))
env.pop("FFGUARD_THREADS", None)


def jalan(args, memmax):
    e = dict(env, FFGUARD_MEMMAX=memmax)
    r = subprocess.run([FFGUARD] + args, capture_output=True, text=True,
                       timeout=300, env=e)
    return r


# ARAH A: 200M melawan skala 4K -- harus kena batas.
besar = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc2=size=1920x1080:rate=30:duration=20",
         "-vf", "scale=3840:2160:flags=lanczos",
         "-c:v", "libx264", "-preset", "slow",
         os.path.join(tmp, "a.mp4")]
ra = jalan(besar, "200M")
cek("A pagar membunuh kerja besar", ra.returncode != 0,
    f"rc={ra.returncode} -- pagar tidak memotong, itu bukan pagar")
cek("A sebabnya DILAPORKAN", "DIBUNUH" in ra.stderr or "DIBUNUH" in
    (open(log, encoding="utf-8").read() if os.path.exists(log) else ""),
    "ffmpeg mati tanpa sebab tercatat = kegagalan yang tidak bisa dibaca")

# ARAH B: batas wajar, kerja kecil -- harus sukses.
kecil = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
         "testsrc2=size=320x240:rate=25:duration=1",
         "-c:v", "libx264", "-preset", "ultrafast",
         os.path.join(tmp, "b.mp4")]
rb = jalan(kecil, "2G")
cek("B kerja kecil TETAP sukses", rb.returncode == 0,
    f"rc={rb.returncode} stderr={rb.stderr[-200:]} -- pagar yang membunuh "
    "semuanya akan melewatkan arah A juga")
cek("B keluaran benar-benar ditulis",
    os.path.exists(os.path.join(tmp, "b.mp4"))
    and os.path.getsize(os.path.join(tmp, "b.mp4")) > 1000)

# ARAH C: probe `ffmpeg -i FILE` rc=1 itu NORMAL, bukan kegagalan.
# Logger pertama menulis tanda silang untuk panggilan ini dan membuat log
# render sehat penuh kegagalan palsu. Satu tanda silang palsu merusak nilai
# seluruh log.
rc_probe = jalan(["ffmpeg", "-i", os.path.join(tmp, "b.mp4")], "2G")
isi = open(log, encoding="utf-8").read()
cek("C probe tidak dicap gagal", "probe rc=1" in isi,
    f"log:\n{isi[-400:]}")

# ARAH D: argumen render TIDAK disentuh (tanpa FFGUARD_THREADS).
cek("D nol -threads disuntik", "-threads" not in isi,
    f"pagar menyuntik argumen; itu menggeser bit keluaran. log:\n{isi[-400:]}")

import shutil
shutil.rmtree(tmp, ignore_errors=True)
print(f"_v94_pagar_memori_ffmpeg.py OK -- {ok} cek; pagar memotong (rc "
      f"{ra.returncode}), kerja sah tetap lolos, probe tidak dicap gagal, "
      f"nol argumen render disentuh")
