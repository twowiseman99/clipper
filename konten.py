#!/usr/bin/env python3
"""konten.py — read a Konten.com campaign brief and turn it into checkable render rules.

Three things measured on this box before a line of this was written, because
each one changed the design:

1. **The brief needs no login.** `konten.com/api/campaigns/<slug>` returns the
   full campaign — budget, spent, min_views, min_video_duration, and the whole
   `brief_detail` with elemenWajib / bolehDilakukan / dilarangDilakukan — over
   plain HTTP 200 with nothing but a browser User-Agent. The operator assumed
   a cookie was needed to read requirements; it is not. Cookies are needed
   only to SUBMIT.

2. **There are two hosts, not one.** The page calls
   `gateway.konten.com/api/*`, while `konten.com/api/campaigns` also answers.
   Unauthenticated probes, same minute:

       konten.com/api/campaigns/<slug>                 200  (full brief)
       gateway.konten.com/api/campaigns/<slug>         200
       gateway.konten.com/api/me                       401  Unauthorized
       gateway.konten.com/api/campaigns/<slug>/submit  401  Unauthorized
       gateway.konten.com/api/clips                    404  unknown_route
       gateway.konten.com/api/submissions              404  unknown_route

   401 vs 404 is the whole map: 401 means the route EXISTS and wants a session,
   404 means it is not a route at all. So the submit endpoint is
   `POST gateway.konten.com/api/campaigns/<slug>/submit`, and guessing any of
   the 404 names would have produced a submitter that could never work.

3. **`submit_via_link_enabled` is FALSE.** `gateway.konten.com/api/feature-flags`
   is public and reports it. Same payload: `tiktok_official_api_enabled: false`,
   `tiktok_login_kit_enabled: false`, `campaign_min_views_floor: 1000`,
   `early_earning_rate_percent: 50`. A submitter built against a disabled
   feature flag is dead code that looks finished, so SUBMIT IS GATED ON THAT
   FLAG being true at runtime — it is read live, never assumed.

What this module does today: fetch a brief, extract the rules that can be
mechanically checked, and verify a rendered clip against them BEFORE anything
is uploaded. What it deliberately does not do: pretend to submit. `submit`
refuses with the reason — missing session, or the flag being off — rather than
posting into the dark.
"""
import argparse
import json
import os
import re
import subprocess
import sys

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
SITE = "https://konten.com"
GATEWAY = "https://gateway.konten.com"
FLAGS_URL = f"{GATEWAY}/api/feature-flags"
# Measured: 401 (exists, needs session), not one of the 404 guesses.
SUBMIT_PATH = "/api/campaigns/{slug}/submit"

SESSION_DIR = os.environ.get(
    "CLIPPER_SESSION_DIR", "/home/ubuntu/clipper/sessions")


def _curl_json(url, extra=()):
    cmd = ["curl", "-s", "-m", "30", "-A", UA,
           "-H", "Origin: https://konten.com",
           "-H", "Referer: https://konten.com/", *extra, url]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"fetch failed: {url}")
    return json.loads(r.stdout)


def slug_of(s):
    """Accept a full campaign URL or a bare slug."""
    s = s.strip().rstrip("/")
    m = re.search(r"/campaigns/([^/?#]+)", s)
    return m.group(1) if m else s


def fetch_brief(slug):
    d = _curl_json(f"{SITE}/api/campaigns/{slug_of(slug)}")
    return d["campaign"] if isinstance(d, dict) and "campaign" in d else d


def fetch_flags():
    return _curl_json(FLAGS_URL)


# ------------------------------------------------------- rule extraction

# Patterns for the numbers that hide in free text rather than in a field.
# Keyed on what they mean, not on the phrasing, so a new campaign wording adds
# a pattern instead of a special case.
_HOOK_PCT = re.compile(r"hook\s+maksimal\s+(\d+)\s*%", re.I)
_HOOK_SECS = re.compile(r"hook\s+maksimal\s+(\d+)\s*(?:detik|s\b)", re.I)
_LINK_WORDS = ("keranjang kuning", "link produk", "link afiliasi",
               "link di caption", "link keranjang")
_CAPTION_WORDS = ("capton", "caption", "kapsi")


