"""_v77 — a session verifier must not call a login wall a login.

Two bugs this pins, both found by running the real pages on this box rather
than by reading the code:

1. Instagram serves its login wall AT `instagram.com/`, the same URL a
   logged-in session lands on. The first version of classify() fell back to
   "the URL looks right, so we are in" and reported LOGGED_IN against a body
   whose first words are "Log into Instagram". A verifier that lies in the
   optimistic direction is worse than no verifier: every later upload step
   would run against a logged-out browser and fail somewhere deeper, where the
   error no longer names the cause.

2. The real Instagram wall contains the words "Create new account" and "Help".
   "Create" is also the button a logged-IN user clicks to post. So positive
   evidence alone is not safe either — the explicit login signal has to be
   consulted BEFORE the upload-surface text.

Also pinned: a captcha/challenge interstitial must outrank both. NEEDS_LOGIN
means "export cookies again"; BLOCKED means "stop, the account is being
challenged, do not retry in a loop". Collapsing the two is how an automation
hammers a challenge page until the account is flagged.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import session_import as si  # noqa: E402

IG = si.PLATFORMS["instagram"]
TT = si.PLATFORMS["tiktok"]

# Captured verbatim from a session-less headed Chromium on this box.
IG_WALL = ("See everyday moments from your close friends. | Log into Instagram "
           "| Mobile number, username or email | Password | Log in | Forgot "
           "password? | Log in with Facebook | Create new account | Meta | "
           "About | Blog | Jobs | Help | API | Privacy | Terms")
TT_WALL = ("TikTok | Feedback and help | Log in to TikTok | Manage your "
           "account, check notifications, comment on videos, and more. | Use "
           "QR code | Use phone / email / username | Continue with Facebook")
TT_WALL_URL = ("https://www.tiktok.com/login?redirect_url=https%3A%2F%2F"
               "www.tiktok.com%2Ftiktokstudio%2Fupload&enter_method=redirect")


def main():
    # 1. the measured walls are NOT logins
    v, why = si.classify("https://www.instagram.com/", IG_WALL, IG)
    assert v == si.NEEDS_LOGIN, (v, why)
    v, why = si.classify(TT_WALL_URL, TT_WALL, TT)
    assert v == si.NEEDS_LOGIN, (v, why)

    # 2. Instagram must have no URL-shaped fallback at all. If someone adds an
    #    ok_url here, bug 1 comes straight back.
    assert IG.get("ok_url") is None, IG.get("ok_url")

    # 3. a real session IS recognised, so the gate is not just "always no"
    v, why = si.classify(
        "https://www.instagram.com/",
        "Home | Search | Explore | Reels | Create | Your story", IG)
    assert v == si.LOGGED_IN, (v, why)
    v, why = si.classify("https://www.tiktok.com/tiktokstudio/upload",
                         "Select video | drag and drop", TT)
    assert v == si.LOGGED_IN, (v, why)

    # 4. challenge outranks everything, on either platform, even when the page
    #    also carries login or upload text
    v, why = si.classify("https://www.tiktok.com/login",
                         "Verify to continue | Log in to TikTok", TT)
    assert v == si.BLOCKED, (v, why)
    v, why = si.classify("https://www.instagram.com/",
                         "Create | Help us confirm it's you", IG)
    assert v == si.BLOCKED, (v, why)

    # 5. an export taken while logged OUT must be refused at import time, not
    #    written to disk to fail later inside a browser
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        si.SESSION_DIR = d
        p = os.path.join(d, "out.txt")
        with open(p, "w") as f:
            f.write("# Netscape HTTP Cookie File\n"
                    ".tiktok.com\tTRUE\t/\tTRUE\t0\ttt_csrf_token\tabc\n")
        r = si.do_import("tiktok", "x", p)
        assert r["ok"] is False and "sessionid" in r["error"], r
        assert not os.path.exists(si.session_path("tiktok", "x")), \
            "rejected export must leave no session file behind"

        # and a logged-in-shaped export must be accepted, 0600, platform-only
        p2 = os.path.join(d, "in.txt")
        with open(p2, "w") as f:
            f.write("# Netscape HTTP Cookie File\n"
                    ".tiktok.com\tTRUE\t/\tTRUE\t1900000000\tsessionid\tdead\n"
                    ".tiktok.com\tTRUE\t/\tTRUE\t1900000000\tsid_tt\tbeef\n"
                    ".mybank.com\tTRUE\t/\tTRUE\t1900000000\tsessionid\tSECRET\n")
        r = si.do_import("tiktok", "x", p2)
        assert r["ok"] is True, r
        sp = si.session_path("tiktok", "x")
        assert oct(os.stat(sp).st_mode)[-3:] == "600", oct(os.stat(sp).st_mode)
        body = open(sp).read()
        # an export carries every site the operator uses; only one may land
        assert "SECRET" not in body and "mybank" not in body, body
        assert r["cookies_kept"] == 2 and r["cookies_in_file"] == 3, r

    print("_v77 ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
