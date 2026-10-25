"""_v96: campaign hilang ('gone'), brief lengkap dua sumber, dan Clippo di papan.

Semua cek jalan in-memory + DB sementara (tempdir) tanpa akses internet.
Setiap handler diuji di jalur SUKSES dan jalur GAGAL sekaligus.
"""
import base64
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

_tmp = tempfile.mkdtemp(prefix="v96_")
os.environ["CLIPPER_CONSOLE_USERS"] = "tester:sandi-v96"
os.environ["CLIPPER_QUEUE_DB"] = os.path.join(_tmp, "queue.db")
os.environ["CLIPPER_CAMPAIGN_DB"] = os.path.join(_tmp, "campaigns.db")
os.environ["CLIPPER_CAMPAIGN_ASSETS"] = os.path.join(_tmp, "aset")

import campaigns as camp                    # noqa: E402
import render_console as rc                 # noqa: E402
from fastapi.testclient import TestClient   # noqa: E402

AUTH = {
    "Authorization": "Basic " + base64.b64encode(b"tester:sandi-v96").decode()
}

ok = 0
gagal = []


def cek(nama, syarat):
    global ok
    if syarat:
        ok += 1
        print("  ok   %s" % nama)
    else:
        gagal.append(nama)
        print("  FAIL %s" % nama)


