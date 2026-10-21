"""render_console: halaman jujur, akses ketutup, kontrol mati berlabel.

Yang dijaga:
  - tanpa sandi = 401, ga ada jalan nembus
  - akun salah = 401
  - server NOLAK jalan kalau daftar akun kosong (biar ga kebuka diem-diem)
  - gambar outro di preset sedih = ditolak, bukan diem-diem dibuang
  - tombol upload ADA tapi disabled + labelnya jujur
  - halaman job nunjukin nomor urut + perkiraan, bukan spinner buta
  - GA ADA progress bar persen (job.py ga lapor persen)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

tmpdb = os.path.join(tempfile.mkdtemp(prefix="console_"), "q.db")
os.environ["CLIPPER_QUEUE_DB"] = tmpdb
os.environ["CLIPPER_CONSOLE_USERS"] = "dalmi:sandi1,oden:sandi2"

from fastapi.testclient import TestClient  # noqa: E402

import render_console as rc  # noqa: E402
import render_queue as q  # noqa: E402

c = TestClient(rc.app)
AUTH = ("dalmi", "sandi1")

# --- akses ketutup -----------------------------------------------------
r = c.get("/")
assert r.status_code == 401, "halaman kebuka tanpa sandi (dapet %d)" % r.status_code
assert "www-authenticate" in {k.lower() for k in r.headers}, \
    "401 tanpa header WWW-Authenticate, browser ga bakal nanya sandi"
print("tanpa sandi   : 401, bener")

r = c.get("/", auth=("dalmi", "salah"))
assert r.status_code == 401, "sandi salah tetep masuk"
r = c.get("/", auth=("hantu", "sandi1"))
assert r.status_code == 401, "user yang ga ada tetep masuk"
print("sandi salah   : 401, bener")

r = c.get("/", auth=AUTH)
assert r.status_code == 200, "akun bener ditolak (%d)" % r.status_code
print("akun bener    : 200")

# --- ga ada halaman pendaftaran ----------------------------------------
for jalan in ("/signup", "/daftar", "/register"):
    assert c.get(jalan, auth=AUTH).status_code == 404, \
        "%s ada padahal akun dibikin manual" % jalan
print("pendaftaran   : ga ada (404), sesuai keputusan operator")

# --- form nunjukin dua preset dengan nama yang dipake operator ---------
body = c.get("/", auth=AUTH).text
assert "Mengharukan" in body and "Jedag jedug" in body, \
    "nama preset yang dipake operator ga muncul di form"
assert 'name=content' in body and 'name=opening' in body, \
    "field link isi / link hook ga ada"
print("form          : dua preset + field link ada")

# --- gambar outro di preset sedih DITOLAK, ga diem-diem dibuang --------
r = c.post("/render", auth=AUTH, data={
    "preset": "sedih", "content": "https://x/y", "portrait": "/tmp/a.jpg"},
    follow_redirects=False)
assert r.status_code == 200, "ditolak harusnya balik ke form, bukan redirect"
assert "Jedag jedug" in r.text and "outro" in r.text.lower(), \
    "penolakan ga nyebut alasannya"
assert q.waiting_count(q.connect(tmpdb)) == 0, \
    "job tetep masuk antrean padahal parameternya salah"
print("outro+sedih   : ditolak dengan alasan, antrean tetep kosong")

# --- job yang bener masuk antrean + dapet nomor urut -------------------
r = c.post("/render", auth=AUTH, data={
    "preset": "jamet", "content": "https://x/pertama"}, follow_redirects=False)
assert r.status_code == 303, "submit ga redirect ke halaman job (%d)" % r.status_code
job1 = r.headers["location"]
assert job1.startswith("/job/"), "redirect ga ke halaman job: %s" % job1

r = c.post("/render", auth=AUTH, data={
    "preset": "jamet", "content": "https://x/kedua"}, follow_redirects=False)
job2 = r.headers["location"]

h = c.get(job2, auth=AUTH).text
assert "Nomor urut" in h, "orang kedua ga dikasih nomor urut"
assert "Perkiraan" in h, "orang kedua ga dikasih perkiraan nunggu"
# Yang dijaga: perkiraan nyebut DASARNYA, bukan angka tertentu.
#
# Versi lama ngunci "2,4 menit" atau "257" -- dan itu bikin tes ini nagih
# klaim BOHONG: 144 detik itu konstanta dari mesin lain (render nyata di box
# ini 481 dan 405 detik), dan "257 render" ga pernah ada di DB mana pun.
# Begitu angka karangan itu dibuang, tes ini merah padahal halamannya jadi
# lebih jujur. Tes jangan ngunci angka yang masih dituning (lihat _v87).
assert ("render yang kelar di box ini" in h
        or "belum cukup buat median" in h
        or "angka bawaan" in h), \
    "perkiraan ga nyebut dasarnya, jadi kelihatan karangan"
assert "257 render" not in h, "halaman ngaku punya 257 sampel yang ga ada"
print("antrean       : nomor urut + perkiraan + dasar angkanya muncul")

# --- GA ADA progress bar persen ----------------------------------------
for j in (job1, job2):
    t = c.get(j, auth=AUTH).text
    assert "<progress" not in t, "ada progress bar padahal job.py ga lapor persen"
    assert "%</" not in t, "ada angka persen yang ga punya sumber"
print("persen        : ga ada bar/angka persen, bener")

# --- tombol upload ADA tapi mati + labelnya jujur ----------------------
conn = q.connect(tmpdb)
jid = int(job1.rsplit("/", 1)[1])
q.claim(conn)
open(os.path.join(tempfile.mkdtemp(), "k.mp4"), "w").close()
palsu = os.path.join(tempfile.mkdtemp(), "hasil.mp4")
open(palsu, "w").write("x")
q.finish(conn, jid, palsu, ["contoh catatan render"])

t = c.get(job1, auth=AUTH).text
assert "disabled" in t, "tombol upload ga disabled padahal belum ada akun"
# R-26: tombol mati wajib nyebut SEBABNYA di labelnya. Yang dijaga properti
# itu, bukan kalimatnya -- versi lama ngunci "belum ada akun" sementara
# penjelasan di bawahnya nyebut file .pickle, dua model mental buat satu
# blocker. Sekarang satu kosakata: OAuth.
assert "OAuth" in t, "tombol mati tanpa label yang jujur (R-26)"
assert "nunggu OAuth" in t or "belum ada akun" in t, \
    "label tombol mati ga nyebut apa yang ditungguin"
assert "contoh catatan render" in t, "warnings dari render ga ditampilin"
print("upload        : tombol ada, disabled, labelnya nyebut sebabnya")
print("warnings      : catatan render ikut ditampilin")

# --- form fix: teks bebas + dua kolom waktu, semua optional ------------
assert 'name=catatan' in t and 'name=dari' in t and 'name=sampai' in t, \
    "form fix ga lengkap (butuh catatan + dari + sampai)"
assert "render ULANG penuh" in t or "render ulang penuh" in t.lower(), \
    "form fix ga bilang ini render ulang penuh"
print("form fix      : teks + rentang waktu + label jujur soal render ulang")

# --- fix bikin job BARU, ga nimpa yang lama ----------------------------
sebelum = len(q.recent(conn, limit=99))
r = c.post("/fix", auth=AUTH, data={"job_id": jid, "catatan": "b-roll ngaco",
                                    "dari": "1:20", "sampai": "1:45"},
           follow_redirects=False)
assert r.status_code == 303
sesudah = len(q.recent(conn, limit=99))
assert sesudah == sebelum + 1, "fix ga bikin job baru"
assert q.get(conn, jid)["status"] == "done", "fix ngerusak job lama"
print("fix           : bikin job baru, job lama tetep utuh")

# --- catatan fix nyampe ke perintah render -----------------------------
import render_worker as rw  # noqa: E402

baru = q.recent(conn, limit=1)[0]
cmd = rw._perintah(baru)
gabung = " ".join(cmd)
assert "b-roll ngaco" in gabung, "catatan revisi ga nyampe ke job.py"
assert "1:20" in gabung and "1:45" in gabung, "rentang waktu ga nyampe"
assert "--content" in cmd, "perintah render ga punya --content"
assert not any(";" in a or "&&" in a for a in cmd), \
    "ada metachar shell di argumen -- bahaya injeksi"
print("perintah      : catatan + rentang nyampe, argumen bersih")

# --- SETIAP flag harus beneran diterima job.py -------------------------
# Ini yang nangkep bug nyata: pekerja awalnya ngirim preset ke --copy-style,
# dan job.py nolak dengan "invalid choice: 'jamet'". Tesnya lolos, server
# jalan, 15 cek ijo -- yang ketahuan cuma karena pekerja nyata dijalanin.
# Jadi sekarang daftar pilihan dibaca dari argparse-nya job.py langsung.
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "job_mod", os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "job.py"))
jm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jm)
parser = None
try:
    import argparse  # noqa: E402

    # job.py bikin parser di dalam main(); ambil dengan nyuruh dia --help
    # ke buffer, lalu banding daftar pilihan dari CLIP_TYPES.
    sah_preset = set(jm.CLIP_TYPES)
except Exception as e:  # pragma: no cover
    raise AssertionError("ga bisa baca CLIP_TYPES dari job.py: %s" % e)

for nama in rc.PRESETS:
    assert nama in sah_preset, (
        "console nawarin preset %r tapi job.py cuma kenal %s -- render bakal "
        "gagal 'invalid choice'" % (nama, sorted(sah_preset)))
print("preset cocok  : %s, sama kayak CLIP_TYPES di job.py"
      % ", ".join(sorted(rc.PRESETS)))

# Dan flag yang dipakai pekerja harus ada di job.py, bukan tebakan.
pakai_flag = {a for a in cmd if a.startswith("--")}
sumber = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "job.py")).read()
for f in sorted(pakai_flag):
    assert '"%s"' % f in sumber, (
        "pekerja ngirim %s tapi job.py ga punya flag itu" % f)
print("flag cocok    : %s semua ada di job.py" % " ".join(sorted(pakai_flag)))

# --- JSON job.py dicetak RAPI: pekerja wajib bisa bacanya --------------
# Bug nyata: pekerja awalnya baca splitlines()[-1], dan karena job.py
# nyetak json.dumps(..., indent=2) baris terakhirnya cuma "}". Akibatnya
# render yang SUKSES (klip 32 MB beneran jadi) dilaporin GAGAL ke user.
# Tes ini ngasih bentuk output yang sama kayak aslinya.
class _Hasil:
    def __init__(self, stdout):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = 0


_mp4 = os.path.join(tempfile.mkdtemp(), "hasil.mp4")
open(_mp4, "w").write("x")

rapi = 'log baris biasa dulu\n' + __import__("json").dumps(
    {"ok": True, "file": _mp4, "warnings": ["catatan A"]}, indent=2)

conn_j = q.connect(tmpdb)
jj = q.submit(conn_j, "dalmi", "jamet", {"content": "https://x/y"})
q.claim(conn_j)

_asli = rw.subprocess.run
rw.subprocess.run = lambda *a, **k: _Hasil(rapi)
try:
    ok = rw.kerjakan(conn_j, q.get(conn_j, jj))
finally:
    rw.subprocess.run = _asli

assert ok is True, "JSON yang dicetak rapi (indent=2) dibaca sebagai gagal"
hasil_j = q.get(conn_j, jj)
assert hasil_j["status"] == "done", "status bukan done: %s" % hasil_j["status"]
assert hasil_j["out_path"] == _mp4, "path file ga kebaca dari JSON rapi"
assert "catatan A" in hasil_j["warnings"], "warnings ga keikut"
print("json rapi     : JSON multi-baris kebaca, render sukses ga dilaporin gagal")

# KONTROL: output yang BENERAN bukan JSON tetep harus dilaporin gagal.
jk = q.submit(conn_j, "dalmi", "jamet", {"content": "https://x/z"})
q.claim(conn_j)
rw.subprocess.run = lambda *a, **k: _Hasil("cuma log, ga ada json")
try:
    ok2 = rw.kerjakan(conn_j, q.get(conn_j, jk))
finally:
    rw.subprocess.run = _asli
assert ok2 is False, "output tanpa JSON diaku sukses"
assert q.get(conn_j, jk)["status"] == "failed"
print("kontrol json  : output tanpa JSON tetep gagal, bener")

# KONTROL: JSON bener tapi filenya ga ada = GAGAL, bukan sukses kosong.
jf = q.submit(conn_j, "dalmi", "jamet", {"content": "https://x/w"})
q.claim(conn_j)
rw.subprocess.run = lambda *a, **k: _Hasil(
    __import__("json").dumps({"ok": True, "file": "/tmp/ga-ada-%d.mp4" % os.getpid()}))
try:
    ok3 = rw.kerjakan(conn_j, q.get(conn_j, jf))
finally:
    rw.subprocess.run = _asli
assert ok3 is False, "job.py lapor file yang ga ada tapi diaku sukses"
print("kontrol file  : path yang ga ada dilaporin gagal, bener")

# --- file hasil cuma bisa diambil kalau login --------------------------
assert c.get("/file/%d" % jid).status_code == 401, "file kebuka tanpa sandi"
assert c.get("/file/%d" % jid, auth=AUTH).status_code == 200, \
    "file ga kebuka padahal udah login"
print("unduh file    : butuh login, bener")

# --- daftar akun kosong = server NOLAK jalan ---------------------------
import importlib  # noqa: E402

os.environ["CLIPPER_CONSOLE_USERS"] = ""
rc2 = importlib.reload(rc)
assert rc2.USERS == {}, "daftar akun kosong tapi USERS keisi"
r = TestClient(rc2.app).get("/")
assert r.status_code == 401, (
    "daftar akun kosong tapi halaman kebuka -- ini bikin console bisa "
    "nongol tanpa sandi gara-gara lupa set env")
print("akun kosong   : tetep 401, ga ada jalan kebuka tanpa sandi")

os.environ["CLIPPER_CONSOLE_USERS"] = "dalmi:sandi1,oden:sandi2"
importlib.reload(rc)

print("\n_v81 ok — console: akses ketutup, antrean jujur, kontrol mati "
      "berlabel, fix bikin job baru")
