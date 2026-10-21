"""Papan campaign: daftar campaign marketplace, mana yang digarap, dan asetnya.

Kenapa ada: `campaign_watch.py` cuma NGABARIN campaign baru lewat Discord dan
ga nyimpen apa pun selain daftar id yang udah pernah dikabarin. Operator minta
tempat buat NGELIHAT semuanya sekaligus, milih mana yang digarap, dan naro
bahan (link video, gambar, BGM) di bawah campaign-nya masing-masing biar ga
nyampur. Itu state, jadi butuh tabel, bukan pesan.

Tiga hal yang diukur dulu di kotak ini sebelum file ini ditulis, karena
masing-masing ngubah desainnya:

1. **Daftar campaign ga butuh login.** `konten.com/api/campaigns` balik 114
   campaign (50 `active`) lewat HTTP 200 cuma pakai User-Agent browser. Jadi
   papan ini bisa nampilin semuanya tanpa kredensial siapa pun. Yang butuh
   sesi cuma SUBMIT, dan itu bukan kerjaan file ini.

2. **`rate_per_million` NAMANYA BOHONG.** Halaman campaign nulis
   "Rp10.000 / 1K views" buat nilai 10000 yang sama. Jadi angkanya itu rupiah
   per **SERIBU** views, bukan per sejuta — beda 1000x. Kolomnya di UI
   dilabelin `CPM` (minta operator: "kita semua udah paham artinya") dengan
   satuan per-1.000 ditulis di hint bawah tabel, biar ga ada yang ngitung
   pakai arti yang salah. 56 dari 111 campaign cuma punya field ini;
   `cpm_tiktok` dkk itu
   override per platform kalau ada.

3. **CPM doang nipu.** Diukur barusan: campaign CPM tertinggi (Rp15.000,
   Krakatau) sisa budgetnya cuma **6%** — duitnya hampir abis, jadi rate
   gede itu ga bisa diambil. Makanya urutan default papan ini SKOR
   = `cpm x sisa_budget%`, pilihan operator, bukan CPM mentah. Keduanya
   tetep ditampilin apa adanya di kolom sendiri.

`min_views` ditandain merah kalau di atas 10.000: itu lantai sebelum klip
dibayar sama sekali, dan di akun kecil lantai segitu artinya kerja gratis.

State yang disimpen di sini:
    campaigns  — salinan daftar dari marketplace (di-refresh, bisa basi)
    picks      — keputusan kita: 'garap' atau 'lewat', siapa, kapan
    assets     — bahan per campaign: link video, gambar, BGM

Yang SENGAJA ga ada di sini: submit ke marketplace, dan nebak boleh/ga boleh
sebuah video dipakai. Lihat `konten.py` buat aturan brief yang bisa dicek.
"""
import json
import os
import re
import sqlite3
import subprocess
import time

BASE = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.environ.get(
    "CLIPPER_CAMPAIGN_DB", os.path.join(BASE, "campaigns.db"))

# Folder aset per campaign. DI LUAR media/ dan jobs/ dengan sengaja:
# autoclean.py ngehapus isi dua folder itu tiap jam 5 pagi karena isinya
# hasil unduhan yang bisa diambil ulang. Gambar dan BGM yang di-UPLOAD
# operator ga bisa diambil ulang dari mana pun, jadi naro di situ sama
# dengan ngasih umur 24 jam ke aset yang dia upload sendiri.
ASSET_DIR = os.environ.get(
    "CLIPPER_CAMPAIGN_ASSETS", os.path.join(BASE, "assets", "campaign"))

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
LIST_URL = "https://konten.com/api/campaigns"
SITE = "https://konten.com/campaigns/"

# Lantai views yang bikin klip ga dibayar sama sekali di bawahnya. Di atas
# angka ini kolomnya merah. Operator: "min_views dikasih warna merah kalau
# >10rb".
MIN_VIEWS_MERAH = int(os.environ.get("CLIPPER_MIN_VIEWS_RED", "10000"))

