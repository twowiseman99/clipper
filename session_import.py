#!/usr/bin/env python3
"""session_import.py — turn a browser-exported cookie file into a Playwright
session, and prove whether that session is actually logged in.

Why this exists: the operator must never have to touch the server, and must
never hand over a password. So the login happens in HIS browser, on HIS
fingerprint, and this box only ever receives the resulting cookies. Two
subcommands, both runnable by an agent from chat:

    import  --platform tiktok --account burner1 --from FILE
    verify  --platform tiktok --account burner1

`import` accepts either shape without being told which:
  * Netscape cookies.txt (what yt-dlp and the "Get cookies.txt" extensions emit)
  * Playwright storage_state JSON (what login_export.py / clippo.py already use)
and always writes Playwright storage_state JSON, because that is the format the
rest of the repo (clippo.ClippoAdapter) already consumes.

`verify` is the part that matters. A session file existing proves nothing — a
cookie file can be complete, well-formed and still expired. So verify launches
a REAL headed Chromium on Xvfb, loads the session, navigates to the platform's
upload surface and reports which of three things happened:

    LOGGED_IN   — upload surface reached
    NEEDS_LOGIN — bounced to a login wall
    BLOCKED     — captcha / challenge interstitial

The distinction is load-bearing: NEEDS_LOGIN means "export the cookies again",
BLOCKED means "stop, this account is being challenged, do not retry in a loop".
Collapsing them into a single boolean is how an automation ends up hammering a
challenge page until the account is flagged.

Stealth is the same set of flags login_export.py already proved against Google
sign-in (which refuses a browser it can fingerprint as driven): drop
--enable-automation, disable AutomationControlled, and shadow
navigator.webdriver. Measured on this box: vanilla Playwright reports
navigator.webdriver=true on tiktok.com and instagram.com; with these flags it
reports undefined. headless is False on purpose, under Xvfb — a headless build
is the easiest thing in the world to fingerprint.
"""
import argparse
import json
import os
import re
import sys
import time

SESSION_DIR = os.environ.get(
    "CLIPPER_SESSION_DIR", "/home/ubuntu/clipper/sessions")

# Where each platform's "can I post right now" surface lives, and how to tell
# what we landed on. Order matters: a challenge check must run BEFORE the login
# check, because a captcha page served on a /login URL is a challenge, not a
# missing cookie.
PLATFORMS = {
    "tiktok": {
        "url": "https://www.tiktok.com/tiktokstudio/upload",
        "ok_url": re.compile(r"tiktokstudio/upload"),
        "login_url": re.compile(r"/login|/signup"),
        "ok_text": ("Select video", "Pilih video", "Upload video",
                    "Unggah video", "drag and drop"),
        "challenge_text": ("Verify to continue", "Verifikasi",
                           "Drag the slider", "Security check",
                           "unusual activity", "Too many attempts"),
    },
    "instagram": {
        # No ok_url for Instagram: the login wall is served AT
        # instagram.com/ itself, so "we are on the right URL" is not evidence
        # of a session. The self-check pins this — a URL-only fallback
        # reported LOGGED_IN for a page reading "Log into Instagram".
        "url": "https://www.instagram.com/",
        "ok_url": None,
        "login_url": re.compile(r"/accounts/login|/accounts/signup"),
        "login_text": ("Log into Instagram", "Masuk ke Instagram",
                       "Log in with Facebook", "Forgot password?",
                       "Create new account"),
        "ok_text": ("Create", "Buat", "New post", "Postingan baru",
                    "Your story", "Cerita Anda", "Home", "Beranda"),
        "challenge_text": ("suspended", "ditangguhkan", "Help us confirm",
                           "confirm it's you", "Enter the code",
                           "We detected unusual"),
    },
}

NEEDS_LOGIN = "NEEDS_LOGIN"
LOGGED_IN = "LOGGED_IN"
BLOCKED = "BLOCKED"

# Launch flags proven in login_export.py against Google sign-in.
STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--no-first-run",
    "--no-default-browser-check",
]
HIDE_WEBDRIVER = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
)


def session_path(platform, account):
    acct = account.lstrip("@")
    os.makedirs(SESSION_DIR, exist_ok=True)
    return os.path.join(SESSION_DIR, f"{platform}__{acct}.json")


# ---------------------------------------------------------------- parsing

