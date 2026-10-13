"""Bersihin media/klip lama otomatis, SEKALI per tick terus exit.

Permintaan operator: "jadiin behaviour kalo ud oke hapus semua video dan
image yg di download selain source music dan codenya". Jadi yang dibuang
cuma hasil UNDUHAN dan hasil GENERATE; source, audio, kode, dan bukti bug
ga pernah disentuh.

Bentuknya cron per-tick (bukan proses yang jalan terus) karena di kotak ini
sudah terukur: proses yang dimiliki chat mati diam-diam pas sesi tutup, dan
job-nya berhenti tanpa bilang apa-apa.

Sifat yang dijaga (dites di tests/_v82.py):
  1. DIEM kalau ga ada yang perlu dibuang -- cron yang nyetak tiap tick
     bakal spam operator tiap jam.
  2. Daftar JAGA menang atas aturan apa pun. Pernah kejadian: hapus
     media/uf0a29714d9fe/ bikin _v65 FAIL, dan 9 tes lain lolos diam-diam
     karena nge-skip. Daftar jaga dibaca dari tes + KNOWN_ISSUES, bukan
     ditulis tangan.
  3. Klip terbaru disisain (default 5) -- operator minta "selain version
     terbaru".
  4. Dry-run default. Hapus beneran butuh --apply.

Jalanin:
    python3 autoclean.py            # cuma ngitung, ga hapus
    python3 autoclean.py --apply    # hapus beneran
"""
import glob
import os
import re
import shutil
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))

# Umur minimum sebelum sesuatu boleh dibuang. Render terlama yang keukur
# 6,6 menit, jadi apa pun yang lebih muda dari sejam bisa jadi masih
# dipegang proses lain.
MIN_UMUR_JAM = float(os.environ.get("CLIPPER_CLEAN_MIN_AGE_H", "24"))

# Berapa klip terbaru yang disisain. Operator: "selain version terbaru".
SISAIN_KLIP = int(os.environ.get("CLIPPER_CLEAN_KEEP", "5"))

# Ambang lapor. Di bawah ini cron DIEM -- ga ada gunanya ngasih tau
# operator kalau yang kebuang cuma beberapa megabyte.
LAPOR_MIN_MB = float(os.environ.get("CLIPPER_CLEAN_REPORT_MB", "200"))


def _mtime_terbaru(path):
    """Umur sesuatu = file TERBARU di dalamnya, bukan mtime foldernya.

    Jebakan yang kena di tes: mtime folder ikut berubah tiap kali ada file
    ditulis/dihapus di dalamnya, jadi folder b-roll yang isinya tua bisa
    kelihatan baru dan lolos terus dari pembersihan.
    """
    if os.path.isfile(path):
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0.0
    paling = 0.0
    for dp, _d, fs in os.walk(path):
        for f in fs:
            try:
                paling = max(paling, os.path.getmtime(os.path.join(dp, f)))
            except OSError:
                pass
    return paling