KIND = ("video_link", "image", "bgm")
STATE = ("garap", "lewat")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    slug        TEXT PRIMARY KEY,
    cid         TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL DEFAULT '',
    brand       TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT '',
    platform    TEXT NOT NULL DEFAULT '[]',
    cpm         INTEGER NOT NULL DEFAULT 0,
    cpm_source  TEXT NOT NULL DEFAULT '',
    budget_left INTEGER,
    min_views   INTEGER,
    min_seconds INTEGER,
    content_type TEXT NOT NULL DEFAULT '',
    campaign_type TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT '',
    hashtags    TEXT NOT NULL DEFAULT '[]',
    description TEXT NOT NULL DEFAULT '',
    deadline    TEXT NOT NULL DEFAULT '',
    fetched_at  REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS picks (
    slug   TEXT PRIMARY KEY,
    state  TEXT NOT NULL,
    who    TEXT NOT NULL DEFAULT '',
    note   TEXT NOT NULL DEFAULT '',
    at     REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS assets (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    slug  TEXT NOT NULL,
    kind  TEXT NOT NULL,
    value TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    who   TEXT NOT NULL DEFAULT '',
    at    REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS assets_slug ON assets(slug, kind);
"""


def connect(path=None):
    conn = sqlite3.connect(path or DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


# --------------------------------------------------------------- marketplace

def _get(url, timeout=40):
    """curl, bukan urllib: urllib default dapet 403 blanket dari host ini.

    UA browser itu load-bearing, bukan cargo cult — ini udah keukur di
    campaign_watch.py.
    """
    r = subprocess.run(["curl", "-s", "-m", str(timeout), "-A", UA, url],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError("fetch gagal: %s" % url)
    return json.loads(r.stdout)


def cpm_of(c):
    """(angka, dari mana). Rupiah per SERIBU views, lihat docstring modul.

    Ambil yang paling tinggi antar platform: kita yang milih mau posting di
    mana, jadi plafonnya yang nentuin campaign ini layak digarap.
    """
    per = {k: c.get("cpm_" + k) for k in ("tiktok", "instagram", "youtube",
                                          "threads")}
    ada = {k: v for k, v in per.items() if v}
    if ada:
        k = max(ada, key=lambda k: ada[k])
        return int(ada[k]), k
    r = c.get("rate_per_million")
    return (int(r), "rate_per_million") if r else (0, "")


def score(cpm, budget_left):
    """Skor urutan papan: cpm x sisa budget. Pilihan operator.

    Alasannya terukur: CPM tertinggi di marketplace (Rp15.000) nempel di
    campaign yang sisa budgetnya 6%, jadi rate-nya ga bisa diambil. Sisa
    budget yang ga diketahui dihitung 0 — bukan 100 — karena "ga tau" ga
    boleh naikin sesuatu ke puncak daftar.
    """
    return int(round(int(cpm or 0) * (int(budget_left or 0) / 100.0)))


def refresh(conn, campaigns=None):
    """Tarik daftar campaign dan simpen. Balik (jumlah, baru, aktif).

    Campaign yang ilang dari API TIDAK dihapus dari tabel: kalau sebuah
    campaign udah kita tandain garap dan punya aset, barisnya harus tetep
    ada walau marketplace nyopot dia dari daftar. Status-nya bakal basi, dan
    halaman yang nampilin wajib ngomong kapan terakhir di-refresh.
    """
    if campaigns is None:
        campaigns = _get(LIST_URL)["campaigns"]
    lama = {r["slug"] for r in conn.execute("SELECT slug FROM campaigns")}
    now = time.time()
    baru = 0
    for c in campaigns:
        slug = c.get("slug") or ""
        if not slug:
            continue
        cpm, src = cpm_of(c)
        bl = c.get("budget_bar_percent_override")
        st = c.get("status") or ""
        if c.get("emergency_stopped"):
            st = "emergency_stopped"
        conn.execute(
            "INSERT INTO campaigns (slug, cid, title, brand, category, platform,"
            " cpm, cpm_source, budget_left, min_views, min_seconds,"
            " content_type, campaign_type, status, hashtags, description,"
            " deadline, fetched_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(slug) DO UPDATE SET"
            " cid=excluded.cid, title=excluded.title, brand=excluded.brand,"
            " category=excluded.category, platform=excluded.platform,"
            " cpm=excluded.cpm, cpm_source=excluded.cpm_source,"
            " budget_left=excluded.budget_left, min_views=excluded.min_views,"
            " min_seconds=excluded.min_seconds,"
            " content_type=excluded.content_type,"
            " campaign_type=excluded.campaign_type, status=excluded.status,"
            " hashtags=excluded.hashtags, description=excluded.description,"
            " deadline=excluded.deadline, fetched_at=excluded.fetched_at",
            (slug, c.get("id") or "", c.get("title") or "",
             c.get("brand") or "", c.get("category") or "",
             json.dumps(c.get("platform") or [], ensure_ascii=False),
             cpm, src,
             int(bl) if bl is not None else None,
             c.get("min_views"), c.get("min_video_duration"),
             c.get("content_type") or "", c.get("campaign_type") or "", st,
             json.dumps(c.get("hashtags") or [], ensure_ascii=False),
             (c.get("description") or "")[:4000],
             str(c.get("deadline") or ""), now))
        if slug not in lama:
            baru += 1
    conn.commit()
    aktif = sum(1 for c in campaigns if (c.get("status") == "active"
                                         and not c.get("emergency_stopped")))
    return len(campaigns), baru, aktif


def last_refresh(conn):
    row = conn.execute("SELECT MAX(fetched_at) AS t FROM campaigns").fetchone()
    return row["t"] or 0.0


# -------------------------------------------------------------------- papan

def board(conn, hanya_aktif=True, state=None, limit=200):
    """Baris papan, udah diurut skor turun.

    Tiap baris bawa `score`, `pick` (garap/lewat/None) dan `n_asset` biar
    halaman ga perlu query per baris.
    """
    q = ("SELECT c.*, p.state AS pick, p.who AS pick_who,"
         " (SELECT COUNT(*) FROM assets a WHERE a.slug=c.slug) AS n_asset"
         " FROM campaigns c LEFT JOIN picks p ON p.slug=c.slug")
    where, args = [], []
    if hanya_aktif:
        where.append("c.status='active'")
    if state:
        where.append("p.state=?")
        args.append(state)
    if where:
        q += " WHERE " + " AND ".join(where)
    rows = [dict(r) for r in conn.execute(q, args)]
    for r in rows:
        r["score"] = score(r["cpm"], r["budget_left"])
        r["platform"] = json.loads(r["platform"] or "[]")
        r["hashtags"] = json.loads(r["hashtags"] or "[]")
        r["url"] = SITE + r["slug"]
        r["min_views_merah"] = bool(r["min_views"]
                                    and r["min_views"] > MIN_VIEWS_MERAH)
    rows.sort(key=lambda r: (-r["score"], -r["cpm"]))
    return rows[:limit]


def get(conn, slug):
    row = conn.execute(
        "SELECT c.*, p.state AS pick, p.who AS pick_who, p.note AS pick_note"
        " FROM campaigns c LEFT JOIN picks p ON p.slug=c.slug"
        " WHERE c.slug=?", (slug,)).fetchone()
    if not row:
        return None
    r = dict(row)
    r["score"] = score(r["cpm"], r["budget_left"])
    r["platform"] = json.loads(r["platform"] or "[]")
    r["hashtags"] = json.loads(r["hashtags"] or "[]")
    r["url"] = SITE + r["slug"]
    r["min_views_merah"] = bool(r["min_views"]
                                and r["min_views"] > MIN_VIEWS_MERAH)
    return r


def pick(conn, slug, state, who="", note=""):
    """Tandain campaign 'garap' atau 'lewat'. state=None ngapus tandanya."""
    if state is None:
        conn.execute("DELETE FROM picks WHERE slug=?", (slug,))
        conn.commit()
        return None
    if state not in STATE:
        raise ValueError("state harus salah satu dari %s" % (STATE,))
    conn.execute(
        "INSERT INTO picks (slug, state, who, note, at) VALUES (?,?,?,?,?)"
        " ON CONFLICT(slug) DO UPDATE SET state=excluded.state,"
        " who=excluded.who, note=excluded.note, at=excluded.at",
        (slug, state, who, note, time.time()))
    conn.commit()
    return state


# -------------------------------------------------------------------- aset

def safe_slug(s):
    """Slug yang aman dipakai jadi nama folder.

    Slug datang dari URL yang diketik orang, jadi dia input yang ga
    dipercaya. `../../etc` sebagai slug bakal nulis aset di luar folder
    aset; ini yang nahan.
    """
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", (s or "").strip()).strip("-.")
    return s[:120] or "tanpa-slug"


def asset_dir(slug):
    d = os.path.join(ASSET_DIR, safe_slug(slug))
    os.makedirs(d, exist_ok=True)
    return d


def save_upload(slug, kind, filename, data):
    """Tulis file upload ke folder campaign. Balik path absolutnya.

    Nama file yang dikirim browser ga dipercaya sama sekali: dipakai cuma
    buat ekstensinya DAN satu kata mood, badannya diganti timestamp. Nama kayak
    `../../job.py` ga bisa keluar dari folder aset karena ga ada satu pun
    bagian nama asli yang ikut ke path.

    BUG YANG KETANGKEP DI RENDER NYATA, bukan di tes: nama diganti total
    jadi `bgm_<timestamp>.mp3`, dan `bgm._from_filename` baca mood DARI
    NAMA FILE -- jadi tiap BGM yang diupload selalu kebaca mood kosong dan
    pemeriksa tabrakan register MATI PERMANEN. Terukur: upload lagu
    `hype_dj_nansuya...` ke klip preset `sedih` (emotional) jalan mulus
    tanpa satu pun warning, padahal `bgm._clashes('emotional','hype')` itu
    True. Jadi satu kata mood dari nama asli WAJIB ikut -- dicocokin ke
    daftar mood yang sah (bukan teks bebas), supaya nama dari browser tetep
    ga bisa nyumbang karakter sembarangan ke path.
    """
    if kind not in KIND:
        raise ValueError("kind ga dikenal: %r" % kind)
    ext = os.path.splitext(filename or "")[1].lower()
    ext = ext if re.fullmatch(r"\.[A-Za-z0-9]{1,5}", ext or "") else ""
    mood = mood_dari_nama(filename) if kind == "bgm" else ""
    nama = "%s_%s%d%s" % (kind, (mood + "_") if mood else "",
                          int(time.time() * 1000), ext)
    path = os.path.join(asset_dir(slug), nama)
    with open(path, "wb") as f:
        f.write(data)
    return path


def mood_dari_nama(filename):
    """Satu kata mood yang SAH dari nama file upload, atau "".

    Daftarnya diambil dari bgm.MOODS, bukan ditulis ulang di sini: dua
    daftar mood yang kembar bakal lepas pelan-pelan, dan yang rusak nanti
    diam -- mood ga kekenalin, peringatan tabrakan ga muncul, klip duka
    dapet lagu jedag-jedug.
    """
    try:
        import bgm
        sah = set(bgm.MOODS)
    except Exception:
        return ""
    for kata in re.split(r"[^A-Za-z]+", (filename or "").lower()):
        if kata in sah:
            return kata
    return ""


def add_asset(conn, slug, kind, value, label="", who=""):
    if kind not in KIND:
        raise ValueError("kind ga dikenal: %r" % kind)
    cur = conn.execute(
        "INSERT INTO assets (slug, kind, value, label, who, at)"
        " VALUES (?,?,?,?,?,?)",
        (slug, kind, value, label, who, time.time()))
    conn.commit()
    return cur.lastrowid


def assets(conn, slug, kind=None):
    if kind:
        rows = conn.execute(
            "SELECT * FROM assets WHERE slug=? AND kind=? ORDER BY id DESC",
            (slug, kind)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM assets WHERE slug=? ORDER BY id DESC",
            (slug,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        # File yang udah ga ada di disk ditandain, bukan disembunyiin:
        # baris yang ilang diem-diem bikin orang ngira dia ga pernah upload.
        d["ada"] = (d["kind"] == "video_link") or os.path.exists(d["value"])
        out.append(d)
    return out


def remove_asset(conn, asset_id, slug=None):
    """Hapus satu aset. File di disk ikut dihapus kalau dia di folder aset.

    Pembatas foldernya penting: aset bisa nunjuk file lain di kotak ini
    (misal BGM bawaan di background_music/), dan tombol hapus di halaman
    campaign ga boleh bisa ngehapus itu.
    """
    row = conn.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
    if not row or (slug and row["slug"] != slug):
        return False
    if row["kind"] != "video_link":
        p = os.path.abspath(row["value"])
        if p.startswith(os.path.abspath(ASSET_DIR) + os.sep) and os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass
    conn.execute("DELETE FROM assets WHERE id=?", (asset_id,))
    conn.commit()
    return True


# ------------------------------------------------------------------- CLI/tes

def _selfcheck():
    import tempfile
    db = os.path.join(tempfile.mkdtemp(), "c.db")
    conn = connect(db)

    # CPM: plafon antar platform menang, rate_per_million cuma fallback.
    assert cpm_of({"cpm_tiktok": 1000, "cpm_youtube": 7000}) == (7000, "youtube")
    assert cpm_of({"rate_per_million": 2000}) == (2000, "rate_per_million")
    assert cpm_of({}) == (0, "")

    # Skor: CPM gede + budget abis KALAH sama CPM sedang + budget penuh.
    # Ini angka nyata dari marketplace pas file ini ditulis.
    assert score(15000, 6) == 900
    assert score(10000, 98) == 9800
    assert score(5000, None) == 0        # ga tau != bagus

    contoh = [
        {"slug": "krakatau", "id": "a", "title": "Krakatau", "brand": "b",
         "status": "active", "cpm_tiktok": 15000,
         "budget_bar_percent_override": 6, "min_views": 10000},
        {"slug": "karomah", "id": "b", "title": "Karomah", "brand": "b",
         "status": "active", "cpm_tiktok": 10000,
         "budget_bar_percent_override": 98, "min_views": 10000},
        {"slug": "mati", "id": "c", "title": "Paused", "brand": "b",
         "status": "paused", "cpm_tiktok": 99000,
         "budget_bar_percent_override": 100, "min_views": 1000},
        {"slug": "nuface", "id": "d", "title": "NUFACE", "brand": "b",
         "status": "active", "cpm_tiktok": 5000,
         "budget_bar_percent_override": 83, "min_views": 1000},
    ]
    total, baru, aktif = refresh(conn, contoh)
    assert (total, baru, aktif) == (4, 4, 3), (total, baru, aktif)
    # refresh kedua: ga ada yang baru, dan ga ada duplikat
    assert refresh(conn, contoh)[1] == 0

    b = board(conn)
    assert [r["slug"] for r in b] == ["karomah", "nuface", "krakatau"], \
        [r["slug"] for r in b]
    # Campaign CPM paling tinggi justru di URUTAN TERAKHIR. Ini inti papan.
    assert b[-1]["cpm"] == 15000 and b[0]["cpm"] == 10000
    assert b[0]["min_views_merah"] is False or b[0]["min_views"] > 10000
    assert [r["min_views_merah"] for r in b] == [False, False, False]
    # 10.001 merah, 10.000 ENGGA -- batasnya "di atas 10rb".
    refresh(conn, [dict(contoh[1], min_views=10001)])
    assert get(conn, "karomah")["min_views_merah"] is True

    # Pick: garap/lewat/batal
    assert pick(conn, "karomah", "garap", who="oden") == "garap"
    assert get(conn, "karomah")["pick"] == "garap"
    assert len(board(conn, state="garap")) == 1
    pick(conn, "karomah", None)
    assert get(conn, "karomah")["pick"] is None
    try:
        pick(conn, "karomah", "ngawur")
        raise AssertionError("state ngawur harusnya ditolak")
    except ValueError:
        pass

    # Slug ga dipercaya: ga boleh keluar dari folder aset.
    assert safe_slug("../../etc/passwd") == "etc-passwd"
    assert safe_slug("") == "tanpa-slug"
    global ASSET_DIR
    _lama = ASSET_DIR
    ASSET_DIR = os.path.join(os.path.dirname(db), "aset")
    try:
        p = save_upload("../../etc", "image", "../../../job.py", b"x")
        assert os.path.abspath(p).startswith(os.path.abspath(ASSET_DIR) + os.sep), p
        assert "job.py" not in os.path.basename(p), p

        # MOOD WAJIB SELAMAT DARI RENAME. Ini bug yang kena di render nyata:
        # nama diganti total -> bgm._from_filename balik [] -> pemeriksa
        # tabrakan register mati permanen dan klip duka bisa dapet lagu
        # jedag-jedug tanpa satu pun warning.
        import bgm as _bgm
        ph = save_upload("x", "bgm", "hype_dj_nansuya_gang_jedag.mp3", b"m")
        assert _bgm._from_filename(os.path.basename(ph)) == ["hype"], \
            os.path.basename(ph)
        pe = save_upload("x", "bgm", "Emotional Piano Sad.MP3", b"m")
        assert _bgm._from_filename(os.path.basename(pe)) == ["emotional"], \
            os.path.basename(pe)
        # Nama tanpa mood tetep kepakai, cuma ga bisa dikasih peringatan.
        pn = save_upload("x", "bgm", "WhatsApp Audio 2026.mp3", b"m")
        assert _bgm._from_filename(os.path.basename(pn)) == [], \
            os.path.basename(pn)
        # Dan nama jahat tetep ga nyumbang apa pun ke path.
        pj = save_upload("x", "bgm", "../../hype/../../etc/passwd.mp3", b"m")
        assert os.path.abspath(pj).startswith(
            os.path.abspath(ASSET_DIR) + os.sep), pj
        assert "passwd" not in os.path.basename(pj), pj
        assert mood_dari_nama("ngawur_banget.mp3") == ""

        aid = add_asset(conn, "karomah", "image", p, label="poster", who="oden")
        aid2 = add_asset(conn, "karomah", "video_link",
                         "https://youtu.be/xxxx", who="oden")
        got = assets(conn, "karomah")
        assert len(got) == 2 and all(g["ada"] for g in got), got
        assert len(assets(conn, "karomah", "image")) == 1

        # Hapus aset DI LUAR folder aset: barisnya ilang, filenya TETEP ADA.
        luar = os.path.join(os.path.dirname(db), "jangan_hapus.mp3")
        open(luar, "wb").write(b"m")
        aid3 = add_asset(conn, "karomah", "bgm", luar)
        assert remove_asset(conn, aid3) is True
        assert os.path.exists(luar), "file di luar folder aset ikut kehapus"

        # Hapus aset DI DALAM folder aset: file ikut kebuang.
        assert remove_asset(conn, aid) is True
        assert not os.path.exists(p)
        assert remove_asset(conn, aid2, slug="campaign-lain") is False
        assert len(assets(conn, "karomah")) == 1
    finally:
        ASSET_DIR = _lama

    print(json.dumps({"ok": True, "checked": "cpm, skor, papan, pick, aset"}))
    return 0


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="campaigns.py", description=__doc__)
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--refresh", action="store_true",
                   help="tarik daftar campaign dari marketplace")
    p.add_argument("--board", action="store_true", help="cetak papan")
    p.add_argument("--all", action="store_true",
                   help="ikutin campaign yang ga aktif")
    p.add_argument("--limit", type=int, default=20)
    a = p.parse_args(argv)
    if a.selftest:
        return _selfcheck()
    conn = connect()
    if a.refresh:
        total, baru, aktif = refresh(conn)
        print("refresh: %d campaign (%d baru), %d aktif" % (total, baru, aktif))
    if a.board or not a.refresh:
        rows = board(conn, hanya_aktif=not a.all, limit=a.limit)
        print("%-7s %-7s %5s %7s  %s" % ("SKOR", "Rp/1k", "sisa", "minview",
                                         "campaign"))
        for r in rows:
            print("%-7d %-7d %4s%% %7s%s  %s — %s" % (
                r["score"], r["cpm"],
                r["budget_left"] if r["budget_left"] is not None else "?",
                r["min_views"] if r["min_views"] is not None else "?",
                " !" if r["min_views_merah"] else "  ",
                r["title"][:44], r["brand"][:18]))
        print("(%d baris, terakhir refresh %s)" % (
            len(rows),
            time.strftime("%d %b %H:%M", time.localtime(last_refresh(conn)))
            if last_refresh(conn) else "BELUM PERNAH"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
