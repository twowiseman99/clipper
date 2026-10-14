"""Ganti / tambah / hapus akun console tanpa ngedit file env pakai tangan.

Kenapa ada: akun console hidup di satu baris `CLIPPER_CONSOLE_USERS=` di
`~/.hermes/clipper-console.env`, dan ngeditnya pakai tangan itu dua jebakan
sekaligus — satu koma kelewat bikin SEMUA akun ga kebaca (console tetep
nyala, cuma nolak semua orang), dan sandi kebawa ke riwayat shell kalau lu
nulisnya di command line.

Makanya skrip ini:
  - sandi diminta lewat prompt (ga kelihatan, ga masuk history), atau
    di-generate acak
  - file ditulis ATOMIK (tmp + rename) dan izinnya dijaga 600: gagal di
    tengah jalan ga boleh ninggalin file akun yang setengah
  - baris lain di file env ga disentuh
  - dia NGECEK hasilnya lewat HTTP ke console yang beneran jalan, bukan
    cuma bilang "udah diganti"

Pakai:
    python3 scripts/console_passwd.py --list
    python3 scripts/console_passwd.py --set oden              # prompt
    python3 scripts/console_passwd.py --set oden --generate   # acak 20 char
    python3 scripts/console_passwd.py --remove nama
"""
import argparse
import getpass
import os
import re
import secrets
import shutil
import string
import subprocess
import sys
import tempfile

ENV_PATH = os.environ.get(
    "CLIPPER_CONSOLE_ENV",
    os.path.expanduser("~/.hermes/clipper-console.env"))
KUNCI = "CLIPPER_CONSOLE_USERS"
SERVICE = "clipper-console"
# Sandi acak: huruf+angka doang, tanpa simbol. Simbol di basic-auth URL
# (`https://user:sandi@host`) harus di-escape dan gampang bikin orang
# nyangka sandinya salah. 20 char alnum = ~103 bit, cukup jauh.
ABJAD = string.ascii_letters + string.digits


def baca_env(path=None):
    path = path or ENV_PATH
    if not os.path.exists(path):
        return [], {}
    with open(path, encoding="utf-8") as f:
        baris = f.read().splitlines()
    akun = {}
    for ln in baris:
        if ln.strip().startswith(KUNCI + "="):
            nilai = ln.split("=", 1)[1].strip()
            if len(nilai) >= 2 and nilai[0] == nilai[-1] and nilai[0] in "\"'":
                nilai = nilai[1:-1]
            for bagian in nilai.split(","):
                bagian = bagian.strip()
                if bagian and ":" in bagian:
                    nama, sandi = bagian.split(":", 1)
                    if nama.strip() and sandi:
                        akun[nama.strip()] = sandi
    return baris, akun


def tulis_env(baris, akun, path=None):
    """Tulis ulang file env, cuma baris akun yang diganti.

    Atomik lewat tmp+rename di folder yang SAMA (rename antar filesystem
    bukan atomik), dan mode 600 dipasang SEBELUM isinya ditulis -- bukan
    sesudah, karena di jeda itu sandi kebaca user lain.
    """
    path = path or ENV_PATH
    if not akun:
        raise SystemExit("nolak nulis: daftar akun kosong, console bakal "
                         "nolak semua orang")
    for nama, sandi in akun.items():
        if "," in nama or ":" in nama or "," in sandi:
            raise SystemExit("nama/sandi ga boleh ada koma atau titik dua: %r"
                             % nama)
    nilai = ",".join("%s:%s" % (n, s) for n, s in sorted(akun.items()))
    baris_baru = '%s="%s"' % (KUNCI, nilai)
    keluar, ketemu = [], False
    for ln in baris:
        if ln.strip().startswith(KUNCI + "="):
            if not ketemu:
                keluar.append(baris_baru)
                ketemu = True
        else:
            keluar.append(ln)
    if not ketemu:
        keluar.append(baris_baru)

    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".console-env-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(keluar).rstrip("\n") + "\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    os.chmod(path, 0o600)


