"""Bersihin folder kerja render: temp_subs_* yang ketinggalan + media kedaluwarsa.

KENAPA ADA (diukur 23 Okt 2026, bukan dugaan):

  temp_subs_*: 68 folder nyangkut di /home/ubuntu/clipper, umur 25 jam sampai
  239 jam (10 hari). edit.py bikin tempdir ini per render dan menghapusnya di
  blok `finally` — tapi `finally` TIDAK jalan kalau prosesnya dibunuh SIGKILL,
  dan 23 Okt ffmpeg dibunuh OOM empat kali. Jadi setiap render yang mati
  meninggalkan satu folder plus PNG overlay di dalamnya.

  Ukurannya kecil (3,7 MB total) tapi JUMLAHnya yang jadi masalah: 68 folder
  bernama acak di root repo bikin `git status`, `ls`, dan sapuan file lain
  berisik, dan satu di antaranya (temp_subs_d4427296) masih menyimpan 66 PNG
  yang nyaris saja gw pakai sebagai bukti padahal sudah tidak lengkap.

APA YANG DIHAPUS vs TIDAK — operator menulis aturannya eksplisit:

  DIHAPUS   : yang diunduh/dibikin pipeline untuk satu render — b-roll, frame
              ekstrak, PNG overlay, file perantara, cache video sumber.
  TIDAK      : aset operator (audio template, library musik, outro, font,
              preset) dan hasil akhir klip.

Yang bikin ini aman dijalankan: fetch.py SUDAH punya struktur per-render
(MEDIA_DIR/<task_id>/, TTL 24 jam, CLIPPER_MEDIA_TTL_HOURS) dan autoclean.py
sudah menjaga jobs/ + media/ dengan daftar JAGA yang dibaca DARI KODE. Jadi
modul ini TIDAK menyentuh dua wilayah itu — cuma temp_subs_* yang belum
dipegang siapa pun. Tumpang tindih dihindari dengan pembagian wilayah, bukan
dengan berharap.

PENGAMAN (urutannya penting):
  1. Path wajib absolut, wajib di dalam ROOT, wajib cocok pola nama.
  2. Nol rm -rf dengan variabel mentah: setiap path lewat _aman() dulu.
  3. Dry-run adalah DEFAULT. Menghapus butuh apply=True eksplisit.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time

ROOT = os.environ.get("CLIPPER_HOME", "/home/ubuntu/clipper")

# Nama folder kerja yang dibuat edit.py. Dipaku ke pola supaya "work dir"
# tidak pernah bisa berarti folder lain.
POLA = re.compile(r"^temp_subs_[0-9a-f]{6,}$")

# Umur minimum sebelum boleh disentuh. Operator minta render GAGAL disimpan
# 24 jam untuk debugging — itu angka yang sama dengan TTL media di fetch.py,
# jadi dipakai ulang supaya nol kejutan.
MIN_UMUR_JAM = float(os.environ.get("CLIPPER_WORK_TTL_HOURS", "24"))

# Wilayah yang DILINDUNGI mutlak. Bukan "diharapkan tidak kena" — kalau sebuah
# path menyentuh salah satu dari ini, dia ditolak sebelum dihapus.
DILINDUNGI = (
    os.path.join(ROOT, "assets"),          # font, preset, potret
    os.path.join(ROOT, "tests"),
    os.path.join(ROOT, "jobs"),            # hasil akhir klip + audit
    os.path.join(ROOT, "media"),           # wilayah autoclean/fetch TTL
    "/home/ubuntu/background_music",       # library musik operator
    "/home/ubuntu/piper_voices",
    "/home/ubuntu/tokens",
    "/home/ubuntu/kirim",                  # file yang sudah dikirim
)


def _aman(path: str) -> tuple[bool, str]:
    """True kalau path ini boleh dihapus. Alasan ditulis, bukan diam."""
    if not path:
        return False, "path kosong"
    if not os.path.isabs(path):
        return False, "path tidak absolut"
    nyata = os.path.realpath(path)
    akar = os.path.realpath(ROOT)
    if nyata == akar:
        return False, "path ADALAH root repo"
    # Harus di dalam ROOT. realpath dipakai supaya symlink tidak bisa
    # menunjuk keluar lalu dihapus dari dalam.
    if not nyata.startswith(akar + os.sep):
        return False, f"di luar {akar}"
    for lindung in DILINDUNGI:
        l = os.path.realpath(lindung)
        if nyata == l or nyata.startswith(l + os.sep):
            return False, f"wilayah dilindungi: {lindung}"
    if not POLA.match(os.path.basename(nyata)):
        return False, f"nama tidak cocok pola {POLA.pattern}"
    if not os.path.isdir(nyata):
        return False, "bukan direktori"
    return True, "ok"


def _ukuran(path: str) -> tuple[int, int]:
    """(byte, jumlah file) di bawah path."""
    byt = n = 0
    for akar, _, nama in os.walk(path):
        for f in nama:
            try:
                byt += os.path.getsize(os.path.join(akar, f))
                n += 1
            except OSError:
                pass
    return byt, n


def _umur_jam(path: str) -> float:
    """Umur dari file TERBARU di dalamnya, bukan dari mtime foldernya.

    Jebakan yang sudah pernah kena di autoclean: mtime FOLDER berubah saat
    isinya ditambah, jadi folder yang masih dipakai bisa terlihat tua kalau
    diukur salah — dan sebaliknya. File terbaru adalah yang menjawab
    "kapan terakhir ada aktivitas di sini".
    """
    paling = os.path.getmtime(path)
    for akar, _, nama in os.walk(path):
        for f in nama:
            try:
                t = os.path.getmtime(os.path.join(akar, f))
            except OSError:
                continue
            paling = max(paling, t)
    return (time.time() - paling) / 3600.0


def kandidat() -> list[dict]:
    """Folder kerja yang LAYAK dihapus, dengan alasan per entri."""
    out = []
    try:
        isi = os.listdir(ROOT)
    except OSError as e:
        print(f"⚠️ cleanup: tidak bisa membaca {ROOT} — {e}", file=sys.stderr)
        return out

    for nama in sorted(isi):
        p = os.path.join(ROOT, nama)
        if not POLA.match(nama):
            continue
        boleh, alasan = _aman(p)
        if not boleh:
            out.append({"path": p, "hapus": False, "alasan": alasan,
                        "byte": 0, "file": 0, "umur": 0.0})
            continue
        umur = _umur_jam(p)
        byt, n = _ukuran(p)
        if umur < MIN_UMUR_JAM:
            out.append({"path": p, "hapus": False,
                        "alasan": f"masih {umur:.1f} jam (< {MIN_UMUR_JAM:.0f})",
                        "byte": byt, "file": n, "umur": umur})
            continue
        out.append({"path": p, "hapus": True,
                    "alasan": f"umur {umur:.1f} jam, sisa render yang mati",
                    "byte": byt, "file": n, "umur": umur})
    return out


def jalan(apply: bool = False) -> int:
    kand = kandidat()
    hapus = [k for k in kand if k["hapus"]]
    tahan = [k for k in kand if not k["hapus"]]

    print(f"{'HAPUS' if apply else 'DRY-RUN'} folder kerja di {ROOT}")
    print(f"  pola     : {POLA.pattern}")
    print(f"  TTL      : {MIN_UMUR_JAM:.0f} jam")
    print(f"  kandidat : {len(kand)}  layak-hapus: {len(hapus)}  ditahan: {len(tahan)}")
    print()

    if tahan:
        print("DITAHAN (dan sebabnya):")
        for k in tahan[:10]:
            print(f"  - {os.path.basename(k['path']):24} {k['alasan']}")
        if len(tahan) > 10:
            print(f"  ... {len(tahan) - 10} lagi")
        print()

    total_byte = sum(k["byte"] for k in hapus)
    total_file = sum(k["file"] for k in hapus)
    if hapus:
        print(f"AKAN DIHAPUS ({len(hapus)} folder, {total_file} file, "
              f"{total_byte / 1e6:.2f} MB):")
        for k in hapus[:12]:
            print(f"  - {os.path.basename(k['path']):24} "
                  f"{k['file']:3} file  {k['byte'] / 1e6:6.3f} MB  {k['alasan']}")
        if len(hapus) > 12:
            print(f"  ... {len(hapus) - 12} lagi")
    else:
        print("nol folder layak dihapus.")

    print()
    print("DILINDUNGI (tidak pernah disentuh modul ini):")
    for l in DILINDUNGI:
        ada = "ada" if os.path.exists(l) else "tidak ada"
        print(f"  - {l}  [{ada}]")

    if not apply:
        print()
        print("Ini DRY-RUN. Jalankan dengan --apply untuk benar-benar menghapus.")
        return 0

    dibuang = gagal = 0
    byte_nyata = 0
    for k in hapus:
        boleh, alasan = _aman(k["path"])   # dicek ULANG sebelum rm
        if not boleh:
            print(f"⚠️ cleanup: tolak {k['path']} — {alasan}", file=sys.stderr)
            gagal += 1
            continue
        try:
            shutil.rmtree(k["path"])
            dibuang += 1
            byte_nyata += k["byte"]
        except OSError as e:
            # stage, path, pesan asli — supaya kegagalan bisa ditindak, bukan
            # cuma diketahui.
            print(f"⚠️ cleanup: stage=rmtree path={k['path']} "
                  f"error={e.__class__.__name__}: {e}", file=sys.stderr)
            gagal += 1

    print()
    print(f"dihapus {dibuang} folder, {byte_nyata / 1e6:.2f} MB dibebaskan, "
          f"gagal {gagal}")
    return 1 if gagal else 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    return jalan(apply="--apply" in argv)


if __name__ == "__main__":
    raise SystemExit(main())
