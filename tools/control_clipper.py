#!/usr/bin/env python3
"""control-clipper -- nyetir console Clipper kayak user, buat bukti.

Dipakai `verify-clipper`. Dia NGGAK ngetes apa-apa sendiri; dia cuma
ngasih perintah yang bisa dipanggil satu-satu, biar feature map yang
nentuin apa yang dibuktiin.

Kenapa instance sendiri, bukan console hidup di :8001 -- console itu
punya operator. Ngedrive punya dia = nambah baris ke antrean beneran dan
bisa mulai render 800 detik. Jadi tiap verifikasi nyalain instance
sendiri: port sendiri, DB sendiri, akun sendiri, folder token sendiri.

Perintah:
  launch        nyalain instance verifikasi, nunggu sampai KEPAKAI
  doctor        read-only: instance ini layak didrive atau nggak
  browser       nyetir halaman pakai Playwright (lihat --help)
  http          ambil satu halaman pakai kredensial instance ini
  cleanup       matiin instance yang DIA yang nyalain; bukti TIDAK dihapus

Yang dipegang:
  - Bukti numpuk di artifacts/<fitur>/ dan HIDUP setelah cleanup.
  - Cleanup matiin PID dari file state, bukan pkill nama proses.
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(tempfile.gettempdir(), "verify-clipper.json")
ARTIFACTS = os.path.join(REPO, "artifacts")
PY = os.path.join(REPO, ".venv", "bin", "python")

PORT = int(os.environ.get("VERIFY_PORT", "8042"))
AKUN = "verify"
SANDI = "verify-local-only"


def _state():
    if os.path.exists(STATE):
        with open(STATE) as f:
            return json.load(f)
    return {}


def _simpan(d):
    with open(STATE, "w") as f:
        json.dump(d, f, indent=2)


def _url(path):
    return "http://127.0.0.1:%d%s" % (PORT, path)


def _ambil(path, timeout=5):
    """GET pakai Basic Auth instance ini. Balik (status, body)."""
    import base64

    req = urllib.request.Request(_url(path))
    tok = base64.b64encode(("%s:%s" % (AKUN, SANDI)).encode()).decode()
    req.add_header("Authorization", "Basic " + tok)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, str(e)


# ---------------------------------------------------------------- launch

def launch(args):
    """Nyalain instance verifikasi dari data dir KOSONG.

    'Siap' di sini bukan 'proses nyala' dan bukan juga '/sehat jawab' --
    /sehat sengaja kebuka tanpa sandi, jadi dia jawab 200 walau tabel
    antreannya belum kebikin. Yang ditungguin halaman '/' DI BALIK SANDI
    bisa dirender, karena itu yang beneran user pakai.
    """
    lama = _state()
    if lama.get("pid") and _hidup(lama["pid"]):
        print("udah jalan: pid %s port %s" % (lama["pid"], lama["port"]))
        return 0

    data = tempfile.mkdtemp(prefix="verify-clipper-")
    env = dict(os.environ)
    env.update({
        "CLIPPER_CONSOLE_PORT": str(PORT),
        "CLIPPER_CONSOLE_HOST": "127.0.0.1",
        "CLIPPER_CONSOLE_USERS": "%s:%s" % (AKUN, SANDI),
        "CLIPPER_QUEUE_DB": os.path.join(data, "queue.db"),
        "CLIPPER_TOKEN_DIR": os.path.join(data, "tokens"),
        "CLIPPER_JOB_OUT": os.path.join(data, "out"),
        "CLIPPER_JOB_LOCK": os.path.join(data, "job.lock"),
    })
    os.makedirs(env["CLIPPER_TOKEN_DIR"], exist_ok=True)
    os.makedirs(env["CLIPPER_JOB_OUT"], exist_ok=True)

    log = open(os.path.join(data, "console.log"), "w")
    p = subprocess.Popen([PY, os.path.join(REPO, "render_console.py")],
                         cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT)

    batas = time.time() + 30
    siap = False
    while time.time() < batas:
        if p.poll() is not None:
            print("console mati pas start. log:", log.name)
            print(open(log.name).read()[-1500:])
            return 1
        st, body = _ambil("/")
        # KEPAKAI = halaman di balik sandi kebentuk, bukan cuma port kebuka.
        if st == 200 and "Clipper" in body:
            siap = True
            break
        time.sleep(0.4)

    if not siap:
        print("ga nyampe kepakai dalam 30s. log:", log.name)
        p.send_signal(signal.SIGTERM)
        return 1

    _simpan({"pid": p.pid, "port": PORT, "data": data, "log": log.name})
    print("launch ok | pid %d | %s | data %s" % (p.pid, _url("/"), data))
    return 0


def _hidup(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- doctor

def doctor(args):
    """Read-only: instance ini layak didrive?

    Nol tulisan, nol mutasi. Tiap jawaban 'ya' harus punya buktinya
    sendiri -- bukan satu angka yang mewakili semuanya.
    """
    s = _state()
    gagal = []

    def cek(label, ok, rinci=""):
        print("  %-26s %s %s" % (label, "ok  " if ok else "GAGAL", rinci))
        if not ok:
            gagal.append(label)

    cek("state file", bool(s), STATE)
    if not s:
        print("\nbelum ada instance. jalanin: control_clipper.py launch")
        return 1

    cek("pid hidup", _hidup(s.get("pid")), "pid %s" % s.get("pid"))

    # Port ini PUNYA KITA, bukan kebetulan ada yang jawab.
    punya = False
    try:
        out = subprocess.run(["ss", "-ltnp"], capture_output=True,
                             text=True).stdout
        for baris in out.splitlines():
            if ":%d " % s["port"] in baris and "pid=%d" % s["pid"] in baris:
                punya = True
    except Exception as e:
        print("  (ss gagal: %s)" % e)
    cek("port punya kita", punya, "port %s" % s.get("port"))

    st, body = _ambil("/sehat")
    cek("/sehat jawab", st == 200, "status %s" % st)

    # Auth beneran ngegigit: tanpa sandi harus 401.
    import base64
    req = urllib.request.Request(_url("/"))
    kode = 0
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            kode = r.status
    except urllib.error.HTTPError as e:
        kode = e.code
    except Exception:
        pass
    cek("tanpa sandi ditolak", kode == 401, "status %s" % kode)

    st, body = _ambil("/")
    cek("halaman kepakai", st == 200 and "Clipper" in body, "status %s" % st)

    # DB-nya punya instance ini, bukan DB operator.
    db = os.path.join(s.get("data", ""), "queue.db")
    cek("DB terisolasi", os.path.exists(db), db)

    print("\n%s" % ("semua lolos" if not gagal else "GAGAL: %d" % len(gagal)))
    return 1 if gagal else 0


# --------------------------------------------------------------- browser

def browser(args):
    """Nyetir halaman pakai Playwright, pegangan ARIA, bukan koordinat."""
    from playwright.sync_api import sync_playwright

    s = _state()
    if not s:
        print("belum ada instance; launch dulu")
        return 1

    keluar = os.path.join(ARTIFACTS, args.fitur)
    os.makedirs(keluar, exist_ok=True)

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(
            viewport={"width": args.width, "height": args.height},
            http_credentials={"username": AKUN, "password": SANDI},
        )
        page = ctx.new_page()
        page.goto(_url(args.path), wait_until="load", timeout=30000)

        if args.fill:
            for pasangan in args.fill:
                nama, nilai = pasangan.split("=", 1)
                page.fill("[name=%s]" % nama, nilai)

        if args.click:
            page.get_by_role("button", name=args.click).first.click()
            page.wait_for_load_state("load")

        hasil = {}
        if args.snapshot:
            aria = page.locator("body").inner_text()
            jalur = os.path.join(keluar, args.snapshot)
            with open(jalur, "w") as f:
                f.write(aria)
            hasil["snapshot"] = jalur
        if args.screenshot:
            jalur = os.path.join(keluar, args.screenshot)
            page.screenshot(path=jalur, full_page=True)
            hasil["screenshot"] = jalur
        if args.expect:
            # Dicocokin ke TEKS YANG USER BACA, bukan HTML mentah.
            # Pelajaran dari putaran pertama: `name=opening` ada di sumber
            # tapi page.content() ngasih `name="opening"`, jadi cek HTML
            # mentah bisa merah padahal fiturnya sehat -- dan itu bikin
            # harness ini ngajarin hal yang salah. Teks terlihat juga yang
            # beneran kena kalau labelnya berubah.
            terlihat = page.locator("body").inner_text()
            for frasa in args.expect:
                ada = frasa in terlihat
                print("  expect %-34s %s" % (frasa[:34], "ok" if ada else "GA ADA"))
                if not ada:
                    hasil["gagal"] = hasil.get("gagal", 0) + 1

        if args.expect_handle:
            # Buat pegangan form yang GA kelihatan sebagai teks: tanya DOM,
            # jangan nyocokin string HTML.
            for nama in args.expect_handle:
                ada = page.locator("[name=%s]" % nama).count() > 0
                print("  handle %-34s %s" % (nama, "ok" if ada else "GA ADA"))
                if not ada:
                    hasil["gagal"] = hasil.get("gagal", 0) + 1

        ctx.close()
        b.close()

    for k, v in hasil.items():
        print("  %-10s %s" % (k, v))
    return 1 if hasil.get("gagal") else 0


def http(args):
    st, body = _ambil(args.path)
    print("status", st)
    if args.expect:
        n = 0
        for frasa in args.expect:
            ada = frasa in body
            print("  expect %-34s %s" % (frasa[:34], "ok" if ada else "GA ADA"))
            n += 0 if ada else 1
        return 1 if n else 0
    print(body[:2000])
    return 0


# -------------------------------------------------------------- cleanup

def cleanup(args):
    """Matiin instance yang DIA yang nyalain. Bukti TIDAK dihapus.

    Bunuh pakai PID dari file state -- jangan pernah pkill nama proses,
    karena console operator di :8001 jalan dari file yang sama persis.
    """
    s = _state()
    if not s:
        print("ga ada yang perlu dimatiin")
        return 0

    pid = s.get("pid")
    if pid and _hidup(pid):
        os.kill(int(pid), signal.SIGTERM)
        batas = time.time() + 10
        while time.time() < batas and _hidup(pid):
            time.sleep(0.3)
        if _hidup(pid):
            os.kill(int(pid), signal.SIGKILL)
        print("mati: pid %s" % pid)
    else:
        print("pid %s udah mati" % pid)

    data = s.get("data", "")
    if data and data.startswith(tempfile.gettempdir()) and os.path.isdir(data):
        shutil.rmtree(data, ignore_errors=True)
        print("data dir dibuang: %s" % data)

    os.remove(STATE)
    print("bukti TETAP di: %s" % ARTIFACTS)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("launch").set_defaults(fn=launch)
    sub.add_parser("doctor").set_defaults(fn=doctor)
    sub.add_parser("cleanup").set_defaults(fn=cleanup)

    b = sub.add_parser("browser")
    b.add_argument("--path", default="/")
    b.add_argument("--fitur", default="scratch")
    b.add_argument("--fill", action="append")
    b.add_argument("--click")
    b.add_argument("--expect", action="append")
    b.add_argument("--expect-handle", action="append")
    b.add_argument("--snapshot")
    b.add_argument("--screenshot")
    b.add_argument("--width", type=int, default=1280)
    b.add_argument("--height", type=int, default=900)
    b.set_defaults(fn=browser)

    h = sub.add_parser("http")
    h.add_argument("--path", default="/sehat")
    h.add_argument("--expect", action="append")
    h.set_defaults(fn=http)

    a = ap.parse_args()
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
