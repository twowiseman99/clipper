#!/usr/bin/env python3
"""Gate: jalur upload YouTube nyampe API, dan UI-nya jujur soal apa yang kurang.

Kenapa gate ini ada: "tombol upload nyala" bukan bukti apa-apa. Diukur 21 Okt
2026, library Google (google-api-python-client dkk) KE-LIST di
requirements.txt tapi GA KEPASANG di .venv -- dan upload_youtube ke-import
di dalam try/except yang ngubah ImportError jadi daftar akun KOSONG. Jadi
library ilang dan token ilang kelihatan SAMA PERSIS di UI: "nunggu OAuth
operator". Operator bisa ngurus OAuth berhari-hari sementara yang kurang
sebenernya satu perintah install.

Yang dijaga di sini:
  1. library Google beneran keimport (bukan ketelen except)
  2. token kebaca -> client kebangun -> POST nyampe youtube.googleapis.com
  3. kondisi "library ilang" dan "token ilang" BEDA pesannya
"""
import glob
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GAGAL = []


def cek(nama, syarat, detail=""):
    print(("ok   " if syarat else "GAGAL ") + nama + (f"  [{detail}]" if detail else ""))
    if not syarat:
        GAGAL.append(nama)


# ---------------------------------------------------------------- library
# Diuji pakai import TELANJANG, sengaja di luar try: kalau paketnya ilang,
# gate ini harus MATI berisik. preflight.upload_accounts() nelen ImportError
# jadi [] -- itu bener buat UI, tapi bikin gate buta kalau ikut dipakai.
import importlib.metadata as md  # noqa: E402

for paket, modul in (("google-api-python-client", "googleapiclient.discovery"),
                     ("google-auth", "google.auth.transport.requests"),
                     ("google-auth-oauthlib", "google_auth_oauthlib.flow")):
    try:
        __import__(modul)
        cek(f"{paket} kepasang & keimport", True, md.version(paket))
    except Exception as e:
        cek(f"{paket} kepasang & keimport", False, f"{type(e).__name__}: {e}")

# Paket yang kepake wajib kecatet di requirements, biar box berikutnya ga
# kena jebakan yang sama.
req = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "requirements.txt")).read()
for paket in ("google-api-python-client", "google-auth", "google-auth-oauthlib"):
    cek(f"{paket} kecatet di requirements.txt", paket in req)

import upload_youtube as uy  # noqa: E402

# ---------------------------------------------------------------- jalur API
akun = uy.available_accounts()
cek("TOKEN_DIR kebaca", bool(uy.TOKEN_DIR), uy.TOKEN_DIR)

if akun:
    import httplib2
    from googleapiclient.discovery import build

    creds = uy.load_credentials(akun[0])
    cek("load_credentials() balik credentials", hasattr(creds, "token"))
    yt = build("youtube", "v3", credentials=creds)
    cek("build('youtube','v3') bangun client", yt is not None)

    # Bukti = request yang BENERAN keluar, bukan jenis exception-nya. Putaran
    # pertama probe ini salah baca: exception terakhir "RefreshError" bikin gw
    # nyimpulin jalurnya mental lokal, padahal POST ke youtube.googleapis.com
    # udah kekirim dan dijawab 401; library-nya yang abis itu nyoba refresh dan
    # mental di situ. Nama exception terakhir BUKAN tempat kejadian.
    keluar = []
    _asli = httplib2.Http.request

    def _intip(self, uri, method="GET", *a, **k):
        keluar.append((method, uri.split("?")[0]))
        return _asli(self, uri, method, *a, **k)

    vid = "/tmp/_gate_upload_contoh.mp4"
    if not os.path.exists(vid):
        os.system("ffmpeg -y -v error -f lavfi -i testsrc2=size=320x240:rate=15 "
                  f"-t 1 -pix_fmt yuv420p {vid} >/dev/null 2>&1")

    httplib2.Http.request = _intip
    try:
        uy.upload(sqlite3.connect(":memory:"), vid,
                  {"title": "gate", "description": "gate", "youtube_tags": []},
                  account=akun[0], schedule=False)
        sukses = True
    except Exception:
        sukses = False
    finally:
        httplib2.Http.request = _asli

    ke_yt = [u for m, u in keluar if "youtube.googleapis.com" in u]
    cek("POST nyampe youtube.googleapis.com", bool(ke_yt), ke_yt[0] if ke_yt else "nol")
    cek("endpoint-nya /videos (insert), bukan rute lain",
        any("/videos" in u for _, u in keluar))
    if akun[0] == "dummy":
        cek("token dummy TIDAK berhasil upload", not sukses,
            "kalau ini sukses, berarti token dummy-nya nyata")
