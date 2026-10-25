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
DETAIL_URL = "https://konten.com/api/campaigns/%s"
SITE = "https://konten.com/campaigns/"
CLIPPO_SITE = "https://app.clippo.id/campaigns/"
CLIPPO_API = "https://app.clippo.id/api/proxy/campaigns"
CLIPPO_PLATFORM = {0: "tiktok", 1: "instagram", 2: "youtube", 3: "threads"}
BRIEF_TTL = 6 * 3600

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
    fetched_at  REAL NOT NULL DEFAULT 0,
    source      TEXT NOT NULL DEFAULT 'konten',
    brief_json  TEXT NOT NULL DEFAULT '',
    brief_at    REAL NOT NULL DEFAULT 0
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
    kolom = {r["name"] for r in conn.execute("PRAGMA table_info(campaigns)")}
    for nama, definisi in (
        ("source", "TEXT NOT NULL DEFAULT 'konten'"),
        ("brief_json", "TEXT NOT NULL DEFAULT ''"),
        ("brief_at", "REAL NOT NULL DEFAULT 0"),
    ):
        if nama not in kolom:
            conn.execute(
                "ALTER TABLE campaigns ADD COLUMN %s %s" % (nama, definisi))
    conn.commit()
    return conn


# --------------------------------------------------------------- marketplace

class BriefNotFound(RuntimeError):
    """Dilempar waktu marketplace jawab 404 buat detail campaign."""


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


