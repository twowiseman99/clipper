"""_v83: papan campaign + upload aset di console, dites lewat HTTP.

Yang dijaga di sini BUKAN "halamannya kebuka". Tiga hal yang bisa diem-diem
rusak dan bikin kerugian nyata:

1. **Form ga boleh bisa nunjuk file sembarangan di server.** Dropdown BGM dan
   gambar outro ngirim PATH, bukan file. POST bisa dibikin tangan. Tanpa
   pagar, `bgm_file=/etc/passwd` bikin pekerja nempelin file itu ke render.
   Dites dengan POST tangan, bukan lewat tombol.

2. **Nama file upload ga boleh keluar dari folder aset.** `../../job.py`
   sebagai nama file bakal nimpa kode kalau namanya dipakai apa adanya.

3. **Urutan papan ga boleh CPM mentah.** Campaign Rp15.000 dengan sisa budget
   6% harus kalah dari Rp10.000 sisa 97%; itu seluruh alasan papan ini ada.

Dijalanin pakai server sungguhan di port acak + DB sementara, jadi tes ini ga
nyentuh queue.db atau campaigns.db yang dipakai operator.
"""
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(BASE, ".venv", "bin", "python")
USER, PASS = "tes", "sandi-tes"


def _port_bebas():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _auth():
    import base64
    return "Basic " + base64.b64encode(
        ("%s:%s" % (USER, PASS)).encode()).decode()


def _req(url, data=None, headers=None, method=None):
    h = {"Authorization": _auth()}
    h.update(headers or {})
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _form(url, fields):
    body = "&".join("%s=%s" % (k, urllib.request.quote(str(v)))
                    for k, v in fields.items()).encode()
    return _req(url, data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"})


def _multipart(url, fields, files):
    """files: [(name, filename, bytes)]"""
    b = "----tes%d" % time.time()
    buf = io.BytesIO()
    for k, v in fields.items():
        buf.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n"
                   "%s\r\n" % (b, k, v)).encode())
    for name, fn, data in files:
        buf.write(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; "
                   "filename=\"%s\"\r\nContent-Type: application/octet-stream"
                   "\r\n\r\n" % (b, name, fn)).encode())
        buf.write(data)
        buf.write(b"\r\n")
    buf.write(("--%s--\r\n" % b).encode())
    return _req(url, data=buf.getvalue(),
                headers={"Content-Type": "multipart/form-data; boundary=%s" % b})