def main():
    try:
        camp.DB_PATH = os.environ["CLIPPER_CAMPAIGN_DB"]
        camp.ASSET_DIR = os.environ["CLIPPER_CAMPAIGN_ASSETS"]

        # ------------------------------------------------------------------ 1
        print("== 1. Migrasi DB lama (ALTER TABLE aman dijalanin ulang) ==")
        db_lama = os.path.join(_tmp, "lama.db")
        raw_conn = sqlite3.connect(db_lama)
        raw_conn.execute("""
            CREATE TABLE campaigns (
                slug TEXT PRIMARY KEY,
                cid TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                brand TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                platform TEXT NOT NULL DEFAULT '[]',
                cpm INTEGER NOT NULL DEFAULT 0,
                cpm_source TEXT NOT NULL DEFAULT '',
                budget_left INTEGER,
                min_views INTEGER,
                min_seconds INTEGER,
                content_type TEXT NOT NULL DEFAULT '',
                campaign_type TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT '',
                hashtags TEXT NOT NULL DEFAULT '[]',
                description TEXT NOT NULL DEFAULT '',
                deadline TEXT NOT NULL DEFAULT '',
                fetched_at REAL NOT NULL DEFAULT 0
            )
        """)
        raw_conn.execute(
            "INSERT INTO campaigns (slug, title, status) VALUES ('lama-1', 'Lama', 'active')"
        )
        raw_conn.commit()
        raw_conn.close()

        # Panggil connect() dua kali buat buktiin migrasi idempotent
        c1 = camp.connect(db_lama)
        c2 = camp.connect(db_lama)
        kolom = {r["name"] for r in c2.execute("PRAGMA table_info(campaigns)")}
        cek("kolom source, brief_json, brief_at ketambah",
            {"source", "brief_json", "brief_at"}.issubset(kolom))
        baris_lama = camp.get(c2, "lama-1")
        cek("baris lama default source='konten'",
            baris_lama["source"] == "konten" and baris_lama["brief_json"] == "")
        c1.close()
        c2.close()

        # ------------------------------------------------------------------ 2
        print("== 2. Campaign hilang ('gone'), pagar list kosong, pick & aset selamat ==")
        conn = camp.connect()
        camp.refresh(conn, [
            {"slug": "masih-ada", "id": "camp-111", "title": "Masih Ada",
             "brand": "BrandA", "status": "active", "cpm_tiktok": 8000,
             "budget_bar_percent_override": 90, "min_views": 5000,
             "min_video_duration": 20, "platform": ["tiktok"],
             "description": "deskripsi masih ada"},
            {"slug": "bakal-ilang", "id": "camp-222", "title": "Bakal Ilang",
             "brand": "BrandB", "status": "active", "cpm_tiktok": 9000,
             "budget_bar_percent_override": 80, "min_views": 5000,
             "min_video_duration": 15, "platform": ["tiktok"],
             "description": "deskripsi bakal ilang"},
        ])

        # Pasang pick + aset di campaign yang bakal ilang
        camp.pick(conn, "bakal-ilang", "garap", who="oden", note="udah digarap")
        aid = camp.add_asset(conn, "bakal-ilang", "video_link",
                             "https://youtu.be/bahan123", label="mentahan", who="oden")
        path_img = camp.save_upload("bakal-ilang", "image", "cover.png", b"\x89PNGxxxx")
        camp.add_asset(conn, "bakal-ilang", "image", path_img, label="cover", who="oden")

        # Refresh kedua: 'bakal-ilang' dicopot dari list marketplace
        camp.refresh(conn, [
            {"slug": "masih-ada", "id": "camp-111", "title": "Masih Ada",
             "brand": "BrandA", "status": "active", "cpm_tiktok": 8000,
             "budget_bar_percent_override": 90, "min_views": 5000,
             "min_video_duration": 20, "platform": ["tiktok"],
             "description": "deskripsi masih ada"},
        ])

        c_aktif = camp.get(conn, "masih-ada")
        c_gone = camp.get(conn, "bakal-ilang")
        cek("campaign yang masih di list tetep 'active' (kontrol positif)",
            c_aktif is not None and c_aktif["status"] == "active")
        cek("campaign yang ilang dari list ditandai status='gone'",
            c_gone is not None and c_gone["status"] == "gone")

        papan_aktif = [r["slug"] for r in camp.board(conn, hanya_aktif=True)]
        cek("campaign aktif muncul di board() & campaign gone GA muncul",
            "masih-ada" in papan_aktif and "bakal-ilang" not in papan_aktif)

        # Pick dan aset di baris 'gone' WAJIB selamat
        cek("pick baris gone selamat",
            c_gone["pick"] == "garap" and c_gone["pick_note"] == "udah digarap")
        aset_gone = camp.assets(conn, "bakal-ilang")
        cek("aset baris gone selamat (2 aset + file di disk utuh)",
            len(aset_gone) == 2 and any(a["id"] == aid for a in aset_gone)
            and os.path.exists(path_img))

        # PAGAR list kosong: JANGAN tandai 'masih-ada' gone kalau list kosong
        camp.refresh(conn, [])
        cek("list kosong GA nandain campaign aktif jadi gone",
            camp.get(conn, "masih-ada")["status"] == "active")

        # ------------------------------------------------------------------ 3
        print("== 3. Clippo masuk papan (cpm, budget_left, url, pagar sumber) ==")
        clippo_contoh = [
            {
                "id": "clp100",
                "title": "Clippo Campaign Satu",
                "status": 3,
                "ratePerKView": 2000,
                "rateUnit": 1000,
                "budgetPercentage": 95.34,
                "minDuration": 15,
                "maxDuration": 90,
                "platformSupported": [0, 1],
                "hashtags": ["#ClippoSatu", "Viral"],
                "campaignDos": ["Wajib kualitas HD", ""],
                "campaignDonts": ["Dilarang reupload mentah", ""],
                "requirementsV2": "<p>Wajib <strong>pakai</strong> logo</p><p>Minimal 15 detik</p>",
                "contentMainFocus": {"ops": [{"insert": "Fokus ke manfaat produk\n"}]},
                "campaignHook": {"ops": [{"insert": "Kenapa banyak yang pindah ke sini?\n"}]},
                "campaignPurpose": {"ops": [{"insert": "Awareness produk baru\n"}]},
                "notes": {"ops": [{"insert": "Catatan tambahan clippo <script>alert('xss-clippo')</script>\n"}]},
                "assetVideoUrlsV2": [
                    {"url": "https://drive.google.com/drive/folders/abc",
                     "isRequired": True, "displayText": "Footage Utama"},
                    {"url": "javascript:alert(1)",
                     "isRequired": False, "displayText": "Link Jahat"},
                ],
                "creator": {"user": {"name": "ClippoBrand"}},
            },
            {
                "id": "clp200",
                "title": "Clippo Multi Rate",
                "status": 3,
                "ratePerKView": 1000,
                "rateUnit": 1000,
                "campaignRates": [
                    {"platform": 0, "ratePerKView": 1500, "rateUnit": 1000},
                    {"platform": 1, "ratePerKView": 3000, "rateUnit": 1000},
                ],
                "budgetPercentage": 50.0,
                "minDuration": 30,
                "platformSupported": [0, 1],
                "creator": {"user": {"name": "BrandDua"}},
            },
            {
                "id": "clp300",
                "title": "Clippo Udah Selesai",
                "status": 1,
                "ratePerKView": 5000,
                "rateUnit": 1000,
                "budgetPercentage": 10.0,
            },
        ]
        tot_c, baru_c, akt_c = camp.refresh_clippo(conn, clippo_contoh)
        cek("refresh_clippo hitung total=3, baru=3, aktif=2",
            (tot_c, baru_c, akt_c) == (3, 3, 2))

        c_clp1 = camp.get(conn, "clippo-clp100")
        cek("Clippo ratePerKView 2000/rateUnit 1000 -> cpm 2000",
            c_clp1["cpm"] == 2000)
        cek("Clippo budgetPercentage 95.34 -> budget_left 95",
            c_clp1["budget_left"] == 95)
        cek("Clippo skor = round(2000 * 95 / 100) = 1900",
            c_clp1["score"] == 1900)
        cek("Clippo source='clippo' & min_seconds=15 & brand='ClippoBrand'",
            c_clp1["source"] == "clippo" and c_clp1["min_seconds"] == 15
            and c_clp1["brand"] == "ClippoBrand")
        cek("Clippo URL publik = https://app.clippo.id/campaigns/<id>",
            c_clp1["url"] == "https://app.clippo.id/campaigns/clp100")
        cek("konten.com URL tetep SITE + slug",
            camp.get(conn, "masih-ada")["url"] == "https://konten.com/campaigns/masih-ada")

        c_clp2 = camp.get(conn, "clippo-clp200")
        cek("Clippo campaignRates tertinggi menang (3000 instagram)",
            c_clp2["cpm"] == 3000 and c_clp2["cpm_source"] == "instagram")
        c_clp3 = camp.get(conn, "clippo-clp300")
        cek("Clippo status != 3 jadi 'completed'",
            c_clp3["status"] == "completed")

        # Pagar lintas sumber: refresh_clippo ga boleh nandain 'masih-ada' (konten) jadi gone
        cek("refresh_clippo GA nandain baris konten jadi gone",
            camp.get(conn, "masih-ada")["status"] == "active")
        # Dan refresh konten ga boleh nandain baris clippo jadi gone
        camp.refresh(conn, [
            {"slug": "masih-ada", "id": "camp-111", "title": "Masih Ada",
             "brand": "BrandA", "status": "active", "cpm_tiktok": 8000,
             "budget_bar_percent_override": 90},
        ])
        cek("refresh konten GA nandain baris clippo jadi gone",
            camp.get(conn, "clippo-clp100")["status"] == "active")

        # Clippo hilang dari list -> gone, tapi list kosong -> jangan gone
        camp.refresh_clippo(conn, [])
        cek("refresh_clippo([]) GA nandain clippo-clp200 gone",
            camp.get(conn, "clippo-clp200")["status"] == "active")
        camp.refresh_clippo(conn, [clippo_contoh[0]])
        cek("clippo-clp200 hilang dari list Clippo -> status='gone'",
            camp.get(conn, "clippo-clp200")["status"] == "gone")
        cek("clippo-clp100 yang masih di list tetep 'active'",
            camp.get(conn, "clippo-clp100")["status"] == "active")

        # ------------------------------------------------------------------ 4
        print("== 4. normalize_brief seragam buat konten & clippo ==")
        raw_konten = {
            "slug": "masih-ada",
            "min_video_duration": 20,
            "hashtags": ["KontenTag"],
            "brief_dos": ["Boleh pakai musik bebas royalti", ""],
            "brief_donts": ["", "Jangan pakai watermark kompetitor"],
            "brief_detail": {
                "elemenWajib": "- Wajib tampilkan produk di 3 detik awal\n- Wajib sebut nama brand <script>alert('xss-konten')</script>",
                "materialWajib": "Wajib pakai footage dari link materi",
                "materialWajibChoice": "wajib",
                "bolehDilakukan": ["- Boleh tambah efek transisi", ""],
                "dilarangDilakukan": ["- Dilarang mengandung SARA", ""],
                "materi": [
                    {"url": "https://youtu.be/materi-konten-1", "title": "Video Utama Konten"},
                    {"url": "ftp://server-luar/file.mp4", "title": "Materi FTP"},
                ],
                "captionWajib": "Beli sekarang di keranjang kuning",
                "cta": "Cek link di bio!",
                "narasi": "- Ceritakan pengalaman pakai produk ini",
                "instruksiBrief": "Pastikan resolusi minimal 1080p",
                "durasiMin": "20",
                "durasiMax": "60",
            },
        }
        nb_k = camp.normalize_brief("konten", raw_konten)
        nb_c = camp.normalize_brief("clippo", clippo_contoh[0])
        kunci_wajib = {"wajib", "boleh", "dilarang", "materi", "caption", "hook", "catatan", "durasi"}
        cek("normalize_brief punya kunci yang SAMA persis di dua sumber",
            set(nb_k.keys()) == kunci_wajib and set(nb_c.keys()) == kunci_wajib)
        cek("normalize_brief konten: wajib/boleh/dilarang/materi/durasi keisi & string kosong kebuang",
            any("3 detik awal" in x for x in nb_k["wajib"])
            and any("transisi" in x for x in nb_k["boleh"])
            and any("SARA" in x for x in nb_k["dilarang"])
            and "" not in nb_k["boleh"] and "" not in nb_k["dilarang"]
            and nb_k["materi"][0]["wajib"] is True
            and nb_k["durasi"] == {"min": 20, "max": 60})
        cek("normalize_brief clippo: HTML tag <p>/<strong> dibuang & Quill delta digabung",
            "Wajib pakai logo" in nb_c["wajib"]
            and "Fokus ke manfaat produk" in nb_c["wajib"]
            and "Wajib kualitas HD" in nb_c["boleh"]
            and "Dilarang reupload mentah" in nb_c["dilarang"]
            and "Kenapa banyak yang pindah ke sini?" in nb_c["hook"]
            and nb_c["durasi"] == {"min": 15, "max": 90})

        # ------------------------------------------------------------------ 5
        print("== 5. HTTP Console: papan, detail gone, brief 2 sumber, XSS, on-demand ==")
        client = TestClient(rc.app)

        # 5a. Papan nampilin yang aktif (masih-ada & clippo-clp100) + label sumber,
        #     dan GA nampilin yang gone (bakal-ilang & clippo-clp200)
        r_board = client.get("/campaign", headers=AUTH)
        cek("GET /campaign -> 200", r_board.status_code == 200)
        html_board = r_board.text
        cek("campaign aktif konten & clippo muncul di papan (jalur sukses)",
            "masih-ada" in html_board and "clippo-clp100" in html_board)
        cek("campaign gone GA muncul di papan aktif (jalur gagal/filter)",
            "bakal-ilang" not in html_board and "clippo-clp200" not in html_board)
        cek("label sumber 'konten' dan 'clippo' muncul di papan",
            "<span class=chip>konten</span>" in html_board
            and "<span class=chip>clippo</span>" in html_board)

        # 5b. Halaman detail campaign yang udah gone -> 200 + pesan jelas
        r_gone = client.get("/campaign/bakal-ilang", headers=AUTH)
        cek("GET /campaign/bakal-ilang (gone) -> 200",
            r_gone.status_code == 200)
        cek("halaman detail gone nulis 'udah ga ada di marketplace'",
            "udah ga ada di marketplace" in r_gone.text)
        cek("aset baris gone tetep tampil di halaman detailnya",
            "youtu.be/bahan123" in r_gone.text)

        # 5c. Halaman detail Clippo nampilin wajib/boleh/dilarang/materi/hook/catatan
        #     + escape <script> + tolak link javascript:
        r_clp = client.get("/campaign/clippo-clp100", headers=AUTH)
        cek("GET /campaign/clippo-clp100 -> 200", r_clp.status_code == 200)
        h_clp = r_clp.text
        cek("detail Clippo nampilin item Wajib, Boleh, Dilarang",
            "Wajib pakai logo" in h_clp
            and "Wajib kualitas HD" in h_clp
            and "Dilarang reupload mentah" in h_clp)
        cek("detail Clippo nampilin Materi http/https sebagai link + tanda wajib",
            "href='https://drive.google.com/drive/folders/abc'" in h_clp
            and "Footage Utama" in h_clp
            and "wajib</span>" in h_clp)
        cek("URL materi skema javascript: TIDAK dirender jadi <a href=...>",
            "href='javascript:" not in h_clp and 'href="javascript:' not in h_clp
            and "Link Jahat" in h_clp)
        cek("teks <script> di brief Clippo keluar ter-escape (&lt;script&gt;)",
            "&lt;script&gt;alert(&#x27;xss-clippo&#x27;)&lt;/script&gt;" in h_clp
            and "<script>alert('xss-clippo')</script>" not in h_clp)

        # 5d. On-demand brief konten.com:
        #     - Pertama: suntik fetcher sukses -> brief ditarik, disimpen, dan tampil
        dipanggil = []
        _lama_fetcher = camp.FETCH_BRIEF
        try:
            def _mock_fetch_ok(source, slug, cid=""):
                dipanggil.append((source, slug))
                return raw_konten

            camp.FETCH_BRIEF = _mock_fetch_ok
            r_k1 = client.get("/campaign/masih-ada", headers=AUTH)
            cek("GET /campaign/masih-ada (on-demand sukses) -> 200",
                r_k1.status_code == 200 and len(dipanggil) == 1)
            h_k1 = r_k1.text
            cek("detail konten.com nampilin Wajib, Boleh, Dilarang, Caption, Ide hook, Catatan",
                "Wajib tampilkan produk di 3 detik awal" in h_k1
                and "Boleh tambah efek transisi" in h_k1
                and "Dilarang mengandung SARA" in h_k1
                and "Beli sekarang di keranjang kuning" in h_k1
                and "Ceritakan pengalaman pakai produk ini" in h_k1
                and "Pastikan resolusi minimal 1080p" in h_k1)
            cek("detail konten.com: link http jadi <a>, ftp:// BUKAN <a>",
                "href='https://youtu.be/materi-konten-1'" in h_k1
                and "href='ftp://" not in h_k1
                and "Materi FTP" in h_k1)
            cek("teks <script> di brief konten.com keluar ter-escape",
                "&lt;script&gt;alert(&#x27;xss-konten&#x27;)&lt;/script&gt;" in h_k1
                and "<script>alert('xss-konten')</script>" not in h_k1)

            # Buka lagi sebelum 6 jam -> ambil dari DB, ga manggil fetcher lagi
            r_k2 = client.get("/campaign/masih-ada", headers=AUTH)
            cek("brief < 6 jam dipakai dari cache DB (fetcher ga dipanggil ulang)",
                r_k2.status_code == 200 and len(dipanggil) == 1)

            # Tua-kan brief_at > 6 jam + suntik fetcher yang RAISE error ->
            # WAJIB 200 (jangan 500), tampilkan brief tersimpan + pesan error jelas
            conn.execute("UPDATE campaigns SET brief_at=? WHERE slug='masih-ada'",
                         (time.time() - 7 * 3600,))
            conn.commit()

            # Dengan CLIPPER_BRIEF_OFFLINE=1, ensure_brief TIDAK BOLEH manggil fetcher
            panggilan_offline = []
            os.environ["CLIPPER_BRIEF_OFFLINE"] = "1"
            try:
                b_off, err_off = camp.ensure_brief(
                    conn, "masih-ada",
                    fetcher=lambda *a: panggilan_offline.append(a))
            finally:
                os.environ.pop("CLIPPER_BRIEF_OFFLINE", None)
            cek("CLIPPER_BRIEF_OFFLINE=1 -> ensure_brief manggil fetcher 0 kali",
                len(panggilan_offline) == 0 and b_off is not None and err_off is None)

            def _mock_fetch_raise(source, slug, cid=""):
                raise RuntimeError("timeout koneksi ke konten.com")

            camp.FETCH_BRIEF = _mock_fetch_raise
            r_k_err = client.get("/campaign/masih-ada", headers=AUTH)
            cek("fetch brief yang raise -> 200 (BUKAN 500)",
                r_k_err.status_code == 200)
            cek("fetch brief yang raise -> nampilin pesan gagal + brief tersimpan tetep tampil",
                "timeout koneksi ke konten.com" in r_k_err.text
                and "Wajib tampilkan produk di 3 detik awal" in r_k_err.text)

            # RuntimeError dengan angka "404" di URL/query TIDAK BOLEH nandain 'gone'
            def _mock_fetch_timeout_404_url(source, slug, cid=""):
                raise RuntimeError(
                    "fetch failed: https://konten.com/api/campaigns/masih-ada?t=1404 timeout after 30s"
                )

            _, err_404_url = camp.ensure_brief(
                conn, "masih-ada", fetcher=_mock_fetch_timeout_404_url)
            cek("RuntimeError dengan '404' di URL -> status tetep 'active' & masih di board()",
                err_404_url is not None
                and camp.get(conn, "masih-ada")["status"] == "active"
                and "masih-ada" in [r["slug"] for r in camp.board(conn)])

            # Suntik fetcher yang jawab 404 (BriefNotFound) waktu narik brief ->
            # baris ditandai status='gone' dan halaman nulis 'udah ga ada di marketplace'
            def _mock_fetch_404(source, slug, cid=""):
                raise camp.BriefNotFound("404: campaign dicopot")

            camp.FETCH_BRIEF = _mock_fetch_404
            r_k_404 = client.get("/campaign/masih-ada", headers=AUTH)
            cek("fetch brief BriefNotFound -> 200 + baris ditandai status='gone' & ilang dari board()",
                r_k_404.status_code == 200
                and camp.get(conn, "masih-ada")["status"] == "gone"
                and "masih-ada" not in [r["slug"] for r in camp.board(conn)]
                and "udah ga ada di marketplace" in r_k_404.text)
        finally:
            camp.FETCH_BRIEF = _lama_fetcher

        # ------------------------------------------------------------------ 6
        print("== 6. POST /campaign/refresh: dua sumber independen ==")
        _lama_refresh = camp.refresh
        _lama_refresh_clippo = camp.refresh_clippo
        try:
            # Skenario A: konten.com sukses, Clippo gagal -> hasil konten.com masuk!
            def _ok_konten(c):
                return _lama_refresh(c, [{
                    "slug": "baru-dari-konten", "id": "camp-999",
                    "title": "Baru Dari Konten", "brand": "BrandK",
                    "status": "active", "cpm_tiktok": 12000,
                    "budget_bar_percent_override": 90,
                }])

            def _fail_clippo(c):
                raise RuntimeError("playwright gagal buka clippo")

            camp.refresh = _ok_konten
            camp.refresh_clippo = _fail_clippo
            r_ref1 = client.post("/campaign/refresh", headers=AUTH,
                                 follow_redirects=False)
            cek("POST /campaign/refresh saat Clippo gagal -> 200 + pesan error clippo",
                r_ref1.status_code == 200
                and "clippo ga kebaca" in r_ref1.text
                and "konten.com: 1 campaign" in r_ref1.text)
            cek("gagal Clippo GA ngebatalin hasil konten.com",
                camp.get(conn, "baru-dari-konten") is not None
                and "baru-dari-konten" in r_ref1.text)

            # Skenario B: konten.com gagal, Clippo sukses -> hasil Clippo masuk!
            def _fail_konten(c):
                raise RuntimeError("konten.com 502 bad gateway")

            def _ok_clippo(c):
                return _lama_refresh_clippo(c, [{
                    "id": "clp999", "title": "Baru Dari Clippo",
                    "status": 3, "ratePerKView": 4000, "rateUnit": 1000,
                    "budgetPercentage": 88.0,
                }])

            camp.refresh = _fail_konten
            camp.refresh_clippo = _ok_clippo
            r_ref2 = client.post("/campaign/refresh", headers=AUTH,
                                 follow_redirects=False)
            cek("POST /campaign/refresh saat konten.com gagal -> 200 + pesan error konten.com",
                r_ref2.status_code == 200
                and "konten.com ga kebaca" in r_ref2.text
                and "clippo: 1 campaign" in r_ref2.text)
            cek("gagal konten.com GA ngebatalin hasil Clippo",
                camp.get(conn, "clippo-clp999") is not None
                and "clippo-clp999" in r_ref2.text)

            # Skenario C: dua-duanya sukses -> 303 redirect ke /campaign
            camp.refresh = _ok_konten
            camp.refresh_clippo = _ok_clippo
            r_ref3 = client.post("/campaign/refresh", headers=AUTH,
                                 follow_redirects=False)
            cek("POST /campaign/refresh saat dua-duanya sukses -> 303 ke /campaign",
                r_ref3.status_code == 303
                and r_ref3.headers.get("location") == "/campaign")

            # -------------------------------------------------------------- 7
            print("== 7. CLI --refresh dan --no-clippo ==")
            jejak_cli = []
            camp.refresh = lambda c: (jejak_cli.append("konten") or (1, 0, 1))
            camp.refresh_clippo = lambda c: (jejak_cli.append("clippo") or (1, 0, 1))
            rc_cli1 = camp.main(["--refresh"])
            cek("CLI --refresh manggil konten + clippo",
                rc_cli1 == 0 and jejak_cli == ["konten", "clippo"])
            jejak_cli.clear()
            rc_cli2 = camp.main(["--refresh", "--no-clippo"])
            cek("CLI --refresh --no-clippo cuma manggil konten",
                rc_cli2 == 0 and jejak_cli == ["konten"])
        finally:
            camp.refresh = _lama_refresh
            camp.refresh_clippo = _lama_refresh_clippo

        print()
        print("_v96: %d ok, %d gagal" % (ok, len(gagal)))
        if gagal:
            for g in gagal:
                print("  - %s" % g)
            return 1
        return 0
    finally:
        shutil.rmtree(_tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
