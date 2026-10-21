"""_v91: tanda 'garap' punya ARTI, dan triage bisa dari baris papan.

Dua permintaan operator ("ya untuk both 1 dan 2"), dan dua-duanya punya cara
gagal yang diem-diem:

1. **Tombol putusan di baris papan.** Triage 49 campaign lewat buka-tutup
   halaman detail itu 98 klik. Tombolnya harus POST (bukan link GET: GET yang
   nulis DB bisa kepanggil ulang sama prefetch browser) dan harus balik ke
   SARINGAN yang lagi dipakai, bukan ke papan default — kalau balik ke default
   tiap klik, orang kehilangan tempat dia berhenti.

2. **Render cuma buat campaign 'garap'.** Ini yang bikin tandanya berarti.
   CARA GAGAL YANG DIJAGA DI SINI: pagar yang cuma nyembunyiin form.
   Nyembunyiin tombol BUKAN pagar — tab lama yang masih kebuka, tombol back,
   atau POST bikinan tangan semuanya ngelewatin tampilan. Jadi tes ini nembak
   POST /render LANGSUNG, dan buktinya bukan teks halaman tapi JUMLAH JOB DI
   ANTREAN (teks bisa kebetulan cocok; antrean nol ga bisa dipalsuin).

Yang juga dijaga: render LEPAS (tanpa campaign) harus TETEP jalan. Pagar yang
kelewat lebar matiin form utama, dan itu bukan yang diminta.

Jalan pakai server sungguhan di port acak + DB sementara.
"""
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(BASE, ".venv", "bin", "python")
USER, PASS = "tes", "sandi-tes"
sys.path.insert(0, BASE)

ok = 0


def cek(kondisi, pesan):
    global ok
    assert kondisi, pesan
    ok += 1


def _port_bebas():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _auth():
    return "Basic " + base64.b64encode(
        ("%s:%s" % (USER, PASS)).encode()).decode()


def _req(url, data=None, headers=None):
    h = {"Authorization": _auth()}
    h.update(headers or {})
    r = urllib.request.Request(url, data=data, headers=h)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _form(url, fields, ikuti=True):
    body = "&".join("%s=%s" % (k, urllib.parse.quote(str(v)))
                    for k, v in fields.items()).encode()
    h = {"Authorization": _auth(),
         "Content-Type": "application/x-www-form-urlencoded"}
    r = urllib.request.Request(url, data=body, headers=h)
    opener = (urllib.request.build_opener() if ikuti
              else urllib.request.build_opener(_NoRedirect))
    # JEBAKAN: dict(resp.headers) ngilangin sifat case-insensitive-nya
    # email.Message, dan Starlette ngirim header `location` HURUF KECIL.
    # Versi pertama tes ini "gagal" di cek redirect sementara server-nya
    # bener. Kembaliin objek headers aslinya.
    try:
        with opener.open(r, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), \
                resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.headers


