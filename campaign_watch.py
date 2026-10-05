#!/usr/bin/env python3
"""Watch clipping marketplaces for campaigns worth taking, and report only new ones.

The operator's filter, verbatim: "filter campaign2 yang CPM nya di atas Rp.2500
dan budget tersisanya 50%".

Two marketplaces were asked for. Only one of them can actually be read from
this box, and the report says so rather than implying full coverage:

  konten.com  — `/api/campaigns` serves 109 campaigns with no login at all.
  app.clippo.id — `/api/proxy/*` returns 403 without a session, and this box
                  has no browser and no stored Clippo credentials. Reporting
                  "0 Clippo campaigns match" would be a lie by omission, so
                  Clippo is listed as UNREAD until a session exists.

The budget field needed a measurement, not a guess. The list endpoint carries
`budget_bar_percent_override`, whose name suggests a display tweak rather than
real data, and the real `budget`/`spent` numbers only appear on the per-campaign
detail endpoint. Checked against 8 campaigns:

    budget 300_000_000, spent 246_000_000 -> 18.0% left, override says 18

8/8 matched within 1.5pp, so the override IS the remaining-budget percentage and
the list endpoint alone is enough. The verifier below re-runs that check on a
sample each time, because this is an undocumented third-party field and an
assumption that silently stops holding would quietly corrupt every report.
"""
import json
import os
import subprocess
import sys
import time

MIN_CPM = int(os.environ.get("WATCH_MIN_CPM", "2500"))
MIN_BUDGET_LEFT = int(os.environ.get("WATCH_MIN_BUDGET_LEFT", "50"))
STATE = os.path.expanduser(os.environ.get(
    "WATCH_STATE", "~/.hermes/campaign-watch/konten.json"))
# A real browser UA. urllib's default got a blanket 403 from this host while
# curl with a browser UA succeeded, so the UA is load-bearing, not cargo cult.
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
LIST_URL = "https://konten.com/api/campaigns"
DETAIL_URL = "https://konten.com/api/campaigns/{}"
CLIPPO_PROBE = "https://app.clippo.id/api/proxy/campaigns"


def _get(url, timeout=30):
    r = subprocess.run(["curl", "-s", "-m", str(timeout), "-A", UA, url],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"fetch failed: {url}")
    return json.loads(r.stdout)


def cpm(c):
    """Highest CPM across platforms.

    A campaign can pay different rates per platform, and the operator picks
    which platform to post on, so the ceiling is the number that decides
    whether the campaign is worth taking. `rate_per_million` is the fallback
    for campaigns that quote one flat rate.
    """
    rates = [c.get(k) for k in
             ("cpm_tiktok", "cpm_instagram", "cpm_youtube", "cpm_threads")]
    rates = [r for r in rates if r]
    return max(rates) if rates else (c.get("rate_per_million") or 0)


def budget_left(c):
    v = c.get("budget_bar_percent_override")
    return int(v) if v is not None else None


def verify_budget_field(campaigns, sample=4):
    """Re-check `override == (budget-spent)/budget` on a few detail pages.

    Returns (checked, mismatches). An empty check is reported as such: "0
    mismatches out of 0" must never read as confirmation.
    """
    checked, bad = 0, []
    for c in campaigns[:sample]:
        try:
            d = _get(DETAIL_URL.format(c["id"]))["campaign"]
        except Exception:
            continue
        b, s, ov = d.get("budget"), d.get("spent"), budget_left(c)
        if not b or ov is None:
            continue
        real = 100.0 * (b - s) / b
        checked += 1
        if abs(real - ov) >= 1.5:
            bad.append((c.get("slug", c["id"]), ov, round(real, 1)))
    return checked, bad


def qualifying(campaigns):
    out = []
    for c in campaigns:
        if c.get("status") != "active" or c.get("emergency_stopped"):
            continue
        left = budget_left(c)
        if left is None or left < MIN_BUDGET_LEFT:
            continue
        if cpm(c) <= MIN_CPM:
            continue
        out.append(c)
    return sorted(out, key=cpm, reverse=True)


def load_seen():
    try:
        with open(STATE) as f:
            return set(json.load(f).get("seen", []))
    except Exception:
        return set()


