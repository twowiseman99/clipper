"""_v91: triage putusan dari baris papan, TANPA ngunci render.

Permintaan operator dua tahap, dan tahap kedua DICABUT dengan alasan yang
harus ikut kejaga di sini:

1. **Tombol putusan di baris papan.** Triage 49 campaign lewat buka-tutup
   halaman detail itu 98 klik. Tombolnya harus POST (bukan link GET: GET yang
   nulis DB bisa kepanggil ulang sama prefetch browser) dan harus balik ke
   SARINGAN yang lagi dipakai, bukan ke papan default — kalau balik ke default
   tiap klik, orang kehilangan tempat dia berhenti.

2. ~~Render cuma buat campaign 'garap'~~ **DITOLAK operator 21 Okt:**
   *"kalau 2 di iyakan nanti ribet kalau mau testing untuk video2 yg non
   campaign"*. Pagar itu sempat kepasang lalu dicabut lagi.

   Yang bikin ini lebih dari "ya udah dihapus": nguji video DI BAWAH campaign
   itu kerjaan yang SAH — di situ aset + brief-nya kepake. Pagar garap bikin
   lu wajib nandain keputusan bisnis dulu cuma buat nyoba render, dan itu
   bikin tanda `garap` jadi bohong (ketekan buat tes, bukan buat mutusin).
   Jadi tes di bawah ini ngejaga ARAH SEBALIKNYA: render WAJIB jalan di
   status apa pun — belum diputusin, `lewat`, maupun `garap`. Kalau besok ada
   yang masang balik pagarnya, cek ini yang merah.

`garap` itu penanda keputusan tim (siapa + kapan + alasan), BUKAN izin
teknis. Jangan kasih dia kuasa mengeksekusi.

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

        # ---- 2. Render JALAN walau campaign belum diputusin -------------
        # Ini arah yang dijaga setelah operator nolak pagar garap: nguji
        # video non-campaign / campaign yang belum diputusin itu kerjaan
        # yang sah. Bukti pakai JUMLAH JOB, bukan teks halaman.
        cek(rq.waiting_count(qconn) == 0, "antrean ga kosong di awal")
        kode, html, _ = _form(url + "/render", {
            "preset": "jamet", "content": "https://youtu.be/abc123",
            "campaign": "satu", "context": "tes"})
        cek(kode == 200, "POST render bales %s" % kode)
        jobs = rq.for_campaign(qconn, "satu")
        cek(len(jobs) == 1,
            "campaign BELUM diputusin ga bisa dirender — pagar garap kepasang "
            "lagi, padahal operator nolak: testing video non-campaign jadi "
            "ribet")
        cek(json.loads(jobs[0]["params"])["campaign"] == "satu",
            "job kesimpen tapi campaign-nya ilang dari params")

        # ---- 3. Render JALAN juga di campaign 'lewat' -------------------
        # Status 'lewat' itu catatan keputusan bisnis, bukan larangan
        # teknis. Orang tetep boleh nyoba render buat ngecek apakah
        # keputusan 'lewat'-nya udah bener.
        _form(url + "/campaign/dua/pick", {"state": "lewat"})
        kode, html, _ = _form(url + "/render", {
            "preset": "jamet", "content": "https://youtu.be/abc123",
            "campaign": "dua", "context": "tes"})
        cek(len(rq.for_campaign(qconn, "dua")) == 1,
            "campaign 'lewat' ga bisa dirender — status putusan jangan "
            "dijadiin izin teknis")

        # ---- 4. Panel form render kebuka tanpa lihat status putusan -----
        kode, html = _req(url + "/campaign/satu")
        cek("Masukin antrean" in html,
            "form render ketutup padahal campaign belum diputusin — itu "
            "pagar garap lewat tampilan")
        kode, html = _req(url + "/campaign/dua")
        cek("Masukin antrean" in html,
            "form render ketutup di campaign 'lewat'")

        # ---- 5. Putusan dari baris papan: redirect ke saringan ----------
        kode, html, hdr = _form(url + "/campaign/satu/pick",
                                {"state": "garap", "balik": "garap"},
                                ikuti=False)
        cek(kode == 303, "pick ga redirect: %s" % kode)
        cek("saring=garap" in hdr.get("Location", ""),
            "abis klik dari baris papan, orang ga dibalikin ke saringannya "
            "(Location=%r)" % hdr.get("Location"))
        # Form di halaman DETAIL ga ngirim `balik` -> perilaku lama kejaga.
        kode, html, hdr = _form(url + "/campaign/satu/pick",
                                {"state": "garap"}, ikuti=False)
        cek(hdr.get("Location", "").endswith("/campaign/satu"),
            "form di halaman detail ga balik ke halaman campaign lagi "
            "(Location=%r)" % hdr.get("Location"))

        # ---- 6. Tanda garap nempel + nyaring ---------------------------
        kode, html = _req(url + "/campaign?saring=garap")
        cek("satu" in html and "Campaign Dua" not in html,
            "saringan 'digarap' ga nyaring")
        kode, html = _req(url + "/campaign?saring=lewat")
        cek("Campaign Dua" in html, "saringan 'dilewat' ga nyaring")

        # ---- 7. Render lepas (tanpa campaign) tetep jalan ---------------
        sebelum = rq.waiting_count(qconn)
        kode, html, _ = _form(url + "/render", {
            "preset": "sedih", "content": "https://youtu.be/lepas1"})
        cek(rq.waiting_count(qconn) == sebelum + 1,
            "render lepas (tanpa campaign) ga masuk antrean")

        print("_v91 ok: %d cek — tombol putusan di baris papan, redirect "
              "balik ke saringan, dan render TETEP bebas di semua status "
              "putusan (pagar garap sengaja ga ada)" % ok)
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
