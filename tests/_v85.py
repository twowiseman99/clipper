#!/usr/bin/env python3
"""Panel upload: field keisi dari meta render, dan kolom meta ikut bermigrasi.

Dicek di sini, bukan di halaman hidup, supaya tes ini tetap jalan di box tanpa
console nyala. Yang dijaga SIFAT, bukan teks persisnya:

1. `meta` adalah kolom yang ditambah ke DB yang SUDAH terbentuk.
   `CREATE TABLE IF NOT EXISTS` tidak menambah kolom, jadi tanpa migrasi
   eksplisit setiap pembacaan `job["meta"]` di DB lama melempar
   OperationalError. Kontrolnya: bikin DB bergaya LAMA tanpa kolom itu,
   lalu buktikan connect() menambahkannya.

2. `finish()` menyimpan judul dan deskripsi. Ini hasil render yang sudah
   dibayar (job.py memanggil model untuk itu); sebelum ini worker
   membuangnya, jadi panel upload tidak punya apa pun untuk diisikan.

3. Panel upload merender field WALAUPUN tombolnya mati. Menyiapkan teks itu
   kerja yang berguna meski pengirimannya menunggu token OAuth operator.

4. Judul yang berisi HTML harus ter-escape. Judul datang dari model, jadi
   dia input yang tidak dipercaya.
"""
import json
import os
import re
import sqlite3
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

gagal = []


def cek(nama, syarat, detail=""):
    if syarat:
        print("ok   %s" % nama)
    else:
        print("FAIL %s %s" % (nama, detail))
        gagal.append(nama)


tmp = tempfile.mkdtemp(prefix="upload_panel_")

# ---------------------------------------------------------------- 1. migrasi
# DB bergaya LAMA: tabel jobs tanpa kolom meta.
lama = os.path.join(tmp, "lama.db")
conn = sqlite3.connect(lama)
conn.executescript("""
CREATE TABLE jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner       TEXT NOT NULL,
    preset      TEXT NOT NULL,
    params      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'waiting',
    stage       TEXT NOT NULL DEFAULT '',
    error       TEXT NOT NULL DEFAULT '',
    out_path    TEXT NOT NULL DEFAULT '',
    warnings    TEXT NOT NULL DEFAULT '[]',
    created_at  REAL NOT NULL,
    started_at  REAL,
    finished_at REAL
);
""")
conn.execute("INSERT INTO jobs (owner,preset,params,created_at) "
             "VALUES ('x','sedih','{}',1.0)")
conn.commit()
kolom_awal = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
conn.close()

cek("DB tiruan beneran belum punya kolom meta",
    "meta" not in kolom_awal, "kolom: %s" % sorted(kolom_awal))

import render_queue as q  # noqa: E402

conn = q.connect(lama)
kolom_baru = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
cek("connect() nambah kolom meta ke DB lama", "meta" in kolom_baru,
    "kolom: %s" % sorted(kolom_baru))
cek("job lama tetep kebaca abis migrasi", q.get(conn, 1) is not None)
cek("default meta '{}' bukan NULL", q.get(conn, 1)["meta"] == "{}",
    repr(q.get(conn, 1)["meta"]))

# Idempotent: connect berkali-kali tidak boleh meledak.
try:
    for _ in range(3):
        q.connect(lama)
    cek("migrasi idempotent (3x connect)", True)
except Exception as e:
    cek("migrasi idempotent (3x connect)", False, str(e))

# ------------------------------------------------------- 2. finish simpan meta
baru = os.path.join(tmp, "baru.db")
conn = q.connect(baru)
jid = q.submit(conn, "tes", "sedih", {"content": "x"})
meta_in = {"title": "Judul dari model", "description": "Deskripsi.",
           "mood": "emotional", "duration_sec": 81.0}
q.finish(conn, jid, "/tmp/palsu.mp4", ["satu catatan"], meta_in)
j = q.get(conn, jid)
meta_out = json.loads(j["meta"])

cek("finish() nyimpen title", meta_out.get("title") == meta_in["title"],
    repr(meta_out.get("title")))