else:
    cek("ada token buat nguji jalur API", False,
        f"nol token_*.pickle di {uy.TOKEN_DIR} — jalan tools/token_dummy.py dulu")

# -------------------------------------------- library ilang != token ilang
# Dua sebab beda wajib kebaca beda. Diukur dengan nyembunyiin modulnya.
import preflight  # noqa: E402

asli_akun = uy.available_accounts()
tanpa_token = []
_glob_asli = glob.glob
try:
    glob.glob = lambda *a, **k: []
    tanpa_token = uy.available_accounts()
finally:
    glob.glob = _glob_asli

cek("tanpa token: daftar akun kosong", tanpa_token == [])
cek("dengan token: daftar akun ga kosong", bool(asli_akun), str(asli_akun))
cek("dua kondisi itu beda hasilnya (jadi gate ini ngukur sesuatu)",
    tanpa_token != asli_akun)
cek("preflight.upload_accounts() ga meledak pas kosong",
    isinstance(preflight.upload_accounts(), list))

# upload_blocker() wajib MISAHIN dua sebab itu, karena dua-duanya butuh
# tindakan dari orang yang beda. Yang dijaga: jawabannya beda, bukan
# kalimatnya persis apa.
cek("upload_blocker() bilang None pas semuanya beres",
    preflight.upload_blocker() is None, str(preflight.upload_blocker()))

tanpa_tok_blocker = None
_glob_asli = glob.glob
try:
    glob.glob = lambda *a, **k: []
    tanpa_tok_blocker = preflight.upload_blocker()
finally:
    glob.glob = _glob_asli
cek("tanpa token: blocker-nya 'token'",
    tanpa_tok_blocker and tanpa_tok_blocker[0] == "token", str(tanpa_tok_blocker))

# Library disembunyiin: dicek lewat subprocess, karena modul yang udah
# keimport di proses ini ga bisa dibikin ilang dengan jujur.
import subprocess  # noqa: E402
import tempfile  # noqa: E402

sab = tempfile.mkdtemp()
with open(os.path.join(sab, "googleapiclient.py"), "w") as f:
    f.write('raise ImportError("disembunyiin buat kontrol negatif")\n')
env = dict(os.environ, PYTHONPATH=sab)
out = subprocess.run(
    [sys.executable, "-c",
     "import preflight; print(preflight.upload_blocker())"],
    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    env=env, capture_output=True, text=True).stdout.strip()
cek("library disembunyiin: blocker-nya 'library', BUKAN 'token'",
    "'library'" in out and "'token'" not in out, out[:110])
cek("jadi dua sebab itu ga pernah kebaca sama", "'library'" in out
    and tanpa_tok_blocker and tanpa_tok_blocker[0] == "token")

# Dan yang bikin cek ini sempat bohong: upload_youtube import googleapiclient
# DI DALAM fungsi, jadi `import upload_youtube` sukses walau library ilang.
# Versi pertama upload_blocker() nanya itu dan jawab None -- buta total.
out2 = subprocess.run(
    [sys.executable, "-c", "import upload_youtube; print('keimport')"],
    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    env=env, capture_output=True, text=True).stdout.strip()
cek("upload_youtube TETEP keimport walau library ilang (sebab jebakannya)",
    out2 == "keimport",
    "makanya cek library wajib import googleapiclient langsung")

print()
print(f"  {len(GAGAL)} gagal" if GAGAL else f"  {len(GAGAL) or 'semua'} lolos")
sys.exit(1 if GAGAL else 0)