def _to_int(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        n = int(round(v))
        return n if n > 0 else None
    s = str(v).strip()
    if s.isdigit():
        n = int(s)
        return n if n > 0 else None
    return None


def _quill_text(val):
    if isinstance(val, str):
        return val
    if isinstance(val, dict) and isinstance(val.get("ops"), list):
        return "".join(
            op.get("insert", "") for op in val["ops"]
            if isinstance(op, dict) and isinstance(op.get("insert"), str)
        )
    if isinstance(val, (list, tuple)):
        return "\n".join(str(x) for x in val if x is not None)
    return ""


def _clean_lines(val):
    """Bersihin string/list/Quill delta jadi list baris tanpa kosong & tanpa HTML."""
    if not val:
        return []
    if isinstance(val, (list, tuple)):
        raw_lines = []
        for item in val:
            raw_lines.extend(_clean_lines(item))
        out = []
        for x in raw_lines:
            if x not in out:
                out.append(x)
        return out
    teks = _quill_text(val) if isinstance(val, dict) else str(val)
    if not teks.strip():
        return []
    # Tag blok HTML diganti newline dulu biar item list/paragraf ga nempel.
    teks = re.sub(r"</?(?:p|div|li|tr|h[1-6])\b[^>]*>|<br\s*/?>", "\n",
                  teks, flags=re.I)
    # Buang semua tag HTML formatting; tag <script> dibiarin utuh sebagai teks
    # supaya di halaman detail wajib ketangkep dan keluar ter-escape oleh _e().
    teks = re.sub(r"</?(?!script\b)[a-zA-Z][a-zA-Z0-9]*\b[^>]*>", " ",
                  teks, flags=re.I)
    for ent, asli in (("&nbsp;", " "), ("&amp;", "&"), ("&quot;", '"'),
                      ("&#39;", "'"), ("&#x27;", "'")):
        teks = teks.replace(ent, asli)
    out = []
    for baris in teks.splitlines():
        s = re.sub(r"[ \t]+", " ", baris).strip()
        s = re.sub(r"^[-•*]\s+", "", s).strip()
        if not s or s in ("-", "–", "—"):
            continue
        if s not in out:
            out.append(s)
    return out


def _clean_str(val):
    lines = _clean_lines(val)
    return " ".join(lines).strip()


def _dedup(seq):
    out = []
    for x in seq:
        if x and x not in out:
            out.append(x)
    return out


def normalize_brief(source, raw):
    """Ubah payload mentah konten.com atau Clippo jadi struktur brief seragam.

    Bentuk kembalian selalu:
      {"wajib": [str], "boleh": [str], "dilarang": [str],
       "materi": [{"url": str, "title": str, "wajib": bool}],
       "caption": [str], "hook": [str], "catatan": [str],
       "durasi": {"min": int|None, "max": int|None}}
    """
    kosong = {
        "wajib": [], "boleh": [], "dilarang": [], "materi": [],
        "caption": [], "hook": [], "catatan": [],
        "durasi": {"min": None, "max": None},
    }
    if not isinstance(raw, dict):
        return kosong

    src = (source or "konten").strip().lower()
    if src == "clippo":
        if "data" in raw and isinstance(raw["data"], dict) and "id" not in raw:
            raw = raw["data"]
        wajib = _dedup(
            _clean_lines(raw.get("requirementsV2") or raw.get("requirements"))
            + _clean_lines(raw.get("contentMainFocus"))
            + _clean_lines(raw.get("wajib"))
            + (["Wajib pasang keranjang kuning"] if raw.get("isYellowCart") else [])
        )
        boleh = _dedup(
            _clean_lines(raw.get("campaignDos"))
            + _clean_lines(raw.get("boleh"))
        )
        dilarang = _dedup(
            _clean_lines(raw.get("campaignDonts"))
            + _clean_lines(raw.get("dilarang"))
        )
        materi = []
        seen_urls = set()
        for m in (raw.get("assetVideoUrlsV2") or raw.get("materi") or []):
            if not isinstance(m, dict):
                continue
            u = str(m.get("url") or "").strip()
            if not u or u in seen_urls:
                continue
            seen_urls.add(u)
            t = _clean_str(m.get("displayText") or m.get("title") or u) or u
            w = bool(m.get("isRequired") if "isRequired" in m else m.get("wajib", False))
            materi.append({"url": u, "title": t, "wajib": w})
        if not materi:
            for u in (raw.get("assetVideoUrls") or []):
                u = str(u or "").strip()
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    materi.append({"url": u, "title": u, "wajib": False})

        caption = _dedup(
            _clean_lines(raw.get("ctaLabel"))
            + _clean_lines(raw.get("caption"))
        )
        ht = [str(h).strip().lstrip("#") for h in (raw.get("hashtags") or [])
              if str(h).strip().lstrip("#")]
        if ht:
            caption = _dedup(caption + [" ".join("#" + h for h in dict.fromkeys(ht))])

        hook = _dedup(
            _clean_lines(raw.get("campaignHook"))
            + _clean_lines(raw.get("hook"))
        )
        catatan = _dedup(
            _clean_lines(raw.get("campaignPurpose"))
            + _clean_lines(raw.get("notes"))
            + _clean_lines(raw.get("catatan"))
        )
        rw = _to_int(raw.get("rewardPerVideo"))
        if rw:
            catatan = _dedup(catatan + [
                "Reward per video: Rp%s" % format(rw, ",d").replace(",", ".")
            ])
        durasi = {
            "min": _to_int(raw.get("minDuration")),
            "max": _to_int(raw.get("maxDuration")),
        }
        return {
            "wajib": wajib, "boleh": boleh, "dilarang": dilarang,
            "materi": materi, "caption": caption, "hook": hook,
            "catatan": catatan, "durasi": durasi,
        }

    # Default: konten.com
    if "campaign" in raw and isinstance(raw["campaign"], dict):
        raw = raw["campaign"]
    bd = raw.get("brief_detail") if isinstance(raw.get("brief_detail"), dict) else {}

    wajib = _dedup(
        _clean_lines(bd.get("elemenWajib"))
        + _clean_lines(bd.get("materialWajib"))
        + _clean_lines(raw.get("wajib"))
    )
    boleh = _dedup(
        _clean_lines(bd.get("bolehDilakukan"))
        + _clean_lines(raw.get("brief_dos"))
        + _clean_lines(raw.get("boleh"))
    )
    dilarang = _dedup(
        _clean_lines(bd.get("dilarangDilakukan"))
        + _clean_lines(raw.get("brief_donts"))
        + _clean_lines(raw.get("dilarang"))
    )

    wajib_default = str(bd.get("materialWajibChoice") or "").strip().lower() in (
        "wajib", "ya", "true", "yes", "1"
    )
    materi = []
    seen_urls = set()
    for m in (bd.get("materi") or raw.get("materi") or []):
        if not isinstance(m, dict):
            continue
        u = str(m.get("url") or "").strip()
        if not u or u in seen_urls:
            continue
        seen_urls.add(u)
        t = _clean_str(m.get("title") or m.get("displayText") or u) or u
        if "wajib" in m:
            w = bool(m["wajib"])
        elif "isRequired" in m:
            w = bool(m["isRequired"])
        else:
            w = wajib_default
        materi.append({"url": u, "title": t, "wajib": w})

    caption = _dedup(
        _clean_lines(bd.get("captionWajib"))
        + _clean_lines(bd.get("caption"))
        + _clean_lines(raw.get("brief_caption"))
        + _clean_lines(bd.get("cta"))
    )
    ht = [str(h).strip().lstrip("#")
          for h in ((bd.get("hashtags") or []) + (raw.get("hashtags") or []))
          if str(h).strip().lstrip("#")]
    if ht:
        caption = _dedup(caption + [" ".join("#" + h for h in dict.fromkeys(ht))])

    tags = bd.get("tagSocialMedia") if isinstance(bd.get("tagSocialMedia"), dict) else {}
    if tags.get("enabled"):
        for plat, akun in tags.items():
            if plat != "enabled" and isinstance(akun, list) and akun:
                bersih = [str(x).strip() for x in akun if str(x).strip()]
                if bersih:
                    caption = _dedup(caption + ["Tag %s: %s" % (plat, ", ".join(bersih))])

    hook = _dedup(
        _clean_lines(bd.get("narasi"))
        + _clean_lines(raw.get("brief_narrative"))
        + _clean_lines(bd.get("hook") or raw.get("hook"))
    )
    catatan = _dedup(
        _clean_lines(bd.get("instruksiBrief"))
        + _clean_lines(raw.get("brief_instructions"))
        + _clean_lines(bd.get("penjelasanBrand"))
        + _clean_lines(bd.get("tujuanCampaign"))
        + _clean_lines(raw.get("brief_goal"))
        + _clean_lines(raw.get("catatan"))
    )
    durasi = {
        "min": _to_int(raw.get("min_video_duration")) or _to_int(bd.get("durasiMin")),
        "max": _to_int(bd.get("durasiMax")) or _to_int(raw.get("max_video_duration")),
    }
    return {
        "wajib": wajib, "boleh": boleh, "dilarang": dilarang,
        "materi": materi, "caption": caption, "hook": hook,
        "catatan": catatan, "durasi": durasi,
    }


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


def cpm_of_clippo(c):
    """(cpm, nama_platform) buat Clippo dalam Rp per 1.000 views.

    Konversi pakai `rate * 1000 / rateUnit`. Ambil yang tertinggi dari
    `campaignRates`, fallback ke `ratePerKView`.
    """
    unit_default = float(c.get("rateUnit") or 1000)
    kandidat = []
    for cr in (c.get("campaignRates") or []):
        if not isinstance(cr, dict):
            continue
        r = cr.get("ratePerKView")
        if not r:
            continue
        u = float(cr.get("rateUnit") or unit_default or 1000)
        nilai = int(round(float(r) * 1000.0 / u))
        p_raw = cr.get("platform")
        p_nama = CLIPPO_PLATFORM.get(p_raw, str(p_raw or ""))
        kandidat.append((nilai, p_nama))
    if kandidat:
        return max(kandidat, key=lambda x: x[0])
    r = c.get("ratePerKView")
    if r:
        nilai = int(round(float(r) * 1000.0 / (unit_default or 1000.0)))
        ps = c.get("platformSupported") or []
        p_nama = CLIPPO_PLATFORM.get(ps[0], str(ps[0])) if ps else "ratePerKView"
        return nilai, p_nama
    return 0, ""


def score(cpm, budget_left):
    """Skor urutan papan: cpm x sisa budget. Pilihan operator.

    Alasannya terukur: CPM tertinggi di marketplace (Rp15.000) nempel di
    campaign yang sisa budgetnya 6%, jadi rate-nya ga bisa diambil. Sisa
    budget yang ga diketahui dihitung 0 — bukan 100 — karena "ga tau" ga
    boleh naikin sesuatu ke puncak daftar.
    """
    return int(round(int(cpm or 0) * (int(budget_left or 0) / 100.0)))


def refresh(conn, campaigns=None):
    """Tarik daftar campaign konten.com dan simpen. Balik (jumlah, baru, aktif).

    Campaign yang ilang dari API TIDAK dihapus dari tabel: kalau sebuah
    campaign udah kita tandain garap dan punya aset, barisnya harus tetep
    ada walau marketplace nyopot dia dari daftar. Baris yang ga ada di list
    baru ditandain `status='gone'` (kecuali list kosong/gagal).
    """
    if campaigns is None:
        campaigns = _get(LIST_URL)["campaigns"]
    lama = {r["slug"] for r in conn.execute("SELECT slug FROM campaigns")}
    now = time.time()
    baru = 0
    baru_slugs = set()
    for c in campaigns:
        slug = (c.get("slug") or "").strip()
        if not slug:
            continue
        baru_slugs.add(slug)
        cpm, src = cpm_of(c)
        bl = c.get("budget_bar_percent_override")
        st = c.get("status") or ""
        if c.get("emergency_stopped"):
            st = "emergency_stopped"
        punya_brief = isinstance(c.get("brief_detail"), dict) or any(
            k in c for k in ("wajib", "boleh", "dilarang")
        )
        bjson = json.dumps(normalize_brief("konten", c), ensure_ascii=False) if punya_brief else ""
        bat = now if punya_brief else 0.0
        conn.execute(
            "INSERT INTO campaigns (slug, cid, title, brand, category, platform,"
            " cpm, cpm_source, budget_left, min_views, min_seconds,"
            " content_type, campaign_type, status, hashtags, description,"
            " deadline, fetched_at, source, brief_json, brief_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(slug) DO UPDATE SET"
            " cid=excluded.cid, title=excluded.title, brand=excluded.brand,"
            " category=excluded.category, platform=excluded.platform,"
            " cpm=excluded.cpm, cpm_source=excluded.cpm_source,"
            " budget_left=excluded.budget_left, min_views=excluded.min_views,"
            " min_seconds=excluded.min_seconds,"
            " content_type=excluded.content_type,"
            " campaign_type=excluded.campaign_type, status=excluded.status,"
            " hashtags=excluded.hashtags, description=excluded.description,"
            " deadline=excluded.deadline, fetched_at=excluded.fetched_at,"
            " source='konten',"
            " brief_json=CASE WHEN excluded.brief_json != '' THEN excluded.brief_json ELSE campaigns.brief_json END,"
            " brief_at=CASE WHEN excluded.brief_at > 0 THEN excluded.brief_at ELSE campaigns.brief_at END",
            (slug, c.get("id") or "", c.get("title") or "",
             c.get("brand") or "", c.get("category") or "",
             json.dumps(c.get("platform") or [], ensure_ascii=False),
             cpm, src,
             int(bl) if bl is not None else None,
             c.get("min_views"), c.get("min_video_duration"),
             c.get("content_type") or "", c.get("campaign_type") or "", st,
             json.dumps(c.get("hashtags") or [], ensure_ascii=False),
             (c.get("description") or "")[:4000],
             str(c.get("deadline") or ""), now, "konten", bjson, bat))
        if slug not in lama:
            baru += 1
    if baru_slugs:
        tanda = ",".join("?" for _ in baru_slugs)
        conn.execute(
            "UPDATE campaigns SET status='gone'"
            " WHERE source='konten' AND slug NOT IN (%s)" % tanda,
            tuple(baru_slugs))
    conn.commit()
    aktif = sum(1 for c in campaigns if (c.get("status") == "active"
                                         and not c.get("emergency_stopped")))
    return len(campaigns), baru, aktif


_CLIPPO_FETCH_JS = """async (url) => {
    const r = await fetch(url, {credentials: 'include'});
    return {ok: r.ok, status: r.status, body: r.ok ? await r.json() : null};
}"""


def _fetch_clippo_campaigns(limit=50, max_pages=20):
    """Tarik semua halaman list + detail Clippo lewat fetch() di dalam halaman."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = None
    try:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(CLIPPO_SITE.rstrip("/"), wait_until="domcontentloaded",
                  timeout=60000)
        items = []
        pg = 1
        while pg <= max_pages:
            url = "%s?limit=%d&orderBy=recommended&page=%d" % (
                CLIPPO_API, limit, pg)
            res = page.evaluate(_CLIPPO_FETCH_JS, url)
            if not res or not res.get("ok"):
                st = res.get("status") if isinstance(res, dict) else "?"
                raise RuntimeError("Clippo list API %s di page %d" % (st, pg))
            payload = ((res.get("body") or {}).get("data")) or {}
            batch = payload.get("data") or []
            items.extend(batch)
            if pg >= (payload.get("totalPage") or 1) or not batch:
                break
            pg += 1

        # Tarik detail per campaign di dalam halaman yang sama biar dapet
        # campaignDos, campaignDonts, campaignHook, minDuration, dll.
        out = []
        for it in items:
            cid = it.get("id")
            if not cid:
                continue
            dres = page.evaluate(_CLIPPO_FETCH_JS, "%s/%s" % (CLIPPO_API, cid))
            merged = dict(it)
            if dres and dres.get("ok"):
                detail = (dres.get("body") or {}).get("data")
                if isinstance(detail, dict):
                    merged.update(detail)
            out.append(merged)
        return out
    finally:
        try:
            if browser:
                browser.close()
        except Exception:
            pass
        try:
            pw.stop()
        except Exception:
            pass


def refresh_clippo(conn, campaigns=None):
    """Tarik daftar campaign Clippo dan simpen. Balik (jumlah, baru, aktif)."""
    if campaigns is None:
        campaigns = _fetch_clippo_campaigns()
    lama = {r["slug"] for r in conn.execute("SELECT slug FROM campaigns")}
    now = time.time()
    baru = 0
    aktif = 0
    baru_slugs = set()
    for c in campaigns:
        raw_id = str(c.get("id") or "").strip()
        if not raw_id and c.get("slug"):
            s = str(c["slug"]).strip()
            raw_id = s[7:] if s.startswith("clippo-") else s
        if not raw_id:
            continue
        cid = raw_id[7:] if raw_id.startswith("clippo-") else raw_id
        slug = "clippo-" + cid
        baru_slugs.add(slug)

        cpm, src = cpm_of_clippo(c)
        bp = c.get("budgetPercentage")
        bl = int(round(float(bp))) if bp is not None else None
        raw_st = c.get("status")
        st = "active" if (raw_st == 3 or raw_st == "active") else "completed"
        if st == "active":
            aktif += 1

        ps_raw = c.get("platformSupported")
        if ps_raw is not None:
            plats = [CLIPPO_PLATFORM.get(p, str(p)) for p in ps_raw]
        else:
            plats = list(c.get("platform") or [])

        tags = [str(h).strip().lstrip("#") for h in (c.get("hashtags") or [])
                if str(h).strip().lstrip("#")]
        brand = (
            ((c.get("creator") or {}).get("user") or {}).get("name")
            or c.get("brand") or ""
        )
        norm = normalize_brief("clippo", c)
        bjson = json.dumps(norm, ensure_ascii=False)
        desc = c.get("description") or "\n".join(norm["wajib"] + norm["catatan"])
        min_sec = _to_int(
            c.get("minDuration") if c.get("minDuration") is not None
            else c.get("min_seconds")
        )
        conn.execute(
            "INSERT INTO campaigns (slug, cid, title, brand, category, platform,"
            " cpm, cpm_source, budget_left, min_views, min_seconds,"
            " content_type, campaign_type, status, hashtags, description,"
            " deadline, fetched_at, source, brief_json, brief_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(slug) DO UPDATE SET"
            " cid=excluded.cid, title=excluded.title, brand=excluded.brand,"
            " category=excluded.category, platform=excluded.platform,"
            " cpm=excluded.cpm, cpm_source=excluded.cpm_source,"
            " budget_left=excluded.budget_left, min_views=excluded.min_views,"
            " min_seconds=excluded.min_seconds,"
            " content_type=excluded.content_type,"
            " campaign_type=excluded.campaign_type, status=excluded.status,"
            " hashtags=excluded.hashtags, description=excluded.description,"
            " deadline=excluded.deadline, fetched_at=excluded.fetched_at,"
            " source='clippo', brief_json=excluded.brief_json,"
            " brief_at=excluded.brief_at",
            (slug, cid, c.get("title") or "", brand,
             str(c.get("category") or ""),
             json.dumps(plats, ensure_ascii=False),
             cpm, src, bl, c.get("min_views"), min_sec,
             c.get("content_type") or "", c.get("campaign_type") or "", st,
             json.dumps(tags, ensure_ascii=False),
             (desc or "")[:4000],
             str(c.get("endDate") or c.get("deadline") or ""),
             now, "clippo", bjson, now))
        if slug not in lama:
            baru += 1

    if baru_slugs:
        tanda = ",".join("?" for _ in baru_slugs)
        conn.execute(
            "UPDATE campaigns SET status='gone'"
            " WHERE source='clippo' AND slug NOT IN (%s)" % tanda,
            tuple(baru_slugs))
    conn.commit()
    return len(campaigns), baru, aktif


def _default_fetch_brief(source, slug, cid=""):
    """Tarik detail brief dari sumber (konten.com via curl, Clippo via Playwright)."""
    src = (source or "konten").strip().lower()
    if src == "clippo":
        real_cid = cid or (slug[7:] if slug.startswith("clippo-") else slug)
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = None
        try:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(CLIPPO_SITE.rstrip("/"), wait_until="domcontentloaded",
                      timeout=60000)
            res = page.evaluate(_CLIPPO_FETCH_JS, "%s/%s" % (CLIPPO_API, real_cid))
            if not res:
                raise RuntimeError("Clippo detail kosong: %s" % real_cid)
            if res.get("status") == 404:
                raise BriefNotFound("Clippo 404: %s" % real_cid)
            if not res.get("ok"):
                raise RuntimeError("Clippo detail HTTP %s: %s"
                                   % (res.get("status"), real_cid))
            data = (res.get("body") or {}).get("data")
            if not isinstance(data, dict):
                raise RuntimeError("Clippo detail tanpa data: %s" % real_cid)
            return data
        finally:
            try:
                if browser:
                    browser.close()
            except Exception:
                pass
            try:
                pw.stop()
            except Exception:
                pass

    url = DETAIL_URL % slug
    r = subprocess.run(
        ["curl", "-s", "-m", "30", "-A", UA, "-w", "\n%{http_code}", url],
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError("fetch gagal: %s" % url)
    parts = r.stdout.rsplit("\n", 1)
    body = parts[0] if len(parts) == 2 else r.stdout
    kode = parts[1].strip() if len(parts) == 2 else ""
    if kode == "404":
        raise BriefNotFound("404: %s" % url)
    try:
        d = json.loads(body)
    except Exception as exc:
        raise RuntimeError("json rusak (%s): %s" % (kode, url)) from exc
    if isinstance(d, dict) and "tidak ditemukan" in str(d.get("error") or "").lower():
        raise BriefNotFound("404: %s" % url)
    if kode and kode != "200":
        raise RuntimeError("HTTP %s: %s" % (kode, url))
    return d["campaign"] if isinstance(d, dict) and "campaign" in d else d


FETCH_BRIEF = _default_fetch_brief


def fetch_brief(slug, source="konten", cid=""):
    return FETCH_BRIEF(source, slug, cid)


_ORIG_FETCH_BRIEF = fetch_brief


def _panggil_fetcher(fn, source, slug, cid):
    import inspect
    try:
        sig = inspect.signature(fn)
        params = [
            p for p in sig.parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        has_varargs = any(p.kind == p.VAR_POSITIONAL for p in sig.parameters.values())
        if not has_varargs and len(params) == 1:
            return fn(slug)
        if not has_varargs and len(params) == 2:
            return fn(source, slug)
    except Exception:
        pass
    return fn(source, slug, cid)


def ensure_brief(conn, slug, fetcher=None, max_age=BRIEF_TTL):
    """Ambil brief normal buat `slug`. Tarik dari sumber kalau kosong / > 6 jam.

    Balik `(brief_dict_atau_None, pesan_error_atau_None)`.
    Kalau sumber jawab 404 (`BriefNotFound`), tandai baris `status='gone'`.
    Kalau env `CLIPPER_BRIEF_OFFLINE` di-set (mis. `"1"`), lewati jaringan dan
    balik `(brief_tersimpan, None)`.
    """
    c = get(conn, slug)
    if not c:
        return None, None
    tersimpan = None
    if c.get("brief_json"):
        try:
            tersimpan = json.loads(c["brief_json"])
        except Exception:
            tersimpan = None

    umur = time.time() - float(c.get("brief_at") or 0)
    if tersimpan is not None and umur <= max_age:
        return tersimpan, None

    if os.environ.get("CLIPPER_BRIEF_OFFLINE", "").strip() not in ("", "0", "false", "False"):
        return tersimpan, None

    fn = fetcher
    if fn is None:
        if FETCH_BRIEF is not _default_fetch_brief:
            fn = FETCH_BRIEF
        elif fetch_brief is not _ORIG_FETCH_BRIEF:
            fn = fetch_brief
        else:
            fn = _default_fetch_brief

    try:
        raw = _panggil_fetcher(fn, c.get("source") or "konten",
                               c["slug"], c.get("cid") or "")
        if raw is None:
            raise BriefNotFound("404: %s" % c["slug"])
        norm = normalize_brief(c.get("source") or "konten", raw)
        now = time.time()
        conn.execute(
            "UPDATE campaigns SET brief_json=?, brief_at=? WHERE slug=?",
            (json.dumps(norm, ensure_ascii=False), now, c["slug"]))
        conn.commit()
        return norm, None
    except Exception as exc:
        if isinstance(exc, BriefNotFound):
            conn.execute("UPDATE campaigns SET status='gone' WHERE slug=?",
                         (c["slug"],))
            conn.commit()
            return tersimpan, "Campaign ini udah ga ada di marketplace (404)."
        return tersimpan, "Gagal narik brief terbaru (%s: %s)." % (
            type(exc).__name__, exc)


def last_refresh(conn):
    row = conn.execute("SELECT MAX(fetched_at) AS t FROM campaigns").fetchone()
    return row["t"] or 0.0


def _url_of(r):
    if (r.get("source") or "konten") == "clippo":
        cid = r.get("cid") or (
            r["slug"][7:] if r["slug"].startswith("clippo-") else r["slug"]
        )
        return CLIPPO_SITE + cid
    return SITE + r["slug"]


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
        r["source"] = r.get("source") or "konten"
        r["score"] = score(r["cpm"], r["budget_left"])
        r["platform"] = json.loads(r["platform"] or "[]")
        r["hashtags"] = json.loads(r["hashtags"] or "[]")
        r["url"] = _url_of(r)
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
    r["source"] = r.get("source") or "konten"
    r["score"] = score(r["cpm"], r["budget_left"])
    r["platform"] = json.loads(r["platform"] or "[]")
    r["hashtags"] = json.loads(r["hashtags"] or "[]")
    r["url"] = _url_of(r)
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
    # krakatau & nuface ga ada di list baru -> status='gone' dan ilang dari board
    assert get(conn, "krakatau")["status"] == "gone"
    assert [r["slug"] for r in board(conn)] == ["karomah"]
    # Pagar list kosong: JANGAN tandai karomah gone kalau list kosong
    refresh(conn, [])
    assert get(conn, "karomah")["status"] == "active"

    # Clippo masuk papan + pagar sumber terpisah
    refresh_clippo(conn, [{
        "id": "c1", "title": "Clippo Satu", "status": 3,
        "ratePerKView": 2000, "rateUnit": 1000, "budgetPercentage": 95.34,
        "minDuration": 15, "maxDuration": 60,
        "platformSupported": [0, 1], "hashtags": ["#clippo"],
        "campaignDos": ["boleh satu"], "campaignDonts": ["jangan dua"],
        "requirementsV2": "<p>Wajib <b>tiga</b></p>",
        "assetVideoUrlsV2": [{"url": "https://youtu.be/abc",
                              "isRequired": True, "displayText": "Bahan"}],
        "campaignHook": {"ops": [{"insert": "Hook pembuka\n"}]},
        "creator": {"user": {"name": "BrandX"}},
    }])
    c_clippo = get(conn, "clippo-c1")
    assert c_clippo["source"] == "clippo"
    assert c_clippo["cpm"] == 2000 and c_clippo["budget_left"] == 95
    assert c_clippo["url"] == "https://app.clippo.id/campaigns/c1"
    assert get(conn, "karomah")["status"] == "active"  # konten ga keganggu
    refresh_clippo(conn, [])
    assert get(conn, "clippo-c1")["status"] == "active"  # pagar list kosong
    # Kembalikan clippo-c1 jadi gone supaya ga ganggu cek pick(state='garap') di bawah
    refresh_clippo(conn, [{"id": "c2", "title": "Clippo Completed", "status": 1}])
    assert get(conn, "clippo-c1")["status"] == "gone"

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

    print(json.dumps({"ok": True, "checked": "cpm, skor, papan, pick, aset, gone, brief, clippo"}))
    return 0


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog="campaigns.py", description=__doc__)
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--refresh", action="store_true",
                   help="tarik daftar campaign dari marketplace")
    p.add_argument("--no-clippo", action="store_true",
                   help="lewati penarikan Clippo waktu --refresh")
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
        print("refresh konten: %d campaign (%d baru), %d aktif"
              % (total, baru, aktif))
        if not a.no_clippo:
            try:
                ctot, cbaru, caktif = refresh_clippo(conn)
                print("refresh clippo: %d campaign (%d baru), %d aktif"
                      % (ctot, cbaru, caktif))
            except Exception as exc:
                print("refresh clippo gagal: %s" % exc)
    if a.board or not a.refresh:
        rows = board(conn, hanya_aktif=not a.all, limit=a.limit)
        print("%-7s %-7s %5s %7s %-6s  %s" % (
            "SKOR", "Rp/1k", "sisa", "minview", "sumber", "campaign"))
        for r in rows:
            print("%-7d %-7d %4s%% %7s%s %-6s  %s — %s" % (
                r["score"], r["cpm"],
                r["budget_left"] if r["budget_left"] is not None else "?",
                r["min_views"] if r["min_views"] is not None else "?",
                " !" if r["min_views_merah"] else "  ",
                (r.get("source") or "konten")[:6],
                r["title"][:44], r["brand"][:18]))
        print("(%d baris, terakhir refresh %s)" % (
            len(rows),
            time.strftime("%d %b %H:%M", time.localtime(last_refresh(conn)))
            if last_refresh(conn) else "BELUM PERNAH"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