def restart():
    if not shutil.which("systemctl"):
        return "systemctl ga ada -- restart console-nya sendiri"
    r = subprocess.run(["systemctl", "--user", "restart", SERVICE],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return "restart gagal: " + (r.stderr or "").strip()
    return ""


def cek_http(nama, sandi, port=None):
    """Bukti sandi barunya KEPAKAI: 200 pakai sandi baru, 401 tanpa sandi.

    Tanpa langkah ini skrip ini cuma bisa bilang "file udah ditulis", dan
    file yang bener dengan service yang belum baca ulang itu persis bentuk
    kegagalannya.
    """
    import base64
    import json
    import urllib.error
    import urllib.request
    port = port or os.environ.get("CLIPPER_CONSOLE_PORT", "8001")
    # Dicek di rute yang BERPAGAR, bukan `/sehat`. Verifikator ini awalnya
    # nembak `/sehat` dan dapet 200/200/200 -- sandi ngawur pun "lolos",
    # karena rute itu sengaja kebuka buat health check. Alat verifikasi
    # yang nembak endpoint tanpa pagar selalu bilang OK.
    url = "http://127.0.0.1:%s/" % port

    def panggil(auth):
        req = urllib.request.Request(url)
        if auth:
            req.add_header("Authorization", "Basic " + base64.b64encode(
                auth.encode()).decode())
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception as e:
            return str(e)

    hasil = {
        "pakai_sandi_baru": panggil("%s:%s" % (nama, sandi)),
        "tanpa_sandi": panggil(None),
        "sandi_ngawur": panggil("%s:salah-banget" % nama),
    }
    print(json.dumps(hasil, ensure_ascii=False))
    ok = (hasil["pakai_sandi_baru"] == 200
          and hasil["tanpa_sandi"] == 401
          and hasil["sandi_ngawur"] == 401)
    return ok, hasil


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="daftar nama akun")
    ap.add_argument("--set", metavar="NAMA", help="ganti/tambah akun")
    ap.add_argument("--remove", metavar="NAMA", help="hapus akun")
    ap.add_argument("--generate", action="store_true",
                    help="dengan --set: sandi acak 20 karakter")
    ap.add_argument("--no-restart", action="store_true")
    a = ap.parse_args(argv)

    baris, akun = baca_env()

    if a.list or not (a.set or a.remove):
        print("file  : %s" % ENV_PATH)
        print("mode  : %s" % (oct(os.stat(ENV_PATH).st_mode & 0o777)
                              if os.path.exists(ENV_PATH) else "-"))
        print("akun  : %s" % (", ".join(sorted(akun)) or "(kosong)"))
        return 0

    if a.remove:
        if a.remove not in akun:
            raise SystemExit("ga ada akun bernama %r" % a.remove)
        if len(akun) == 1:
            raise SystemExit("itu akun terakhir -- hapus bakal bikin console "
                             "nolak semua orang")
        akun.pop(a.remove)
        tulis_env(baris, akun)
        print("dihapus: %s" % a.remove)
        pesan = "" if a.no_restart else restart()
        if pesan:
            print(pesan)
        return 0

    nama = a.set
    if a.generate:
        sandi = "".join(secrets.choice(ABJAD) for _ in range(20))
    else:
        sandi = getpass.getpass("sandi baru buat %s: " % nama)
        ulang = getpass.getpass("ulangi: ")
        if sandi != ulang:
            raise SystemExit("ga sama, ga ada yang diubah")
    if len(sandi) < 12:
        raise SystemExit("minimal 12 karakter -- ini kebuka ke internet")

    lama_ada = nama in akun
    akun[nama] = sandi
    tulis_env(baris, akun)
    print("%s: %s" % ("diganti" if lama_ada else "ditambah", nama))

    if a.no_restart:
        print("belum di-restart, console masih pakai sandi lama")
        return 0
    pesan = restart()
    if pesan:
        print(pesan)
        return 1
    import time
    time.sleep(2.5)
    ok, _ = cek_http(nama, sandi)
    if not ok:
        print("GAGAL diverifikasi -- sandi lama mungkin masih kepakai")
        return 1
    if a.generate:
        print("\nsandi buat %s (simpen sekarang, ga ditampilin lagi):" % nama)
        print("  %s" % sandi)
    print("\nterverifikasi lewat HTTP: sandi baru 200, tanpa sandi 401, "
          "sandi ngawur 401")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
