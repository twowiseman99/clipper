"""_v92: halaman "ga ada" wajib 404, TAPI yang ADA wajib tetep 200.

Versi pertama tes ini ditolak reviewer QA independen, dan tolakannya bener: dia
cuma punya kontrol NEGATIF (resource hilang -> 404). Mutation test QA buktiin
dua mutan yang MEMATIKAN APP lolos ijo:
  - q.get   -> selalu None  (SEMUA job jadi 404)      gate HIJAU  <- salah
  - camp.get-> selalu None  (SEMUA campaign jadi 404) gate HIJAU  <- salah
Sebab: ga pernah ada satu pun request ke resource yang BENERAN ADA, jadi gate
ga bisa bedain "404 buat yang hilang" dari "404 buat semuanya".

Versi ini nambah KONTROL POSITIF di dua handler yang diubah, plus isolasi
CLIPPER_CAMPAIGN_DB (dulu kelewat -> gate bisa nabrak campaigns.db repo nyata).
"""
import os
import sys
import tempfile
import base64

_tmp = tempfile.mkdtemp()
os.environ["CLIPPER_CONSOLE_USERS"] = "probe:probe-pass-123"
os.environ["CLIPPER_QUEUE_DB"] = os.path.join(_tmp, "q.sqlite")
os.environ["CLIPPER_CAMPAIGN_DB"] = os.path.join(_tmp, "camp.sqlite")
os.environ["CLIPPER_TOKEN_DIR"] = tempfile.mkdtemp()
os.environ["CLIPPER_BRIEF_OFFLINE"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import render_console as rc          # noqa: E402
import render_queue as q             # noqa: E402
import campaigns as camp            # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

AUTH = {"Authorization": "Basic " + base64.b64encode(
    b"probe:probe-pass-123").decode()}

ok, gagal = 0, []


def cek(nama, syarat):
    global ok
    if syarat:
        ok += 1
        print("  ok   %s" % nama)
    else:
        gagal.append(nama)
        print("  FAIL %s" % nama)


c = TestClient(rc.app)

# ---------------------------------------------------------------- positif
# Kontrol POSITIF: resource yang ADA wajib 200. Ini yang bunuh mutan
# "semua jadi 404" -- justru regresi paling mahal dan dulu ga dijaga.
print("== KONTROL POSITIF: resource yang ADA wajib 200 ==")
conn = q.connect()
job_id = q.submit(conn, "probe", "pr-politik", {"sumber": "probe"})
r = c.get("/job/%d" % job_id, headers=AUTH)
cek("job yang ADA (#%d) -> 200 (dapet %d)" % (job_id, r.status_code),
    r.status_code == 200)
cek("body job yang ADA ga bilang 'ga ada'", "ga ada</h1>" not in r.text)

cconn = camp.connect()
slug = None
try:
    camp.refresh(cconn, campaigns=[{
        "slug": "probe-camp", "nama": "Probe Camp", "cpm": 1000,
    }])
    slug = "probe-camp"
except Exception as e:                                    # pragma: no cover
    print("  (catat) camp.refresh nolak fixture: %s" % e)

if slug:
    r = c.get("/campaign/%s" % slug, headers=AUTH)
    cek("campaign yang ADA -> 200 (dapet %d)" % r.status_code,
        r.status_code == 200)
    cek("body campaign ADA ga bilang 'ga ada di papan'",
        "ga ada di papan" not in r.text)
else:
    gagal.append("fixture campaign gagal dibuat - kontrol positif campaign "
                 "TIDAK JALAN (jangan diamkan)")
    print("  FAIL fixture campaign gagal dibuat")

# ---------------------------------------------------------------- negatif
print("== resource ga ada -> 404 ==")
for jalur in ("/job/999999", "/campaign/ga-ada-slug-xyz", "/file/999999"):
    r = c.get(jalur, headers=AUTH)
    cek("%s -> 404 (dapet %d)" % (jalur, r.status_code),
        r.status_code == 404)

print("== halaman manusianya ga boleh ilang ==")
r = c.get("/job/999999", headers=AUTH)
cek("body /job masih bilang 'ga ada'", "ga ada" in r.text)
cek("body /job masih HTML penuh", "<!doctype html" in r.text.lower())
r = c.get("/campaign/ga-ada-slug-xyz", headers=AUTH)
cek("body /campaign masih bilang 'ga ada'", "ga ada" in r.text)

print("== kontrol negatif: auth menang di atas 404 ==")
for jalur in ("/job/999999", "/campaign/ga-ada-slug-xyz"):
    r = c.get(jalur)
    cek("%s tanpa auth -> 401 bukan 404" % jalur, r.status_code == 401)

print("== kontrol negatif: jalur normal ga keganggu ==")
for jalur in ("/", "/sehat"):
    r = c.get(jalur, headers=AUTH)
    cek("GET %s -> 200 (dapet %d)" % (jalur, r.status_code),
        r.status_code == 200)

print("== _halaman tetep kompatibel ke belakang ==")
import inspect                                            # noqa: E402
sig = inspect.signature(rc._halaman)
wajib = [n for n, p in sig.parameters.items()
         if p.default is inspect.Parameter.empty]
cek("_halaman arg wajib tetep 2 (dapet %d)" % len(wajib), len(wajib) == 2)
cek("_halaman(judul, isi) masih jalan tanpa status",
    rc._halaman("x", "<h1>y</h1>").status_code == 200)

print()
print("%d ok, %d gagal" % (ok, len(gagal)))
for g in gagal:
    print("  - %s" % g)
sys.exit(1 if gagal else 0)