def _ukuran(path):
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for dp, _d, fs in os.walk(path):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def daftar_jaga():
    """Path yang GA BOLEH dihapus, dibaca dari sumbernya.

    Ditemukan dari kode, bukan ditulis tangan: daftar tangan bakal basi
    begitu ada tes baru, dan yang rusak baru ketauan berbulan kemudian.
    """
    jaga = set()

    # 1. Apa pun yang disebut file tes. Ini yang kelewat dulu: 11 tes
    #    nunjuk file di luar repo, cuma 1 yang FAIL pas datanya ilang.
    pola = re.compile(r"(?:media|jobs)/[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)*")
    for t in glob.glob(os.path.join(BASE, "tests", "_v*.py")):
        try:
            isi = open(t, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        for m in pola.findall(isi):
            jaga.add(os.path.join(BASE, m))
            jaga.add(os.path.join(BASE, os.path.dirname(m)))

    # 2. Bukti bug yang masih open. Buang ini = buang satu-satunya bukti.
    #    Polanya ga boleh dipaku ke /home/<user>: pernah kena di tes, path
    #    di luar /home ga kekenalin dan bukti bug masuk daftar hapus.
    ki = os.path.join(BASE, "KNOWN_ISSUES.md")
    if os.path.exists(ki):
        isi = open(ki, encoding="utf-8", errors="replace").read()
        for m in re.findall(r"/\S*?/(?:jobs|media)/[A-Za-z0-9_.\-/]+", isi):
            m = m.rstrip(".,)")
            jaga.add(m)
            # sekalian semua file dengan prefix yang sama (audit.json, dll)
            batang = re.sub(r"\.(mp4|json|txt)$", "", m)
            for s in glob.glob(batang + "*"):
                jaga.add(s)

    # 3. Fixture yang ke-commit. Ini di dalam repo, tapi disebut eksplisit
    #    biar aturan apa pun ga bisa nyentuh.
    for f in glob.glob(os.path.join(BASE, "tests", "fixtures", "*")):
        jaga.add(f)

    return jaga


def kandidat():
    """Daftar (path, byte, alasan) yang boleh dibuang."""
    jaga = daftar_jaga()
    batas = time.time() - MIN_UMUR_JAM * 3600
    out = []

    def kejaga(p):
        p = os.path.abspath(p)
        if p in jaga:
            return True
        # induk atau anak dari yang dijaga juga aman
        for j in jaga:
            if p.startswith(j.rstrip("/") + "/") or j.startswith(p.rstrip("/") + "/"):
                return True
        return False

    # --- klip hasil generate: sisain N terbaru --------------------------
    klip = sorted(glob.glob(os.path.join(BASE, "jobs", "clip_*.mp4")),
                  key=lambda p: os.path.getmtime(p), reverse=True)
    for p in klip[SISAIN_KLIP:]:
        if kejaga(p) or os.path.getmtime(p) > batas:
            continue
        batang = re.sub(r"\.mp4$", "", p)
        for s in glob.glob(batang + "*"):
            if not kejaga(s):
                out.append((s, _ukuran(s), "klip lama (bukan %d terbaru)" % SISAIN_KLIP))

    # --- media hasil UNDUHAN -------------------------------------------
    # Ini yang operator sebut "video yg di download". Transkrip .words.json
    # ikut kebuang karena bisa dibikin ulang dari videonya -- kecuali yang
    # dipakai tes, dan itu udah masuk daftar jaga.
    for d in glob.glob(os.path.join(BASE, "media", "*")):
        if not os.path.isdir(d) or kejaga(d):
            continue
        if _mtime_terbaru(d) > batas:
            continue
        out.append((d, _ukuran(d), "b-roll/sumber ke-download (bisa diambil ulang)"))

    # --- gambar hasil generate -----------------------------------------
    for pola_img in ("media/*.png", "media/*.jpg", "jobs/*.png", "jobs/*.jpg"):
        for p in glob.glob(os.path.join(BASE, pola_img)):
            if kejaga(p) or os.path.getmtime(p) > batas:
                continue
            out.append((p, _ukuran(p), "gambar ke-download/generate"))

    return out


def jalan(apply=False):
    pilih = kandidat()
    total = sum(b for _p, b, _a in pilih)
    mb = total / 1e6

    if not pilih:
        return 0, 0.0, ""          # DIEM: ga ada yang perlu dibuang

    if apply:
        for p, _b, _a in pilih:
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
            except OSError:
                pass

    if mb < LAPOR_MIN_MB:
        return len(pilih), mb, ""  # DIEM: kekecilan buat dilaporin

    alasan = {}
    for _p, b, a in pilih:
        alasan[a] = alasan.get(a, 0) + b
    baris = ["Clipper auto-clean: %s %d item, %.1f GB"
             % ("hapus" if apply else "KETEMU (dry-run)", len(pilih), mb / 1000)]
    for a, b in sorted(alasan.items(), key=lambda kv: -kv[1]):
        baris.append("  %-46s %6.2f GB" % (a, b / 1e9))
    baris.append("  dijaga: source, audio, kode, bukti bug, fixture tes")
    return len(pilih), mb, "\n".join(baris)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    apply = "--apply" in argv
    n, mb, pesan = jalan(apply=apply)
    if pesan:
        print(pesan)
    elif "--verbose" in argv:
        print("auto-clean: %d item / %.1f MB, di bawah ambang lapor" % (n, mb))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
