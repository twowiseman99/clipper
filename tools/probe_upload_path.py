#!/usr/bin/env python3
"""Ukur jalur upload YouTube sampai KE MANA sebelum mental.

Kenapa ini ada: "tombol upload nyala" BUKAN bukti jalur upload jalan. Ada
enam hal yang bisa rusak sebelum request nyampe Google -- library ga
kepasang, token ga kebaca, client gagal dibangun, body salah bentuk, file
video ga kebuka, jaringan ketutup. Kalau nunggu OAuth beres dulu buat
nyobain, enam-enamnya ketahuan belakangan, satu per satu.

Token dummy bikin kita bisa nyoba semuanya sekarang. Jawaban 401 dari
youtube.googleapis.com itu SUKSES buat tes ini: artinya request beneran
kekirim dan yang nolak adalah Google, bukan kode kita. Yang TIDAK diuji di
sini cuma izin akun -- itu bener-bener butuh OAuth.

Kontrol negatif wajib: tanpa token, jalurnya harus mental di tempat yang
BEDA (FileNotFoundError), bukan di API. Kalau dua-duanya gagal dengan error
yang sama, tes ini ga ngukur apa-apa.
"""
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import upload_youtube as uy  # noqa: E402

GAGAL = []


def cek(nama, syarat, detail=""):
    print(("ok   " if syarat else "GAGAL ") + nama + (f"  [{detail}]" if detail else ""))
    if not syarat:
        GAGAL.append(nama)


def video_contoh():
    """File video kecil tapi NYATA -- MediaFileUpload baca isinya."""
    out = "/tmp/probe_upload_contoh.mp4"
    if not os.path.exists(out):
        os.system("ffmpeg -y -v error -f lavfi -i testsrc2=size=320x240:rate=15 "
                  f"-t 1 -pix_fmt yuv420p {out} >/dev/null 2>&1")
    return out


print("=== 1. library kepasang & keimport ===")
try:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    import importlib.metadata as md
    cek("googleapiclient keimport", True, md.version("google-api-python-client"))
    cek("google-auth keimport", True, md.version("google-auth"))
    LIB = True
except Exception as e:
    cek("library Google keimport", False, f"{type(e).__name__}: {e}")
    LIB = False

print()
print("=== 2. token kebaca & client kebangun ===")
akun = uy.available_accounts()
cek("ada akun kedeteksi dari TOKEN_DIR", bool(akun), f"{uy.TOKEN_DIR} -> {akun}")

creds = None
if akun and LIB:
    try:
        creds = uy.load_credentials(akun[0])
        cek("load_credentials() balik objek credentials",
            creds is not None and hasattr(creds, "token"))
    except Exception as e:
        cek("load_credentials() jalan", False, f"{type(e).__name__}: {e}")

yt = None
if creds is not None:
    try:
        yt = build("youtube", "v3", credentials=creds)
        cek("build('youtube','v3') sukses bangun client", yt is not None)
        cek("client punya videos().insert", hasattr(yt.videos(), "insert"))
    except Exception as e:
        cek("build() sukses", False, f"{type(e).__name__}: {e}")

print()
print("=== 3. file video kebuka buat diupload ===")
vid = video_contoh()
cek("file video contoh ada", os.path.exists(vid),
    f"{os.path.getsize(vid) if os.path.exists(vid) else 0} byte")
if LIB and os.path.exists(vid):
    try:
        media = MediaFileUpload(vid, chunksize=-1, resumable=True)
        cek("MediaFileUpload baca ukuran file", media.size() > 0, f"{media.size()} byte")
    except Exception as e:
        cek("MediaFileUpload jalan", False, f"{type(e).__name__}: {e}")

print()
print("=== 4. REQUEST BENERAN KE API GOOGLE ===")
print("     (ditolak Google = SUKSES buat tes ini: yang nolak Google, bukan kode kita)")
kena_api = False
pesan = ""
keluar = []
if yt is not None:
    # Bukti yang dipakai: request HTTP yang BENERAN keluar, bukan jenis
    # exception-nya. Pelajaran dari putaran pertama tes ini -- gw baca
    # "RefreshError" dan nyimpulin jalurnya mental lokal, padahal POST ke
    # youtube.googleapis.com UDAH kekirim dan dijawab 401; library-nya yang
    # abis itu nyoba refresh token dan mental di situ. Nama exception terakhir
    # bukan tempat kejadian. Jadi sadap transport-nya.
    import httplib2
    _asli = httplib2.Http.request

    def _intip(self, uri, method="GET", *a, **k):
        keluar.append((method, uri.split("?")[0]))
        return _asli(self, uri, method, *a, **k)

    httplib2.Http.request = _intip
    conn = sqlite3.connect(":memory:")
    t0 = time.time()
    try:
        uy.upload(conn, vid,
                  {"title": "probe jalur upload", "description": "token dummy",
                   "youtube_tags": ["probe"]},
                  account=akun[0], schedule=False)
        cek("upload kelar (ga diduga pakai token dummy)", False,
            "token dummy TIDAK boleh sukses")
    except Exception as e:
        pesan = f"{type(e).__name__}: {e}"
    finally:
        httplib2.Http.request = _asli
    lamanya = time.time() - t0

    ke_yt = [u for m, u in keluar if "youtube.googleapis.com" in u]
    cek("ada request HTTP yang beneran keluar", bool(keluar), f"{len(keluar)} request")
    cek("request-nya nyampe youtube.googleapis.com", bool(ke_yt),
        ke_yt[0] if ke_yt else "nol")
    cek("metodenya POST ke endpoint upload videos",
        any(m == "POST" and "/videos" in u for m, u in keluar))
    cek("token dummy ditolak (upload TIDAK sukses)", bool(pesan), pesan[:90])
    cek("jawabannya datang dari jaringan, bukan instan",
        lamanya > 0.02, f"{lamanya:.2f}s")
    kena_api = bool(ke_yt)

print()
print("=== 5. KONTROL NEGATIF: tanpa token harus mental SEBELUM jaringan ===")
try:
    uy.load_credentials("akun-yang-ga-ada-tokennya")
    cek("tanpa token ditolak", False, "malah lolos")
except FileNotFoundError as e:
    cek("tanpa token mental di baca file, BUKAN di API", True, type(e).__name__)
    cek("dua kegagalan itu beda tempat (jadi tes ini ngukur sesuatu)",
        kena_api, "pakai token=request ke googleapis, tanpa token=FileNotFoundError")
except Exception as e:
    cek("tanpa token mental di baca file", False, f"{type(e).__name__}: {e}")

print()
print(f"  {len(GAGAL)} gagal" if GAGAL else "  semua lolos")
sys.exit(1 if GAGAL else 0)