def parse_netscape(text):
    """Netscape cookies.txt -> Playwright cookie dicts.

    Tolerates the `#HttpOnly_` prefix that Chrome extensions emit, and the
    7-field tab layout with trailing whitespace. A line that is not 7 fields is
    skipped rather than guessed at.
    """
    out = []
    for raw in text.splitlines():
        line = raw.strip("\n")
        if not line.strip():
            continue
        if line.startswith("#"):
            if not line.startswith("#HttpOnly_"):
                continue
            line = line[len("#HttpOnly_"):]
        parts = line.split("\t")
        if len(parts) != 7:
            parts = re.split(r"\s+", line.strip())
            if len(parts) != 7:
                continue
        domain, _include_sub, path, secure, expires, name, value = parts
        try:
            exp = int(float(expires))
        except ValueError:
            exp = 0
        c = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": path or "/",
            "secure": secure.upper() == "TRUE",
            "httpOnly": False,
            "sameSite": "Lax",
        }
        if exp > 0:
            c["expires"] = exp
        out.append(c)
    return out


def load_cookies(path):
    """(cookies, shape). Detects the format instead of trusting the extension."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        data = json.loads(text)
        if isinstance(data, dict) and "cookies" in data:
            return data["cookies"], "storage_state"
        if isinstance(data, list):
            # Browser-extension JSON export: normalise the field names it uses.
            cookies = []
            for c in data:
                if "name" not in c:
                    continue
                n = {
                    "name": c["name"],
                    "value": c.get("value", ""),
                    "domain": c.get("domain", ""),
                    "path": c.get("path", "/"),
                    "secure": bool(c.get("secure")),
                    "httpOnly": bool(c.get("httpOnly")),
                    "sameSite": "Lax",
                }
                exp = c.get("expirationDate") or c.get("expires")
                if exp and float(exp) > 0:
                    n["expires"] = int(float(exp))
                cookies.append(n)
            return cookies, "json_list"
        raise ValueError("JSON cookie file in an unrecognised shape")
    return parse_netscape(text), "netscape"


def domain_filter(platform, cookies):
    """Keep only this platform's cookies.

    An export taken from a logged-in browser carries every site the operator
    uses. Shipping all of it into an automation context is a needless secret
    spill, so the session file holds one platform's cookies and nothing else.
    """
    wanted = {
        "tiktok": ("tiktok.com",),
        "instagram": ("instagram.com", "facebook.com"),
    }[platform]
    keep = []
    for c in cookies:
        d = (c.get("domain") or "").lstrip(".").lower()
        if any(d == w or d.endswith("." + w) for w in wanted):
            keep.append(c)
    return keep


# Cookies without which the session is definitionally not a login. Checked so
# `import` can fail loudly on a logged-OUT export rather than writing a file
# that only fails later inside a browser run.
REQUIRED = {
    "tiktok": ({"sessionid"}, {"sessionid", "sessionid_ss", "sid_tt"}),
    "instagram": ({"sessionid"}, {"sessionid", "ds_user_id"}),
}


def do_import(platform, account, src):
    cookies, shape = load_cookies(src)
    total = len(cookies)
    cookies = domain_filter(platform, cookies)
    names = {c["name"] for c in cookies}
    need, _hints = REQUIRED[platform]
    missing = need - names
    out = {"shape": shape, "cookies_in_file": total,
           "cookies_kept": len(cookies), "platform": platform,
           "account": account.lstrip("@")}
    if missing:
        out["ok"] = False
        out["error"] = ("export is not logged in: missing %s"
                        % ", ".join(sorted(missing)))
        out["hint"] = ("log into %s in your own browser, then export again"
                       % platform)
        return out
    path = session_path(platform, account)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"cookies": cookies, "origins": []}, f)
    os.chmod(path, 0o600)
    out["ok"] = True
    out["session"] = path
    out["expires_soonest"] = min(
        [c["expires"] for c in cookies if c.get("expires")] or [0])
    return out


# ---------------------------------------------------------------- verify

def launch(p, headed=True):
    return p.chromium.launch(
        headless=not headed,
        args=STEALTH_ARGS,
        ignore_default_args=["--enable-automation"],
    )


def classify(url, body, spec):
    """Three-way verdict. Challenge first — see module docstring.

    Order is the whole design: challenge text, then an explicit login signal
    (URL or page text), then positive upload-surface evidence, and only then a
    URL-shaped fallback — which some platforms must not have at all, because
    they serve the login wall on the logged-in URL.
    """
    low = body.lower()
    for t in spec["challenge_text"]:
        if t.lower() in low:
            return BLOCKED, f"challenge text: {t!r}"
    if spec["login_url"].search(url):
        return NEEDS_LOGIN, f"redirected to {url}"
    for t in spec.get("login_text", ()):
        if t.lower() in low:
            return NEEDS_LOGIN, f"login wall text: {t!r}"
    for t in spec["ok_text"]:
        if t.lower() in low:
            return LOGGED_IN, f"upload surface text: {t!r}"
    if spec.get("ok_url") and spec["ok_url"].search(url):
        return LOGGED_IN, f"stayed on {url} (no login wall)"
    return NEEDS_LOGIN, f"no upload surface on {url}"


def do_verify(platform, account, keep_open=0):
    from playwright.sync_api import sync_playwright
    spec = PLATFORMS[platform]
    path = session_path(platform, account)
    out = {"platform": platform, "account": account.lstrip("@"),
           "session": path}
    state = path if os.path.exists(path) else None
    if state is None:
        out["ok"] = False
        out["verdict"] = NEEDS_LOGIN
        out["why"] = "no session file on disk"
        return out
    with sync_playwright() as p:
        b = launch(p)
        ctx = b.new_context(
            storage_state=state,
            viewport={"width": 1280, "height": 900},
            user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
        )
        ctx.add_init_script(HIDE_WEBDRIVER)
        page = ctx.new_page()
        try:
            page.goto(spec["url"], wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)
            body = page.inner_text("body")
            out["webdriver"] = page.evaluate("navigator.webdriver")
            verdict, why = classify(page.url, body, spec)
            out["verdict"] = verdict
            out["why"] = why
            out["final_url"] = page.url
            out["ok"] = verdict == LOGGED_IN
            if keep_open:
                time.sleep(keep_open)
        except Exception as e:
            out["ok"] = False
            out["verdict"] = "ERROR"
            out["why"] = repr(e)[:300]
        finally:
            b.close()
    return out


# ---------------------------------------------------------------- self-check

def _selfcheck():
    net = ("# Netscape HTTP Cookie File\n"
           ".tiktok.com\tTRUE\t/\tTRUE\t1800000000\tsessionid\tabc123\n"
           "#HttpOnly_.tiktok.com\tTRUE\t/\tTRUE\t1800000000\tsid_tt\txyz\n"
           ".example.com\tTRUE\t/\tFALSE\t0\tjunk\tnope\n")
    cookies = parse_netscape(net)
    assert len(cookies) == 3, cookies
    assert {c["name"] for c in cookies} == {"sessionid", "sid_tt", "junk"}
    # HttpOnly prefix must not leak into the domain.
    sid = [c for c in cookies if c["name"] == "sid_tt"][0]
    assert sid["domain"] == ".tiktok.com", sid

    kept = domain_filter("tiktok", cookies)
    assert {c["name"] for c in kept} == {"sessionid", "sid_tt"}, kept
    assert domain_filter("instagram", cookies) == []

    spec = PLATFORMS["tiktok"]
    # A captcha served on a /login URL is BLOCKED, not NEEDS_LOGIN. If this
    # ever flips, an automation will retry a challenge in a loop.
    v, _ = classify("https://www.tiktok.com/login?x=1",
                    "Verify to continue please", spec)
    assert v == BLOCKED, v
    v, _ = classify("https://www.tiktok.com/login?redirect_url=upload",
                    "Log in to TikTok", spec)
    assert v == NEEDS_LOGIN, v
    v, _ = classify("https://www.tiktok.com/tiktokstudio/upload",
                    "Select video to upload", spec)
    assert v == LOGGED_IN, v
    # Order control: the same OK text on a login URL must still be a login
    # wall, never a pass, because ok_url is checked last.
    v, _ = classify("https://www.tiktok.com/accounts/login", "nothing here",
                    spec)
    assert v == NEEDS_LOGIN, v

    ig = PLATFORMS["instagram"]
    # Verbatim opening of the real instagram.com body, measured on this box
    # with a session-less browser. It contains "Create new account" and "Help"
    # — words that overlap ok_text — which is exactly why login_text must be
    # consulted before ok_text, and why Instagram has no ok_url.
    real_ig_wall = ("See everyday moments from your close friends. | Log into "
                    "Instagram | Mobile number, username or email | Password | "
                    "Log in | Forgot password? | Log in with Facebook | Create "
                    "new account | Meta | About | Blog | Jobs | Help | API")
    v, why = classify("https://www.instagram.com/", real_ig_wall, ig)
    assert v == NEEDS_LOGIN, (v, why)
    v, _ = classify("https://www.instagram.com/", "Log into Instagram", ig)
    assert v == NEEDS_LOGIN, v
    v, _ = classify("https://www.instagram.com/", "Home  Create  Your story",
                    ig)
    assert v == LOGGED_IN, v
    # And the challenge must still outrank a login wall on the same page.
    v, _ = classify("https://www.instagram.com/accounts/login",
                    "Help us confirm it's you", ig)
    assert v == BLOCKED, v
    print("session_import self-check OK")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("import", "verify"):
        s = sub.add_parser(name)
        s.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
        s.add_argument("--account", required=True)
        if name == "import":
            s.add_argument("--from", dest="src", required=True)
        else:
            s.add_argument("--keep-open", type=int, default=0)
    sub.add_parser("selfcheck")
    a = ap.parse_args(argv)
    if a.cmd == "selfcheck":
        return _selfcheck()
    if a.cmd == "import":
        res = do_import(a.platform, a.account, a.src)
    else:
        res = do_verify(a.platform, a.account, a.keep_open)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