def _text_blob(brief):
    bd = brief.get("brief_detail") or {}
    parts = [
        bd.get("elemenWajib") or "",
        bd.get("captionWajib") or "",
        bd.get("narasi") or "",
        bd.get("instruksiBrief") or "",
        brief.get("brief_instructions") or "",
        "\n".join(bd.get("bolehDilakukan") or []),
        "\n".join(bd.get("dilarangDilakukan") or []),
        "\n".join(brief.get("brief_dos") or []),
        "\n".join(brief.get("brief_donts") or []),
    ]
    return "\n".join(p for p in parts if p)


_PER_PLATFORM_CPM = ("cpm_tiktok", "cpm_instagram", "cpm_youtube",
                     "cpm_threads")


def _rates(brief):
    """Pay rate per platform, in IDR per 1000 views.

    Two traps here, both found by checking the field against the page instead
    of trusting its name.

    **The field name lies.** The payload's main rate field is
    `rate_per_million`, but the campaign page renders it as
    "Rp10.000 / 1K views" and labels the column "CPM (Rate /1K Views)". It is
    per *thousand*, not per million — a 1000x error, and reading the name as
    the unit would have priced every campaign at a thousandth of its value.
    The returned dict is therefore always IDR-per-1000, and `rules()` ships a
    `cpm_unit` string so a caller cannot re-guess it.

    **The per-platform fields are often empty.** Measured across all 111
    campaigns in the public list: 54 carry both `rate_per_million` and
    per-platform `cpm_*` fields that agree exactly; **56 carry only
    `rate_per_million`** with every `cpm_*` null; 0 carry only `cpm_*`. So
    reading just `cpm_*` reports "no rate" for half the marketplace — which is
    exactly what happened to ugc-konten-com-longform (Rp10.000) and suli-2
    (Rp4.000) before this existed.

    One campaign (`cryptowave-news`) disagrees: rate_per_million 2000 while
    cpm_tiktok is 2500 and the others 2000. That single row proves the
    per-platform fields are an OVERRIDE, not a duplicate, so they must win
    where present and the flat rate is the fallback for the rest.
    """
    flat = brief.get("rate_per_million")
    out = {}
    for p in (brief.get("platform") or []):
        key = f"cpm_{p}"
        v = brief.get(key)
        out[p] = v if v is not None else flat
    # A platform-specific rate for a platform not in the list still matters:
    # it is money the brief offers, so it is reported rather than dropped.
    for k in _PER_PLATFORM_CPM:
        v = brief.get(k)
        if v is not None:
            out.setdefault(k[4:], v)
    return {k: v for k, v in out.items() if v is not None}


def rules(brief):
    """The campaign's requirements, split by whether a machine can check them.

    The split is the point. A rule like "hook maksimal 20% durasi" is a number
    and gets enforced; "narasi yang relevan" is a judgement and must be shown
    to a human instead of being silently assumed satisfied. Dropping the
    unenforceable ones would make the report read like full compliance.
    """
    bd = brief.get("brief_detail") or {}
    blob = _text_blob(brief)
    out = {
        "slug": brief.get("slug"),
        "title": brief.get("title"),
        "brand": brief.get("brand"),
        "platforms": [p for p in (brief.get("platform") or [])],
        "cpm": _rates(brief),
        "cpm_unit": "IDR per 1000 views",
        "budget": brief.get("budget"),
        "spent": brief.get("spent"),
        "budget_left_pct": brief.get("budget_bar_percent_override"),
        "checkable": {},
        "human": [],
        "forbidden": [],
    }
    chk = out["checkable"]
    if brief.get("min_video_duration"):
        chk["min_duration_s"] = brief["min_video_duration"]
    bd_max = bd.get("durasiMax")
    if isinstance(bd_max, str) and bd_max.strip().isdigit():
        chk["max_duration_s"] = int(bd_max.strip())
    m = _HOOK_PCT.search(blob)
    if m:
        chk["hook_max_pct"] = int(m.group(1))
    m = _HOOK_SECS.search(blob)
    if m:
        chk["hook_max_s"] = int(m.group(1))

    # Links required in the video and/or the caption.
    low = blob.lower()
    links = [x["url"] for x in (bd.get("materi") or [])
             if any(w in (x.get("title", "") or "").lower()
                    for w in ("keranjang", "link", "produk"))]
    if any(w in low for w in _LINK_WORDS):
        chk["required_links"] = links
        chk["link_in_caption"] = any(w in low for w in _CAPTION_WORDS)
    hashtags = [h for h in (brief.get("hashtags") or [])]
    tags = bd.get("tagSocialMedia") or {}
    if tags.get("enabled"):
        for p, v in tags.items():
            if isinstance(v, list) and v:
                hashtags += v
    if hashtags:
        chk["required_hashtags"] = sorted(set(hashtags))

    # Earning thresholds — not render rules, but they decide whether posting is
    # worth it at all, so they travel with the rules.
    for k in ("min_views", "max_views", "early_earn_views",
              "max_claims_per_video", "max_videos_per_clipper"):
        if brief.get(k) is not None:
            chk[k] = brief[k]
    chk["enforce_min_followers"] = bool(brief.get("enforce_min_followers"))

    for line in (bd.get("dilarangDilakukan") or []) + (brief.get("brief_donts") or []):
        line = line.strip(" -\n")
        if line:
            out["forbidden"].append(line)
    for line in (bd.get("elemenWajib") or "").splitlines():
        line = line.strip(" -\n")
        if not line:
            continue
        # A line that produced a number is already enforced; the rest is
        # judgement and must be surfaced to a human.
        if _HOOK_PCT.search(line) or _HOOK_SECS.search(line):
            continue
        out["human"].append(line)
    out["materials"] = [x.get("url") for x in (bd.get("materi") or [])
                        if x.get("url")]
    return out