def save_seen(ids):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"seen": sorted(ids), "updated": time.time()}, f)
    os.replace(tmp, STATE)


def clippo_reachable():
    r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                        "-m", "20", "-A", UA, CLIPPO_PROBE],
                       capture_output=True, text=True)
    return r.stdout.strip()


def main():
    first_run = not os.path.exists(STATE)
    campaigns = _get(LIST_URL)["campaigns"]
    hits = qualifying(campaigns)
    seen = load_seen()
    fresh = [c for c in hits if c["id"] not in seen]

    checked, bad = verify_budget_field(campaigns)
    code = clippo_reachable()

    lines = []
    if fresh:
        lines.append(f"**{len(fresh)} campaign baru** lolos filter "
                     f"(CPM > Rp{MIN_CPM:,} · sisa budget ≥ {MIN_BUDGET_LEFT}%)"
                     .replace(",", "."))
        lines.append("")
        for c in fresh:
            lines.append(
                f"`Rp{cpm(c):>6,}`".replace(",", ".") +
                f" · sisa **{budget_left(c)}%** · {c['title'][:52]}"
                f" — {c['brand'][:22]}")
            lines.append(f"  <https://konten.com/campaigns/{c['slug']}>")
    elif first_run:
        lines.append("Belum ada campaign yang lolos filter.")

    if fresh or first_run:
        lines.append("")
        lines.append(f"_{len(hits)} lolos dari {len(campaigns)} campaign._")
        # Say which source could not be read. A silent run would otherwise
        # read as "both marketplaces checked, nothing found".
        if code != "200":
            lines.append(f"_Clippo: BELUM TERBACA (HTTP {code}) — butuh session "
                         "login; box ini belum ada browser/kredensial._")
        if bad:
            lines.append(f"_⚠ budget field berubah arti: {bad} — "
                         "angka sisa budget jangan dipercaya sampai dicek._")
        elif checked:
            lines.append(f"_budget field diverifikasi ulang: {checked}/{checked} "
                         "cocok sama budget-spent di halaman detail._")
        else:
            lines.append("_⚠ verifikasi budget TIDAK JALAN run ini._")

    save_seen(seen | {c["id"] for c in hits})
    # Silence when there is nothing new: a watcher that reports every tick
    # trains the reader to ignore it.
    if lines:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        s = [{"id": "a", "status": "active", "cpm_tiktok": 3000,
              "budget_bar_percent_override": 60, "title": "x", "brand": "y",
              "slug": "x"},
             # 2500 exactly is NOT above 2500.
             {"id": "b", "status": "active", "cpm_tiktok": 2500,
              "budget_bar_percent_override": 90, "title": "x", "brand": "y",
              "slug": "x"},
             # 49% is below the floor.
             {"id": "c", "status": "active", "cpm_tiktok": 9000,
              "budget_bar_percent_override": 49, "title": "x", "brand": "y",
              "slug": "x"},
             # Paused and emergency-stopped campaigns cannot be worked.
             {"id": "d", "status": "paused", "cpm_tiktok": 9000,
              "budget_bar_percent_override": 90, "title": "x", "brand": "y",
              "slug": "x"},
             {"id": "e", "status": "active", "cpm_tiktok": 9000,
              "emergency_stopped": True, "budget_bar_percent_override": 90,
              "title": "x", "brand": "y", "slug": "x"},
             # Flat-rate campaign: rate_per_million is the only CPM.
             {"id": "f", "status": "active", "rate_per_million": 4000,
              "budget_bar_percent_override": 80, "title": "x", "brand": "y",
              "slug": "x"},
             # Missing budget data is not treated as passing.
             {"id": "g", "status": "active", "cpm_tiktok": 9000,
              "budget_bar_percent_override": None, "title": "x", "brand": "y",
              "slug": "x"}]
        got = [c["id"] for c in qualifying(s)]
        assert got == ["f", "a"], got
        # Highest platform rate wins, not the first one listed.
        assert cpm({"cpm_tiktok": 1000, "cpm_youtube": 7000}) == 7000
        assert cpm({"rate_per_million": 2000}) == 2000
        print("campaign_watch: self-check ok")
        sys.exit(0)
    sys.exit(main())
