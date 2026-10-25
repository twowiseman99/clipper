"""_v97: label sumber berwarna + saringan per sumber di papan campaign.

Semua cek jalan in-memory pakai FastAPI TestClient + DB sementara (tempdir)
tanpa akses jaringan, mengikuti pola _v96.
"""
import base64
import html as html_lib
import os
import re
import shutil
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

_tmp = tempfile.mkdtemp(prefix="v97_")
os.environ["CLIPPER_CONSOLE_USERS"] = "tester:sandi-v97"
os.environ["CLIPPER_QUEUE_DB"] = os.path.join(_tmp, "queue.db")
os.environ["CLIPPER_CAMPAIGN_DB"] = os.path.join(_tmp, "campaigns.db")
os.environ["CLIPPER_CAMPAIGN_ASSETS"] = os.path.join(_tmp, "aset")
os.environ["CLIPPER_BRIEF_OFFLINE"] = "1"

import campaigns as camp                    # noqa: E402
import render_console as rc                 # noqa: E402
from fastapi.testclient import TestClient   # noqa: E402

AUTH = {
    "Authorization": "Basic " + base64.b64encode(b"tester:sandi-v97").decode()
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


def _baris_tr(html_teks, slug):
    """Ambil blok <tr>...</tr> untuk satu slug di papan."""
    for m in re.finditer(r"<tr[^>]*>.*?</tr>", html_teks, flags=re.DOTALL):
        blok = m.group(0)
        if ("/campaign/%s'" % slug) in blok or ('/campaign/%s"' % slug) in blok:
            return blok
    return ""


def main():
    try:
        camp.DB_PATH = os.environ["CLIPPER_CAMPAIGN_DB"]
        camp.ASSET_DIR = os.environ["CLIPPER_CAMPAIGN_ASSETS"]

        conn = camp.connect()
        # Seed 2 konten aktif + 2 clippo aktif (satu dari tiap sumber ditandai garap)
        camp.refresh(conn, [
            {
                "slug": "konten-garap",
                "id": "k-1",
                "title": "Konten Garap Satu",
                "brand": "BrandKontenA",
                "status": "active",
                "cpm_tiktok": 10000,
                "budget_bar_percent_override": 90,
                "min_views": 5000,
                "min_video_duration": 20,
                "platform": ["tiktok"],
                "description": "brief konten garap",
            },
            {
                "slug": "konten-biasa",
                "id": "k-2",
                "title": "Konten Biasa Dua",
                "brand": "BrandKontenB",
                "status": "active",
                "cpm_tiktok": 8000,
                "budget_bar_percent_override": 80,
                "min_views": 5000,
                "min_video_duration": 20,
                "platform": ["tiktok"],
                "description": "brief konten biasa",
            },
        ])
        camp.refresh_clippo(conn, [
            {
                "id": "clp1",
                "title": "Clippo Garap Satu",
                "status": 3,
                "ratePerKView": 9000,
                "rateUnit": 1000,
                "budgetPercentage": 85.0,
                "minDuration": 15,
                "platformSupported": [0],
                "creator": {"user": {"name": "BrandClippoA"}},
            },
            {
                "id": "clp2",
                "title": "Clippo Biasa Dua",
                "status": 3,
                "ratePerKView": 7000,
                "rateUnit": 1000,
                "budgetPercentage": 75.0,
                "minDuration": 15,
                "platformSupported": [0],
                "creator": {"user": {"name": "BrandClippoB"}},
            },
        ])
        camp.pick(conn, "konten-garap", "garap", who="tester", note="ambil konten")
        camp.pick(conn, "clippo-clp1", "garap", who="tester", note="ambil clippo")

        SLUGS_KONTEN = ("konten-garap", "konten-biasa")
        SLUGS_CLIPPO = ("clippo-clp1", "clippo-clp2")
        SLUGS_SEMUA = SLUGS_KONTEN + SLUGS_CLIPPO

        client = TestClient(rc.app)

        # ------------------------------------------------------------------ 1
        print("== 1. Label sumber punya kelas CSS terpisah & ga pakai teal garap ==")
        cek(".src-konten dan .src-clippo ada di STYLE",
            ".src-konten" in rc.STYLE and ".src-clippo" in rc.STYLE)
        blok_src_css = "\n".join(
            baris for baris in rc.STYLE.splitlines()
            if "src-konten" in baris or "src-clippo" in baris
        )
        cek("warna .src-konten/.src-clippo TIDAK memakai --teal milik .garap",
            "var(--teal)" not in blok_src_css
            and "#64BBA8" not in blok_src_css.upper())

        r_all = client.get("/campaign", headers=AUTH)
        cek("GET /campaign -> 200", r_all.status_code == 200)
        h_all = r_all.text

        for s in SLUGS_KONTEN:
            tr = _baris_tr(h_all, s)
            cek("baris %s punya kelas src-konten & teks 'konten' (bukan src-clippo)" % s,
                bool(tr) and "src-konten" in tr and ">konten<" in tr
                and "src-clippo" not in tr)
        for s in SLUGS_CLIPPO:
            tr = _baris_tr(h_all, s)
            cek("baris %s punya kelas src-clippo & teks 'clippo' (bukan src-konten)" % s,
                bool(tr) and "src-clippo" in tr and ">clippo<" in tr
                and "src-konten" not in tr)

        # Sumber ga dikenal jatuh ke chip polos ter-escape
        lbl_asing = rc._label_sumber("sumber<jahat>")
        cek("sumber ga dikenal jatuh ke <span class=chip> ter-escape tanpa src-*",
            lbl_asing == "<span class=chip>sumber&lt;jahat&gt;</span>"
            and "src-" not in lbl_asing)

        # Halaman detail campaign juga pakai label berwarna yang sama
        r_det_k = client.get("/campaign/konten-garap", headers=AUTH)
        r_det_c = client.get("/campaign/clippo-clp1", headers=AUTH)
        cek("detail campaign konten punya label src-konten",
            r_det_k.status_code == 200
            and "<span class='src-konten'><span class=chip>konten</span></span>" in r_det_k.text
            and "<span class='src-clippo'>" not in r_det_k.text)
        cek("detail campaign clippo punya label src-clippo",
            r_det_c.status_code == 200
            and "<span class='src-clippo'><span class=chip>clippo</span></span>" in r_det_c.text
            and "<span class='src-konten'>" not in r_det_c.text)

        # ------------------------------------------------------------------ 2
        print("== 2. Saringan ?sumber= (kosong, clippo, konten) & hitungan ==")
        for jalur in ("/campaign", "/campaign?sumber="):
            resp = client.get(jalur, headers=AUTH)
            cek("GET %s -> 200 & tampilkan keempat baris" % jalur,
                resp.status_code == 200
                and all(s in resp.text for s in SLUGS_SEMUA))
            cek("GET %s subjudul '4 campaign kelihatan'" % jalur,
                "4 campaign kelihatan" in resp.text)
            cek("GET %s pil sumber nunjukin Semua sumber (4), konten.com (2), Clippo (2)" % jalur,
                "Semua sumber (4)" in resp.text
                and "konten.com (2)" in resp.text
                and "Clippo (2)" in resp.text)

        r_clp = client.get("/campaign?sumber=clippo", headers=AUTH)
        cek("GET /campaign?sumber=clippo -> 200", r_clp.status_code == 200)
        h_clp = r_clp.text
        cek("?sumber=clippo nampilin SEMUA slug clippo",
            all(s in h_clp for s in SLUGS_CLIPPO))
        cek("?sumber=clippo TIDAK nampilin satu pun slug konten",
            all(s not in h_clp for s in SLUGS_KONTEN))
        cek("?sumber=clippo subjudul '2 campaign kelihatan'",
            "2 campaign kelihatan" in h_clp)
        cek("?sumber=clippo hitungan pil tetep untuk status aktif: (4), (2), (2)",
            "Semua sumber (4)" in h_clp
            and "konten.com (2)" in h_clp
            and "Clippo (2)" in h_clp)
        cek("?sumber=clippo link pil status nyimpen sumber=clippo",
            "href='/campaign?saring=garap&sumber=clippo'" in h_clp)

        r_kon = client.get("/campaign?sumber=konten", headers=AUTH)
        cek("GET /campaign?sumber=konten -> 200", r_kon.status_code == 200)
        h_kon = r_kon.text
        cek("?sumber=konten nampilin SEMUA slug konten",
            all(s in h_kon for s in SLUGS_KONTEN))
        cek("?sumber=konten TIDAK nampilin satu pun slug clippo",
            all(s not in h_kon for s in SLUGS_CLIPPO))
        cek("?sumber=konten subjudul '2 campaign kelihatan'",
            "2 campaign kelihatan" in h_kon)
        cek("?sumber=konten link pil status nyimpen sumber=konten",
            "href='/campaign?saring=garap&sumber=konten'" in h_kon)

        # ------------------------------------------------------------------ 3
        print("== 3. Kombinasi saring + sumber & hitungan pil per status ==")
        r_gc = client.get("/campaign?saring=garap&sumber=clippo", headers=AUTH)
        cek("GET /campaign?saring=garap&sumber=clippo -> 200",
            r_gc.status_code == 200)
        h_gc = r_gc.text
        cek("?saring=garap&sumber=clippo cuma nampilin clippo-clp1",
            "clippo-clp1" in h_gc
            and "clippo-clp2" not in h_gc
            and "konten-garap" not in h_gc
            and "konten-biasa" not in h_gc)
        cek("?saring=garap&sumber=clippo subjudul '1 campaign kelihatan'",
            "1 campaign kelihatan" in h_gc)
        cek("?saring=garap&sumber=clippo hitungan pil sumber sesuai status garap: (2), (1), (1)",
            "Semua sumber (2)" in h_gc
            and "konten.com (1)" in h_gc
            and "Clippo (1)" in h_gc)
        cek("?saring=garap&sumber=clippo link pil sumber nyimpen saring=garap",
            "href='/campaign?saring=garap&sumber=konten'" in h_gc
            and "href='/campaign?saring=garap&sumber='" in h_gc)

        r_gk = client.get("/campaign?saring=garap&sumber=konten", headers=AUTH)
        cek("?saring=garap&sumber=konten cuma nampilin konten-garap",
            r_gk.status_code == 200
            and "konten-garap" in r_gk.text
            and "konten-biasa" not in r_gk.text
            and "clippo-clp1" not in r_gk.text
            and "clippo-clp2" not in r_gk.text
            and "1 campaign kelihatan" in r_gk.text)

        # ------------------------------------------------------------------ 4
        print("== 4. Input sumber liar / XSS (<script>) dianggap kosong & aman ==")
        r_xss = client.get("/campaign", params={"sumber": "<script>"}, headers=AUTH)
        cek("GET /campaign?sumber=<script> -> 200", r_xss.status_code == 200)
        cek("?sumber=<script> nampilin keempat baris & '4 campaign kelihatan'",
            all(s in r_xss.text for s in SLUGS_SEMUA)
            and "4 campaign kelihatan" in r_xss.text)
        cek("string mentah '<script>' TIDAK muncul di HTML",
            "<script>" not in r_xss.text)

        r_liar = client.get("/campaign?sumber=asal-bukan-sumber", headers=AUTH)
        cek("?sumber=asal-bukan-sumber -> 200, tampil semua, nilai liar ga dipantulin",
            r_liar.status_code == 200
            and all(s in r_liar.text for s in SLUGS_SEMUA)
            and "asal-bukan-sumber" not in r_liar.text)

        # ------------------------------------------------------------------ 5
        print("== 5. Putusan cepat simpan sumber & tolak open redirect balik ==")
        tr_clp2 = _baris_tr(h_clp, "clippo-clp2")
        m_balik = re.search(r"name=balik value='([^']*)'", tr_clp2)
        nilai_balik = html_lib.unescape(m_balik.group(1)) if m_balik else ""
        cek("form putusan cepat di ?sumber=clippo punya input hidden balik",
            m_balik is not None and "sumber=clippo" in nilai_balik)

        r_pick = client.post(
            "/campaign/clippo-clp2/pick",
            data={"state": "garap", "balik": nilai_balik},
            headers=AUTH,
            follow_redirects=False,
        )
        loc = r_pick.headers.get("location", "")
        cek("POST pick dari tampilan sumber=clippo -> 303",
            r_pick.status_code == 303)
        cek("Location redirect memuat sumber=clippo (dapet %r)" % loc,
            loc.startswith("/campaign?") and "sumber=clippo" in loc)
        cek("keputusan garap tersimpan di DB untuk clippo-clp2",
            camp.get(conn, "clippo-clp2")["pick"] == "garap")

        for jahat in (
            "//evil.com",
            "https://evil.com",
            "http://evil.com/campaign",
            "/evil.com",
            "\\evil.com",
            "saring=garap&next=https://evil.com",
            "saring=garap&sumber=jahat",
            "javascript:alert(1)",
        ):
            r_jahat = client.post(
                "/campaign/clippo-clp2/pick",
                data={"state": "garap", "balik": jahat},
                headers=AUTH,
                follow_redirects=False,
            )
            loc_j = r_jahat.headers.get("location", "")
            cek("balik palsu %r -> 303 ke /campaign (dapet %r)" % (jahat, loc_j),
                r_jahat.status_code == 303 and loc_j == "/campaign")

        # Kontrol negatif auth
        r_noauth = client.get("/campaign?sumber=clippo")
        cek("GET /campaign?sumber=clippo tanpa auth -> 401 & ga bocor slug",
            r_noauth.status_code == 401
            and all(s not in r_noauth.text for s in SLUGS_SEMUA))

        print()
        print("_v97: %d ok, %d gagal" % (ok, len(gagal)))
        if gagal:
            for g in gagal:
                print("  - %s" % g)
            return 1
        return 0
    finally:
        shutil.rmtree(_tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