def main():
    import campaigns as camp
    import render_queue as rq

    tmp = tempfile.mkdtemp(prefix="v91_")
    port = _port_bebas()
    env = dict(os.environ)
    env.update({
        "CLIPPER_CONSOLE_USERS": "%s:%s" % (USER, PASS),
        "CLIPPER_CONSOLE_PORT": str(port),
        "CLIPPER_QUEUE_DB": os.path.join(tmp, "queue.db"),
        "CLIPPER_CAMPAIGN_DB": os.path.join(tmp, "campaigns.db"),
        "CLIPPER_CAMPAIGN_ASSETS": os.path.join(tmp, "aset"),
        "PYTHONPATH": BASE,
    })

    conn = camp.connect(env["CLIPPER_CAMPAIGN_DB"])
    camp.refresh(conn, [
        {"slug": "satu", "id": "1", "title": "Campaign Satu", "brand": "AAA",
         "status": "active", "cpm_tiktok": 10000,
         "budget_bar_percent_override": 90, "min_views": 1000,
         "min_video_duration": 30, "platform": ["tiktok"],
         "description": "brief satu", "hashtags": ["satu"]},
        {"slug": "dua", "id": "2", "title": "Campaign Dua", "brand": "BBB",
         "status": "active", "cpm_tiktok": 5000,
         "budget_bar_percent_override": 80, "min_views": 1000,
         "min_video_duration": 30, "platform": ["tiktok"],
         "description": "brief dua", "hashtags": ["dua"]},
    ])
    # Tiap campaign butuh link video, kalau ga panel render-nya ga pernah
    # nyampe ke cek garap (dia keburu bilang "belum ada link video") dan tes
    # pagar jadi benar-trivial.
    for slug in ("satu", "dua"):
        camp.add_asset(conn, slug, "video_link", "https://youtu.be/abc123",
                       who="tes")

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
            raise AssertionError("console ga pernah siap")

        qconn = rq.connect(env["CLIPPER_QUEUE_DB"])

        # ---- 1. Tombol putusan ADA di baris papan ----------------------
        kode, html = _req(url + "/campaign")
        cek(kode == 200, "papan ga kebuka: %s" % kode)
        cek("action='/campaign/satu/pick'" in html,
            "baris papan ga punya form pick — triage balik ke buka-tutup "
            "halaman")
        cek("name=state value=garap" in html, "tombol garap ga ada di baris")
        cek("name=state value=lewat" in html, "tombol lewat ga ada di baris")
        cek("name=balik" in html,
            "tombol baris ga bawa `balik` — abis klik orang kelempar ke "
            "papan default dan kehilangan saringannya")
        cek("<th>Putusan</th>" in html, "kolom Putusan ga ada di header")
        # GET yang nulis DB itu jebakan: prefetch browser bisa manggil
        # sendiri. Pastiin ga ada link pick.
        cek("href='/campaign/satu/pick'" not in html
            and 'href="/campaign/satu/pick"' not in html,
            "putusan kepasang sebagai link GET — prefetch browser bisa "
            "nandain campaign tanpa ada yang ngeklik")

        # ---- 2. PAGAR RENDER, campaign BELUM diputusin ------------------
        cek(rq.waiting_count(qconn) == 0, "antrean ga kosong di awal")
        kode, html, _ = _form(url + "/render", {
            "preset": "jamet", "content": "https://youtu.be/abc123",
            "campaign": "satu"})
        cek(kode == 200, "POST render bales %s" % kode)
        # Bukti yang ga bisa dipalsuin teks halaman.
        cek(rq.waiting_count(qconn) == 0,
            "campaign BELUM diputusin tapi job-nya masuk antrean — pagar "
            "garap cuma di tampilan, bukan di server")
        cek("garap" in html.lower(),
            "pesan tolakan ga nyebut garap, orang ga tau mesti ngapain")

        # ---- 3. Pagar juga nolak status 'lewat' -------------------------
        _form(url + "/campaign/dua/pick", {"state": "lewat"})
        kode, html, _ = _form(url + "/render", {
            "preset": "jamet", "content": "https://youtu.be/abc123",
            "campaign": "dua"})
        cek(rq.waiting_count(qconn) == 0,
            "campaign 'lewat' tetep bisa masuk antrean")

        # ---- 4. Panel form juga ga nawarin tombol bohong ---------------
        kode, html = _req(url + "/campaign/satu")
        cek("Masukin antrean" not in html,
            "form render masih nongol padahal campaign belum garap — "
            "tombolnya bohong")

        # ---- 5. Abis ditandain GARAP, render JALAN ----------------------
        kode, html, hdr = _form(url + "/campaign/satu/pick",
                                {"state": "garap", "balik": "garap"},
                                ikuti=False)
        cek(kode == 303, "pick ga redirect: %s" % kode)
        cek("saring=garap" in hdr.get("Location", ""),
            "abis klik dari baris papan, orang ga dibalikin ke saringannya "
            "(Location=%r)" % hdr.get("Location"))

        kode, html = _req(url + "/campaign/satu")
        cek("Masukin antrean" in html,
            "campaign udah garap tapi form render masih ketutup")
        kode, html, _ = _form(url + "/render", {
            "preset": "jamet", "content": "https://youtu.be/abc123",
            "campaign": "satu", "context": "tes"})
        jobs = rq.for_campaign(qconn, "satu")
        cek(len(jobs) == 1,
            "campaign GARAP malah ga bisa render — pagarnya kelewat lebar: "
            "%r" % jobs)
        cek(json.loads(jobs[0]["params"])["campaign"] == "satu",
            "job kesimpen tapi campaign-nya ilang dari params")

        # ---- 6. Render LEPAS (tanpa campaign) tetep jalan ---------------
        # Pagar yang kelewat lebar matiin form utama. Ini kontrol arah
        # sebaliknya: yang dijaga cuma render yang nempel ke campaign.
        sebelum = rq.waiting_count(qconn)
        kode, html, _ = _form(url + "/render", {
            "preset": "sedih", "content": "https://youtu.be/lepas1"})
        cek(rq.waiting_count(qconn) == sebelum + 1,
            "render lepas (tanpa campaign) kena pagar garap — pagarnya "
            "kelewat lebar, form utama ikut mati")

        # ---- 7. Campaign yang ga ada di papan ditolak -------------------
        sebelum = rq.waiting_count(qconn)
        kode, html, _ = _form(url + "/render", {
            "preset": "jamet", "content": "https://youtu.be/abc123",
            "campaign": "slug-ngawur-ga-ada"})
        cek(rq.waiting_count(qconn) == sebelum,
            "campaign ngawur masuk antrean")

        # ---- 8. Hapus tanda: balik ketutup lagi ------------------------
        _form(url + "/campaign/satu/pick", {"state": "batal"})
        sebelum = rq.waiting_count(qconn)
        kode, html, _ = _form(url + "/render", {
            "preset": "jamet", "content": "https://youtu.be/abc123",
            "campaign": "satu"})
        cek(rq.waiting_count(qconn) == sebelum,
            "tanda garap dihapus tapi render masih jalan — statusnya dibaca "
            "sekali lalu di-cache, bukan dibaca per POST")

        print("_v91 ok: %d cek — tombol putusan di baris papan, pagar garap "
              "di server (bukan cuma UI), render lepas tetep jalan" % ok)
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
