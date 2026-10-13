"""Pekerja render: ambil job dari antrean, jalanin job.py, satu-satu.

Kenapa proses sendiri, bukan thread di dalam render_console.py:
  - render makan 2,4 menit median dan ngabisin dua core. Thread di dalam
    server web bikin halaman mati total selama itu.
  - kalau server web di-restart (deploy, Caddy reload), render yang lagi
    jalan ga ikut mati.
  - sudah ada preseden terukur di kotak ini: proses yang dimiliki chat
    mati diem-diem pas sesinya tutup. Pekerja yang kepisah bisa diawasin
    systemd atau cron.

Dipanggil sekali per tick (cron) atau dibiarin jalan terus (--loop).
Bentuk sekali-per-tick lebih aman: kerja SATU job terus exit, jadi
ga ada proses panjang yang bisa mati tanpa ketauan.

    .venv/bin/python render_worker.py          # satu job, terus exit
    .venv/bin/python render_worker.py --loop    # terus-terusan
"""
import json
import os
import subprocess
import sys
import time

import render_queue as q

BASE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(BASE, ".venv", "bin", "python")
TIMEOUT = float(os.environ.get("CLIPPER_RENDER_TIMEOUT", "900"))


def _perintah(job):
    """Susun perintah job.py dari parameter yang disimpen.

    Sengaja ga pakai shell: parameter datang dari form web, dan string
    yang disambung tangan itu jalan masuk injeksi.
    """
    p = json.loads(job["params"])
    cmd = [PY, os.path.join(BASE, "job.py"), "--content", p["content"]]
    if p.get("opening"):
        cmd += ["--opening", p["opening"]]
    if p.get("portrait"):
        cmd += ["--portrait", p["portrait"]]
    if p.get("context"):
        cmd += ["--context", p["context"]]
    # Preset nentuin mood + ending + b-roll sekaligus. Flagnya --clip-type
    # (bukan --copy-style: itu buat gaya tulisan judul/deskripsi, dan satu-
    # satunya nilai sahnya 'pr-politik'). Salah flag di sini bikin render
    # gagal dengan "invalid choice" -- ketangkep pas tes pekerja nyata,
    # bukan pas baca kode.
    cmd += ["--clip-type", job["preset"]]

    # Catatan fix dititipin ke --context, bukan ke flag baru: fix = render
    # ulang penuh, dan yang perlu tau soal keluhan itu pemilih segmen.
    catatan = p.get("fix_catatan", "")
    rentang = ""
    if p.get("fix_dari") or p.get("fix_sampai"):
        rentang = " (bagian %s sampai %s yang ngaco)" % (
            p.get("fix_dari") or "awal", p.get("fix_sampai") or "akhir")
    if catatan or rentang:
        tambahan = ("Catatan revisi dari operator: " + catatan + rentang).strip()
        for i, arg in enumerate(cmd):
            if arg == "--context":
                cmd[i + 1] = (cmd[i + 1] + " " + tambahan).strip()
                break
        else:
            cmd += ["--context", tambahan]
    return cmd


def kerjakan(conn, job):
    cmd = _perintah(job)
    q.set_stage(conn, job["id"], "render")
    try:
        hasil = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=TIMEOUT, cwd=BASE)
    except subprocess.TimeoutExpired:
        q.fail(conn, job["id"],
               "render lewat batas %d detik. Render terlama yang pernah "
               "keukur 6,6 menit, jadi ini kemungkinan nyangkut." % TIMEOUT)
        return False

    if hasil.returncode != 0:
        # Ambil baris terakhir yang berisi, bukan seluruh dump: pesan ini
        # ditampilin ke orang lain di tim.
        baris = [l for l in (hasil.stderr or hasil.stdout or "").splitlines()
                 if l.strip()]
        q.fail(conn, job["id"], baris[-1] if baris else
               "job.py keluar dengan kode %d tanpa pesan" % hasil.returncode)
        return False

    # job.py nyetak JSON berisi path file + warnings. Kalau ga kebaca,
    # itu kegagalan -- jangan ngaku sukses dengan path kosong.
    #
    # JEBAKAN yang kena waktu tes nyata: JSON-nya DICETAK RAPI (multi-baris),
    # jadi ngambil baris terakhir cuma dapet "}" dan render yang sebenernya
    # SUKSES dilaporin gagal ke user. Yang bener: cari kurung buka pertama,
    # parse dari situ sampai akhir.
    keluaran = (hasil.stdout or "").strip()
    data = None
    mulai_json = keluaran.find("{")
    if mulai_json >= 0:
        try:
            data = json.loads(keluaran[mulai_json:])
        except Exception:
            data = None
    if data is None:
        # Satu kemungkinan lagi: beberapa baris JSON, yang terakhir yang valid.
        for baris in reversed(keluaran.splitlines()):
            baris = baris.strip()
            if baris.startswith("{"):
                try:
                    data = json.loads(baris)
                    break
                except Exception:
                    continue
    if data is None:
        q.fail(conn, job["id"],
               "job.py exit 0 tapi outputnya bukan JSON, jadi path filenya "
               "ga ketebak")
        return False

    path = data.get("file") or data.get("out") or ""
    if not path or not os.path.exists(path):
        q.fail(conn, job["id"],
               "job.py lapor sukses tapi filenya ga ada di %r" % path)
        return False

    q.finish(conn, job["id"], path, data.get("warnings") or [])
    return True


def sekali(conn):
    """Kerjain satu job kalau ada. Balik True kalau ada yang dikerjain."""
    q.reap_stale(conn)
    job = q.claim(conn)
    if job is None:
        return False
    print("job #%d (%s) mulai" % (job["id"], job["preset"]), flush=True)
    mulai = time.time()
    ok = kerjakan(conn, job)
    print("job #%d %s dalam %.0f detik"
          % (job["id"], "kelar" if ok else "GAGAL", time.time() - mulai),
          flush=True)
    return True


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    conn = q.connect()
    if "--loop" in argv:
        while True:
            if not sekali(conn):
                time.sleep(5)
    else:
        if not sekali(conn):
            print("antrean kosong", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