# ------------------------------------------------------------ clip check

def probe(path):
    """Delivered-file facts via ffprobe. Never trust the render's own claim."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,duration",
         "-show_entries", "format=duration", "-of", "json", path],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {r.stderr[:200]}")
    d = json.loads(r.stdout)
    st = (d.get("streams") or [{}])[0]
    dur = st.get("duration") or d.get("format", {}).get("duration")
    return {"width": st.get("width"), "height": st.get("height"),
            "duration": float(dur) if dur else None}


def check(brief_rules, clip_path=None, caption="", hook_s=None):
    """Verdicts per rule. PASS / FAIL / SKIP, and SKIP is never a pass.

    A missing input (no clip handed in, no hook duration known) yields SKIP
    with the reason. An "all clear" built out of skipped checks is the exact
    shape of a gate that silently does nothing, so the summary counts them
    separately and `ok` requires at least one PASS and zero FAIL.
    """
    chk = brief_rules["checkable"]
    res = []

    def add(name, verdict, detail):
        res.append({"rule": name, "verdict": verdict, "detail": detail})

    info = None
    if clip_path:
        info = probe(clip_path)

    if "min_duration_s" in chk:
        if info and info["duration"] is not None:
            d = info["duration"]
            add("min_duration", "PASS" if d >= chk["min_duration_s"] else "FAIL",
                f"{d:.2f}s vs min {chk['min_duration_s']}s")
        else:
            add("min_duration", "SKIP", "no clip given")
    if "max_duration_s" in chk:
        if info and info["duration"] is not None:
            d = info["duration"]
            add("max_duration", "PASS" if d <= chk["max_duration_s"] else "FAIL",
                f"{d:.2f}s vs max {chk['max_duration_s']}s")
        else:
            add("max_duration", "SKIP", "no clip given")

    if "hook_max_pct" in chk:
        if info and info["duration"] and hook_s is not None:
            pct = 100.0 * hook_s / info["duration"]
            add("hook_max_pct",
                "PASS" if pct <= chk["hook_max_pct"] else "FAIL",
                f"hook {hook_s:.2f}s = {pct:.1f}% of {info['duration']:.2f}s, "
                f"max {chk['hook_max_pct']}%")
        else:
            add("hook_max_pct", "SKIP",
                "need --hook-seconds and a clip to compute the ratio")
    if "hook_max_s" in chk:
        if hook_s is not None:
            add("hook_max_s", "PASS" if hook_s <= chk["hook_max_s"] else "FAIL",
                f"hook {hook_s:.2f}s vs max {chk['hook_max_s']}s")
        else:
            add("hook_max_s", "SKIP", "need --hook-seconds")

    if chk.get("link_in_caption"):
        want = chk.get("required_links") or []
        if not caption:
            add("link_in_caption", "SKIP", "no caption given")
        elif not want:
            add("link_in_caption", "SKIP",
                "brief demands a link but lists none in materi")
        else:
            hit = [u for u in want if u in caption]
            add("link_in_caption", "PASS" if hit else "FAIL",
                f"{len(hit)}/{len(want)} required link(s) present in caption")
    for h in chk.get("required_hashtags", []):
        if not caption:
            add(f"hashtag {h}", "SKIP", "no caption given")
        else:
            add(f"hashtag {h}",
                "PASS" if h.lower().lstrip("#") in caption.lower() else "FAIL",
                "caption")

    n = {"PASS": 0, "FAIL": 0, "SKIP": 0}
    for r in res:
        n[r["verdict"]] += 1
    return {
        "results": res,
        "counts": n,
        "ok": n["FAIL"] == 0 and n["PASS"] > 0,
        "needs_human": brief_rules["human"],
        "forbidden": brief_rules["forbidden"],
        "clip": info,
    }


# ---------------------------------------------------------------- submit

def submit_readiness(slug, account):
    """Everything that must be true before a submit can even be attempted.

    Returns a dict with ok=False and a named blocker rather than raising, so
    the caller reports WHY instead of a traceback. Two independent blockers,
    both measured rather than assumed:

      * the platform's own `submit_via_link_enabled` flag, read live;
      * a verified session for this account on disk.
    """
    out = {"slug": slug_of(slug), "account": account,
           "endpoint": GATEWAY + SUBMIT_PATH.format(slug=slug_of(slug))}
    try:
        flags = fetch_flags()
    except Exception as e:
        out["ok"] = False
        out["blocker"] = f"cannot read feature flags: {e}"
        return out
    f = flags.get("flags", {})
    out["submit_via_link_enabled"] = f.get("submit_via_link_enabled")
    out["tiktok_official_api_enabled"] = f.get("tiktok_official_api_enabled")
    out["settings"] = flags.get("settings", {})
    sess = os.path.join(SESSION_DIR, f"konten__{account.lstrip('@')}.json")
    out["session"] = sess
    out["session_present"] = os.path.exists(sess)
    blockers = []
    if not out["submit_via_link_enabled"]:
        blockers.append(
            "konten.com has submit_via_link_enabled=false — submitting a clip "
            "URL is switched off platform-side; a submitter built now would be "
            "dead code")
    if not out["session_present"]:
        blockers.append(
            f"no verified konten session at {sess} — run session_import.py "
            "import --platform konten --account %s --from <cookies.txt>"
            % account)
    out["ok"] = not blockers
    out["blockers"] = blockers
    return out


# ------------------------------------------------------------ self-check

_FIXTURE = {
    "slug": "karomah-insani-kerkun",
    "title": "Karomah Insani - Keranjang Kuning",
    "brand": "Karomah Insani",
    "platform": ["tiktok"],
    "cpm_tiktok": 10000, "cpm_instagram": None, "cpm_youtube": None,
    "budget": 9000000, "spent": 0, "budget_bar_percent_override": 100,
    "min_views": 10000, "max_views": 1000000, "early_earn_views": 1000,
    "min_video_duration": 10, "max_claims_per_video": 1,
    "max_videos_per_clipper": None, "enforce_min_followers": False,
    "hashtags": [],
    "brief_detail": {
        "materi": [
            {"url": "https://vt.tokopedia.com/t/ZS9U8eYM812qb-4xC2U/",
             "title": "Link keranjang kuning"},
            {"url": "https://www.tiktok.com/@sarahandrianna/video/7648549699619671316",
             "title": "Materi 1"},
        ],
        "durasiMax": "-", "durasiMin": "-",
        "elemenWajib": ("- Clipping sesuai dengan materi dan narasi yang "
                        "relevan\n- Hook maksimal 20% durasi video dengan hook "
                        "yang relevan \n- Memasukan link keranjang kuning "
                        "divideo dan dicapton"),
        "bolehDilakukan": ["- Gunakan materi yang ada"],
        "dilarangDilakukan": ["- Dilarang mengandung SARA, ",
                              "- Dilarang menggunakan ads maupun bot", ""],
        "tagSocialMedia": {"enabled": False, "tiktok": []},
    },
}


def _selfcheck():
    r = rules(_FIXTURE)
    chk = r["checkable"]
    assert chk["min_duration_s"] == 10, chk
    # "Hook maksimal 20% durasi video" lives in free text, not a field.
    assert chk["hook_max_pct"] == 20, chk
    # durasiMax is the string "-" here; it must NOT become a number.
    assert "max_duration_s" not in chk, chk
    assert chk["link_in_caption"] is True, chk
    assert any("tokopedia" in u for u in chk["required_links"]), chk
    assert r["platforms"] == ["tiktok"] and r["cpm"] == {"tiktok": 10000}, r
    # The judgement rules must survive into the human list — a report that
    # omits them reads as full compliance.
    assert any("relevan" in h for h in r["human"]), r["human"]
    assert any("bot" in f for f in r["forbidden"]), r["forbidden"]
    # Blank lines in the platform's own arrays must not become empty rules.
    assert all(f.strip() for f in r["forbidden"]), r["forbidden"]

    url_rules = rules(dict(_FIXTURE))
    assert slug_of("https://konten.com/campaigns/karomah-insani-kerkun") == \
        "karomah-insani-kerkun"
    assert slug_of("karomah-insani-kerkun/") == "karomah-insani-kerkun"

    # check(): a hook over the ratio must FAIL, under must PASS, and missing
    # inputs must SKIP rather than pass.
    class _Fake:
        pass
    g = check(url_rules, clip_path=None, caption="", hook_s=None)
    assert g["counts"]["PASS"] == 0, g["counts"]
    assert g["ok"] is False, "all-SKIP must never be ok"

    # Ratio arithmetic without touching ffprobe.
    saved = globals()["probe"]
    try:
        globals()["probe"] = lambda p: {"width": 1080, "height": 1920,
                                        "duration": 30.0}
        g = check(url_rules, clip_path="x.mp4",
                  caption="beli di https://vt.tokopedia.com/t/ZS9U8eYM812qb-4xC2U/",
                  hook_s=5.0)
        by = {r["rule"]: r["verdict"] for r in g["results"]}
        assert by["min_duration"] == "PASS", g["results"]
        assert by["hook_max_pct"] == "PASS", g["results"]   # 16.7% <= 20%
        assert by["link_in_caption"] == "PASS", g["results"]
        assert g["ok"] is True, g

        g = check(url_rules, clip_path="x.mp4", caption="no link here",
                  hook_s=9.0)                                # 30% > 20%
        by = {r["rule"]: r["verdict"] for r in g["results"]}
        assert by["hook_max_pct"] == "FAIL", g["results"]
        assert by["link_in_caption"] == "FAIL", g["results"]
        assert g["ok"] is False, g

        # A clip shorter than the minimum must fail even if everything else is
        # fine — the duration floor is the campaign's, not ours.
        globals()["probe"] = lambda p: {"width": 1080, "height": 1920,
                                        "duration": 8.0}
        g = check(url_rules, clip_path="x.mp4",
                  caption="https://vt.tokopedia.com/t/ZS9U8eYM812qb-4xC2U/",
                  hook_s=1.0)
        by = {r["rule"]: r["verdict"] for r in g["results"]}
        assert by["min_duration"] == "FAIL", g["results"]
        assert g["ok"] is False, g
    finally:
        globals()["probe"] = saved
    print("konten self-check OK")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("brief", help="fetch + extract rules (no login needed)")
    b.add_argument("campaign")
    b.add_argument("--raw", action="store_true")

    c = sub.add_parser("check", help="verify a rendered clip against the brief")
    c.add_argument("campaign")
    c.add_argument("--clip")
    c.add_argument("--caption", default="")
    c.add_argument("--hook-seconds", type=float, default=None)

    s = sub.add_parser("submit", help="report whether a submit is even possible")
    s.add_argument("campaign")
    s.add_argument("--account", required=True)

    sub.add_parser("flags", help="live feature flags + settings")
    sub.add_parser("selfcheck")

    a = ap.parse_args(argv)
    if a.cmd == "selfcheck":
        return _selfcheck()
    if a.cmd == "flags":
        print(json.dumps(fetch_flags(), indent=1, ensure_ascii=False))
        return 0
    if a.cmd == "brief":
        br = fetch_brief(a.campaign)
        print(json.dumps(br if a.raw else rules(br), indent=1,
                         ensure_ascii=False))
        return 0
    if a.cmd == "check":
        br = fetch_brief(a.campaign)
        out = check(rules(br), a.clip, a.caption, a.hook_seconds)
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return 0 if out["ok"] else 1
    out = submit_readiness(a.campaign, a.account)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
