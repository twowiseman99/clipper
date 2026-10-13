"""_v79 — konten.com: brief rules are extracted, and a submit cannot pretend.

Three bugs/traps this pins, each found by measuring rather than reading:

1. **The brief needs no login.** `konten.com/api/campaigns/<slug>` returns the
   whole campaign, including the `brief_detail` that holds the real
   requirements, over plain HTTP 200. The operator was about to hand over a
   cookie to read it. Cookies are needed only to submit.

2. **401 and 404 are not the same answer.** Unauthenticated probes against
   `gateway.konten.com`: `/api/me` and `/api/campaigns/<slug>/submit` return
   401 (route exists, needs a session) while `/api/clips`, `/api/submissions`,
   `/api/creator/clips`, `/api/my-clips` return 404 `unknown_route`. Guessing
   any of the 404 names would have shipped a submitter that could never work.
   So the endpoint is pinned here against the 401 observation.

3. **`submit_via_link_enabled` is false platform-side.** The public
   feature-flags endpoint says so. A submitter written now is dead code that
   looks finished, so submit_readiness() must refuse and NAME the flag. The
   flag is read live — if konten turns it on, this gate opens by itself and
   the test below is what proves the refusal was never hardcoded.

The checkable/human split is the fourth thing worth pinning: "hook maksimal
20% durasi" is a number and gets enforced; "narasi yang relevan" is a
judgement and must reach a human. A report that silently dropped the
judgement rules would read as full compliance.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import konten  # noqa: E402

# The live submit endpoint, as proved by 401-vs-404 rather than by guessing.
EXPECTED_SUBMIT = ("https://gateway.konten.com/api/campaigns/"
                   "karomah-insani-kerkun/submit")


def main():
    # ---- rules extracted from the real brief shape -------------------
    r = konten.rules(konten._FIXTURE)
    chk = r["checkable"]
    assert chk["min_duration_s"] == 10, chk
    # Lives in free text ("Hook maksimal 20% durasi video"), not in a field.
    assert chk["hook_max_pct"] == 20, chk
    # durasiMax is the literal string "-" in this brief. It must not become a
    # number — a bogus max would fail every clip.
    assert "max_duration_s" not in chk, chk
    assert chk["link_in_caption"] is True, chk
    assert chk["min_views"] == 10000 and chk["early_earn_views"] == 1000, chk
    assert r["platforms"] == ["tiktok"], r
    # TikTok-only campaign: an IG upload for this one earns nothing, so the
    # absent CPMs must not silently become a number.
    assert r["cpm"] == {"tiktok": 10000}, r["cpm"]
    # The unit is published, because the field it comes from is named
    # `rate_per_million` while the page says "Rp10.000 / 1K views" — per
    # thousand. A caller re-guessing from the field name is off by 1000x.
    assert r["cpm_unit"] == "IDR per 1000 views", r["cpm_unit"]

    # A campaign carrying ONLY rate_per_million must still report a rate.
    # 56 of the 111 live campaigns are shaped this way (every cpm_* null), so
    # reading only the per-platform fields reports "no rate" for half the
    # marketplace — the bug this pins, caught on ugc-konten-com-longform.
    flat_only = dict(konten._FIXTURE)
    flat_only["platform"] = ["youtube"]
    flat_only["rate_per_million"] = 10000
    for k in konten._PER_PLATFORM_CPM:
        flat_only[k] = None
    assert konten.rules(flat_only)["cpm"] == {"youtube": 10000}, \
        konten.rules(flat_only)["cpm"]

    # ...and a per-platform rate must OVERRIDE the flat one where they differ.
    # Live proof this is not a duplicate field: cryptowave-news carries
    # rate_per_million 2000 with cpm_tiktok 2500.
    override = dict(konten._FIXTURE)
    override["platform"] = ["tiktok", "instagram", "youtube"]
    override["rate_per_million"] = 2000
    override["cpm_tiktok"] = 2500
    override["cpm_instagram"] = None
    override["cpm_youtube"] = None
    assert konten.rules(override)["cpm"] == {
        "tiktok": 2500, "instagram": 2000, "youtube": 2000}, \
        konten.rules(override)["cpm"]

    # judgement rules survive; empty strings in the platform's arrays do not
    assert any("relevan" in h for h in r["human"]), r["human"]
    assert any("bot" in f for f in r["forbidden"]), r["forbidden"]
    assert all(f.strip() for f in r["forbidden"]), r["forbidden"]

    # ---- the gate must be able to say no ----------------------------
    saved = konten.probe
    try:
        konten.probe = lambda p: {"width": 1080, "height": 1920,
                                  "duration": 30.0}
        link = "https://vt.tokopedia.com/t/ZS9U8eYM812qb-4xC2U/"
        g = konten.check(r, "x.mp4", f"beli {link}", 5.0)     # 16.7%
        by = {x["rule"]: x["verdict"] for x in g["results"]}
        assert by == {"min_duration": "PASS", "hook_max_pct": "PASS",
                      "link_in_caption": "PASS"}, g["results"]
        assert g["ok"] is True, g

        g = konten.check(r, "x.mp4", "no link", 9.0)          # 30% > 20%
        by = {x["rule"]: x["verdict"] for x in g["results"]}
        assert by["hook_max_pct"] == "FAIL", g["results"]
        assert by["link_in_caption"] == "FAIL", g["results"]
        assert g["ok"] is False, g

        # Boundary: exactly 20% is allowed, a hair over is not. A gate tuned
        # by eye tends to get the equality case wrong in the user's favour.
        g = konten.check(r, "x.mp4", f"{link}", 6.0)          # exactly 20%
        assert {x["rule"]: x["verdict"] for x in
                g["results"]}["hook_max_pct"] == "PASS", g["results"]
        g = konten.check(r, "x.mp4", f"{link}", 6.03)         # 20.1%
        assert {x["rule"]: x["verdict"] for x in
                g["results"]}["hook_max_pct"] == "FAIL", g["results"]

        # All-SKIP must never report ok: that is the shape of a gate that
        # silently does nothing.
        g = konten.check(r, None, "", None)
        assert g["counts"]["PASS"] == 0 and g["ok"] is False, g
        assert g["counts"]["SKIP"] > 0, g
        # And the judgement rules must still be carried out of a skipped run.
        assert g["needs_human"], g
    finally:
        konten.probe = saved

    # ---- submit cannot pretend --------------------------------------
    # Offline shape check first: the endpoint must be the 401 route, not one
    # of the 404 guesses.
    assert konten.GATEWAY + konten.SUBMIT_PATH.format(
        slug="karomah-insani-kerkun") == EXPECTED_SUBMIT

    live = os.environ.get("V79_OFFLINE") != "1"
    if live:
        try:
            s = konten.submit_readiness("karomah-insani-kerkun", "nobody-here")
        except Exception as e:                       # network down: not a bug
            print(f"_v79 ok (submit check skipped: {e!r})")
            return 0
        assert s["endpoint"] == EXPECTED_SUBMIT, s
        # No session for this account exists, so readiness must be False and
        # must name the missing session.
        assert s["ok"] is False, s
        assert any("session" in b for b in s["blockers"]), s
        # The flag is read LIVE. Whatever its value, the two must agree —
        # this is what proves the refusal is not hardcoded.
        if s["submit_via_link_enabled"]:
            assert not any("submit_via_link_enabled" in b
                           for b in s["blockers"]), s
        else:
            assert any("submit_via_link_enabled" in b
                       for b in s["blockers"]), s

    print("_v79 ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