def main():
    import campaigns as camp

    tmp = tempfile.mkdtemp(prefix="v83_")
    aset_dir = os.path.join(tmp, "aset")
    port = _port_bebas()
    env = dict(os.environ)
    env.update({
        "CLIPPER_CONSOLE_USERS": "%s:%s" % (USER, PASS),
        "CLIPPER_CONSOLE_PORT": str(port),
        "CLIPPER_QUEUE_DB": os.path.join(tmp, "queue.db"),
        "CLIPPER_CAMPAIGN_DB": os.path.join(tmp, "campaigns.db"),
        "CLIPPER_CAMPAIGN_ASSETS": aset_dir,
        "PYTHONPATH": BASE,
    })

    # Papan diisi dari data, bukan dari jaringan: tes ga boleh gantung ke
    # marketplace yang bisa down.
    conn = camp.connect(env["CLIPPER_CAMPAIGN_DB"])
    camp.refresh(conn, [
        {"slug": "krakatau", "id": "1", "title": "Krakatau", "brand": "KRK",
         "status": "active", "cpm_tiktok": 15000,
         "budget_bar_percent_override": 6, "min_views": 20000,
         "min_video_duration": 30, "platform": ["tiktok"],
         "description": "brief krakatau", "hashtags": ["krakatau"]},
        {"slug": "karomah-insani", "id": "2", "title": "Karomah Insani",
         "brand": "KI", "status": "active", "cpm_tiktok": 10000,
         "budget_bar_percent_override": 97, "min_views": 10000,
         "min_video_duration": 60, "platform": ["tiktok", "instagram"],
         "description": "brief karomah", "hashtags": ["karomah"]},
    ])

    proc = subprocess.Popen([PY, os.path.join(BASE, "render_console.py")],
                            env=env, cwd=BASE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = "http://127.0.0.1:%d" % port
    try:
        for _ in range(60):
            try:
                if _req(url + "/sehat")[0] == 200:
                    break
            except Exception:
                pass
            if proc.poll() is not None:
                print(proc.stdout.read().decode("utf-8", "replace"))
                raise AssertionError("console mati sebelum siap")
            time.sleep(0.4)
        else:
            raise AssertionError("console ga pernah siap di %s" % url)

        # --- 1. Tanpa sandi: 401, dan isi papan GA BOLEH kebocor ------------
        r = urllib.request.Request(url + "/campaign")
        try:
            urllib.request.urlopen(r, timeout=10)
            raise AssertionError("papan kebuka tanpa sandi")
        except urllib.error.HTTPError as e:
            assert e.code == 401, e.code
            assert "Karomah" not in e.read().decode("utf-8", "replace")

        # --- 2. Urutan papan: SKOR, bukan CPM mentah ------------------------
        kode, html = _req(url + "/campaign")
        assert kode == 200, kode
        i_kar = html.index("karomah-insani")
        i_kra = html.index("krakatau")
        assert i_kar < i_kra, ("CPM 15rb sisa 6% nongol di atas CPM 10rb "
                              "sisa 97% — papannya balik ke CPM mentah")
        # Header kolom wajib bilang PER SERIBU. Nulis "CPM" doang = ngundang
        # salah hitung 1000x.
        assert "1.000 views" in html, "header kolom ga nyebut per 1.000 views"
        # min_views 20.000 ditandain merah, 10.000 ENGGA.
        baris_kra = html[i_kra - 400:i_kra]
        assert "merah" in baris_kra, "min_views 20rb ga ditandain merah"

        # --- 3. Pilih garap, dan tandanya nempel ----------------------------
        kode, _ = _form(url + "/campaign/karomah-insani/pick",
                        {"state": "garap", "note": "cpm tinggi budget penuh"})
        assert kode == 200, kode
        kode, html = _req(url + "/campaign?saring=garap")
        assert "karomah-insani" in html and "krakatau" not in html, \
            "saringan 'digarap' ga nyaring"

        # --- 4. Upload BGM + gambar + link video ----------------------------
        kode, html = _multipart(
            url + "/campaign/karomah-insani/aset",
            {"video_link": "https://youtu.be/abc123", "label": "dari brand"},
            [("image", "poster.png", b"\x89PNG\r\n\x1a\n" + b"x" * 64),
             ("bgm", "emotional_piano.mp3", b"ID3" + b"y" * 128)])
        assert kode == 200, kode
        kode, html = _req(url + "/campaign/karomah-insani")
        assert "youtu.be/abc123" in html
        assert "emotional_piano.mp3" in html
        assert "poster.png" not in html, \
            "nama file asli dipakai apa adanya — harusnya diganti"
        # Filenya beneran ada di folder aset, bukan cuma baris di DB.
        ada = os.listdir(os.path.join(aset_dir, "karomah-insani"))
        assert len(ada) == 2, ada
        assert all(f.startswith(("image_", "bgm_")) for f in ada), ada

        # --- 5. Nama file ga boleh keluar dari folder aset ------------------
        jejak = os.path.join(BASE, "job.py")
        sebelum = os.path.getsize(jejak)
        kode, _ = _multipart(
            url + "/campaign/karomah-insani/aset", {},
            [("image", "../../../job.py", b"RUSAK")])
        assert kode == 200, kode
        assert os.path.getsize(jejak) == sebelum, "job.py ketimpa upload!"
        assert not os.path.exists(os.path.join(tmp, "job.py"))

        # --- 6. Link selain YouTube/Drive ditolak di depan ------------------
        kode, html = _multipart(
            url + "/campaign/karomah-insani/aset",
            {"video_link": "https://vimeo.com/123"}, [])
        assert "cuma didukung YouTube atau Google Drive" in html, html[:400]
        kode, html = _req(url + "/campaign/karomah-insani")
        assert "vimeo" not in html, "link ga didukung tetep kesimpen"

        # --- 7. PAGAR: form ga boleh nunjuk file sembarangan ---------------
        # POST dibikin tangan, persis kayak orang yang ngedit HTML-nya.
        #
        # DUA CACAT tes yang ketangkep di kontrol negatif (pagar dimatiin,
        # tes tetep ijo), dan dua-duanya bikin tesnya palsu:
        #   1. preset "jedag" GA ADA (kuncinya 'sedih'/'jamet'), jadi POST-nya
        #      kena tolak di cek preset dan pagar path ga pernah kejalan.
        #   2. kata "ditolak" muncul di hint form render yang biasa, jadi
        #      assertion-nya kecocokan terus walau yang balik halaman sukses.
        # Makanya sekarang: preset yang SAH, dan buktinya bukan teks halaman
        # tapi jumlah job di antrean.
        import render_queue as rq
        qconn = rq.connect(env["CLIPPER_QUEUE_DB"])
        assert rq.waiting_count(qconn) == 0, "antrean ga kosong di awal"
        for jahat in ("/etc/passwd", os.path.join(BASE, "job.py"),
                      os.path.join(aset_dir, "..", "..", "etc", "passwd")):
            kode, html = _form(url + "/render", {
                "preset": "jamet", "content": "https://youtu.be/x",
                "bgm_file": jahat})
            assert kode == 200, kode
            assert "Path lain" in html or "ga ada di disk" in html, \
                ("path %r ga ditolak: %s" % (jahat, html[:400]))
            # Bukti yang ga bisa dipalsuin teks halaman: ga ada job masuk.
            assert rq.waiting_count(qconn) == 0, \
                "job dengan bgm_file=%r masuk antrean" % jahat
        # Gambar outro juga, lewat jalur yang sama.
        kode, html = _form(url + "/render", {
            "preset": "jamet", "content": "https://youtu.be/x",
            "portrait": "/etc/hostname"})
        assert rq.waiting_count(qconn) == 0, "portrait sembarangan masuk antrean"

        # --- 8. Jalur yang BENER: aset campaign masuk antrean --------------
        bgm_path = [os.path.join(aset_dir, "karomah-insani", f)
                    for f in ada if f.startswith("bgm_")][0]
        kode, html = _form(url + "/render", {
            "preset": "sedih", "content": "https://youtu.be/abc123",
            "campaign": "karomah-insani", "bgm_file": bgm_path,
            "context": "tes"})
        assert kode == 200, kode
        jobs = rq.for_campaign(qconn, "karomah-insani")
        assert len(jobs) == 1, jobs
        p = json.loads(jobs[0]["params"])
        assert p["bgm_file"] == bgm_path and p["campaign"] == "karomah-insani"
        # Job-nya kelihatan di halaman campaign-nya, bukan cuma di DB.
        kode, html = _req(url + "/campaign/karomah-insani")
        assert "#%d" % jobs[0]["id"] in html

        # --- 9. Perintah render BENER-BENER bawa --bgm-file ----------------
        # Ini yang nentuin pixel: param di DB yang ga nyampe argv itu no-op.
        import render_worker as rw
        cmd = rw._perintah(jobs[0])
        assert "--bgm-file" in cmd and cmd[cmd.index("--bgm-file") + 1] == bgm_path, cmd
        # Dan kalau filenya ilang, flag-nya DIBUANG (render jalan pakai stok
        # + warning dari job.py) bukan bikin argparse gagal.
        hilang = dict(jobs[0],
                      params=json.dumps(dict(p, bgm_file=os.path.join(
                          tmp, "ga-ada.mp3"))))
        assert "--bgm-file" not in rw._perintah(hilang)
        # Flag-nya harus yang job.py BENERAN punya. --copy-style pernah
        # kepake di sini dan render gagal "invalid choice".
        bantuan = subprocess.run([PY, os.path.join(BASE, "job.py"), "--help"],
                                 capture_output=True, text=True, cwd=BASE).stdout
        assert "--bgm-file" in bantuan, "job.py ga punya flag --bgm-file"

        # --- 9b. MOOD WAJIB SELAMAT DARI RENAME UPLOAD -------------------
        # Bug nyata yang cuma ketangkep dari render sungguhan: upload
        # disimpen jadi `bgm_<timestamp>.mp3`, dan `bgm._from_filename`
        # baca mood DARI NAMA FILE -- jadi tiap BGM upload kebaca mood
        # kosong dan pemeriksa tabrakan register MATI PERMANEN. Lagu
        # jedag-jedug nempel di klip duka tanpa satu pun warning.
        import bgm as _bgm
        hype = camp.save_upload(
            "karomah-insani", "bgm",
            "hype_dj_nansuya_gang_jedag_jedug.mp3", b"ID3" + b"z" * 64)
        assert _bgm._from_filename(os.path.basename(hype)) == ["hype"], \
            ("mood ilang waktu upload di-rename: %s"
             % os.path.basename(hype))
        assert _bgm._clashes("emotional", "hype"), \
            "aturan bentrok emotional x hype ilang dari bgm.py"

        # Dan blok --bgm-file di job.py BENERAN ngasih warning buat bentrok
        # itu. Yang dieksekusi POTONGAN KODE ASLINYA, bukan versi tulis
        # ulang di tes: tes yang nyalin logika bisa ijo sementara yang
        # jalan di render udah beda.
        import audit as _audit
        src = open(os.path.join(BASE, "job.py"), encoding="utf-8").read()
        blok = src[src.index("    if bgm_file:"):
                   src.index("    # Where _mood CAME FROM")]
        blok = blok.replace("    ", "", 1).replace("\n    ", "\n")
        kasus = [("emotional", hype, True),
                 ("hype", hype, False),
                 ("emotional", camp.save_upload(
                     "karomah-insani", "bgm", "emotional_piano.mp3", b"x"),
                  False)]
        for mood_klip, path, harus_warning in kasus:
            ns = {"bgm_file": path, "os": os, "bgm": _bgm, "audit": _audit,
                  "_mood": mood_klip, "warnings": [], "track": None,
                  "why": None}
            exec(blok, ns)
            ada = bool(ns["warnings"])
            assert ada == harus_warning, \
                ("klip %r + %s: warning=%s, harusnya %s"
                 % (mood_klip, os.path.basename(path), ada, harus_warning))
            # Lagunya TETEP dipakai apa adanya, warning atau ga: pilihan
            # manusia menang, tabrakan cuma dikabarin.
            assert ns["track"]["path"] == path

        # --- 10. Aset kehapus: baris ilang, file ikut kebuang -------------
        aid = [a["id"] for a in camp.assets(conn, "karomah-insani")
               if a["kind"] == "bgm"][0]
        assert os.path.exists(bgm_path)
        kode, _ = _form(url + "/campaign/karomah-insani/aset/hapus",
                        {"asset_id": aid})
        assert kode == 200, kode
        assert not os.path.exists(bgm_path), "file aset ga kebuang dari disk"

        # --- 11. Marketplace mati: papan lama TETEP kelihatan ------------
        # Diuji dengan ngerusak URL-nya di proses tes, lalu manggil refresh.
        _lama_url = camp.LIST_URL
        camp.LIST_URL = "https://127.0.0.1:1/ga-ada"
        try:
            try:
                camp.refresh(conn)
                raise AssertionError("refresh ke host mati harusnya gagal")
            except RuntimeError:
                pass
            # Papan masih punya dua campaign-nya, ga kekosongan.
            assert len(camp.board(conn)) == 2
        finally:
            camp.LIST_URL = _lama_url

        # --- 12. Halaman render utama masih idup, formnya bisa upload ----
        kode, html = _req(url + "/")
        assert kode == 200
        assert 'enctype="multipart/form-data"' in html, \
            "form render ga bisa nerima file"
        assert 'name=bgm' in html and 'name=image' in html
        assert "/campaign" in html, "ga ada jalan ke papan campaign"

        print("_v83 ok: papan urut skor, upload aman, --bgm-file nyampe argv")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.path.insert(0, BASE)
    raise SystemExit(main())