cek("finish() nyimpen description",
    meta_out.get("description") == meta_in["description"])
cek("finish() ga ngerusak warnings",
    json.loads(j["warnings"]) == ["satu catatan"], j["warnings"])
cek("status tetep done", j["status"] == "done", j["status"])

# Kontrol negatif: finish TANPA meta tidak boleh bikin kolomnya rusak.
jid2 = q.submit(conn, "tes", "sedih", {"content": "y"})
q.finish(conn, jid2, "/tmp/palsu2.mp4", [])
cek("finish() tanpa meta -> '{}' bukan error",
    q.get(conn, jid2)["meta"] == "{}", repr(q.get(conn, jid2)["meta"]))

# --------------------------------------------------- 3. panel rendering field
os.environ.setdefault("CLIPPER_CONSOLE_USERS", "tes:tes")
import render_console as rc  # noqa: E402


class BarisPalsu(dict):
    """Baris sqlite tiruan: cukup mendukung j["kunci"]."""


def panel(meta):
    baris = BarisPalsu(id=7, meta=json.dumps(meta, ensure_ascii=False),
                       params="{}", status="done", out_path="/tmp/x.mp4")
    return rc._panel_upload(baris, 7)


html = panel({"title": "Judul Otomatis", "description": "Isi deskripsi."})
cek("panel punya form ke /upload", "action=/upload" in html)
cek("panel punya field judul", "name=judul" in html)
cek("panel punya field deskripsi", "name=deskripsi" in html)
cek("judul keisi dari meta", 'value="Judul Otomatis"' in html,
    html[:200])
cek("deskripsi keisi dari meta", "Isi deskripsi." in html)
cek("batas 100 karakter dipasang di input", "maxlength=100" in html)

# Tombol mati, tapi field TETAP ada. Ini sifat yang dijaga: nyiapin teks
# berguna walaupun pengiriman nunggu operator.
cek("tanpa akun OAuth tombolnya mati", "disabled" in html)
cek("tombol mati TAPI field tetep dirender",
    "name=judul" in html and "name=deskripsi" in html)
cek("alasan tombol mati disebut", "token" in html.lower())

# Render lama tanpa meta: kotak kosong harus DIJELASKAN, bukan didiemin.
kosong = panel({})
cek("meta kosong -> sebabnya dijelasin",
    "sebelum console nyimpen" in kosong, kosong[:300])
cek("meta kosong -> field masih ada", "name=judul" in kosong)

# -------------------------------------------------------------- 4. escaping
JAHAT = 'Dia bilang "stop" ' + "<" + "script>alert(1)" + "<" + "/script>"
nakal = panel({"title": JAHAT, "description": "a & b"})
cek("tag script ga kecetak mentah",
    "script>alert" not in nakal.replace("&lt;", "<").replace("&gt;", ">")
    or "&lt;script&gt;" in nakal,
    "escape gagal")
cek("kutip di judul di-escape jadi &quot;", "&quot;" in nakal)
cek("ampersand di-escape", "&amp;" in nakal)
raw = re.search(r'value="([^"]*)"', nakal)
# JEBAKAN yang ketangkep kontrol negatif (_v86): memeriksa isi tangkapan
# regex `value="([^"]*)"` TIDAK mengukur apa pun, karena saat escaping
# dimatikan regex itu berhenti di kutip mentah pertama dan hanya menangkap
# "Dia bilang " -- bersih, padahal HTML-nya sudah rusak. Yang benar:
# tuntut judul mentah TIDAK muncul apa adanya, dan bentuk ter-escape MUNCUL.
cek("judul mentah ga muncul apa adanya di HTML", JAHAT not in nakal)
cek("bentuk ter-escape yang muncul", "&lt;script&gt;" in nakal)
cek("value atribut ketangkep utuh (ga kepotong kutip mentah)",
    raw is not None and raw.group(1).endswith("&lt;/script&gt;"),
    raw.group(1) if raw else "ga ketemu")

print()
if gagal:
    print("GAGAL: %d" % len(gagal))
    for g in gagal:
        print("  - %s" % g)
    sys.exit(1)
print("semua lolos")
