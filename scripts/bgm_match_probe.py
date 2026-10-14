"""Buktiin lagu MANA yang beneran ada di audio klip yang DIKIRIM.

Kenapa perlu: "BGM-nya kepakai" ga bisa disertifikasi dari filter graph atau
dari parameter yang diminta. Yang nentuin cuma byte audio di file jadi.

TIGA INSTRUMEN DICOBA DI SINI, DUA GAGAL. Ini bagian yang penting, karena
yang gagal itu kelihatan "jalan" -- urutannya bener, cuma marginnya tipis,
dan margin tipis ga membuktikan apa-apa:

  1. `axcorrelate` + `astats "Max level"` -> 0,95 / 0,93 / 0,88, rasio 1,02x.
     Yang keukur puncak amplitudo, ketutup energi suara orang.
  2. Korelasi ENVELOPE energi 20 ms, median 12 jendela -> rasio 1,10x.
     Pola ketukan ikut keredam waktu musiknya di-duck di bawah vokal.
  3. Kemiripan spektrum rata-rata di outro -> rasio 1,05x. Timbre musik
     pop mirip-mirip semua; alat ini ga bisa milih.
  4. YANG DIPAKAI: korelasi silang WAVEFORM ternormalisasi (NCC) antara
     potongan pendek klip dan SELURUH lagu, puncak dicari di semua offset.
     -> 0,36 vs 0,13 vs 0,08 = rasio 2,9x. Tajam, karena yang dicari
     kecocokan fase sampel, dan itu cuma kejadian kalau byte lagunya
     beneran ada di mixdown.

Jendelanya diambil dari EKOR klip, tempat omongan udah berhenti; di tengah
klip vokal menang dan semua kandidat jadi rendah bareng.

KONTROL NEGATIF WAJIB: minimal satu lagu yang TIDAK dipakai harus diukur
pakai alat yang sama di jendela yang sama. Tanpa itu, angka tinggi bisa cuma
sifat alat ukurnya -- dan di skrip ini itu BUKAN hipotesis, dua instrumen
pertama persis gagal begitu.

Pakai:
    python3 scripts/bgm_match_probe.py klip.mp4 dugaan.mp3 kontrol.mp3 [...]
"""
import os
import subprocess
import sys
import tempfile
import wave

# Ambang rasio pemenang:kandidat-berikutnya yang dianggap konklusif.
# Dari pengukuran: alat yang bener ngasih 2,9x, alat yang tumpul 1,02-1,10x.
# 2,0x duduk di antaranya dengan jarak lega ke dua-duanya.
AMBANG = float(os.environ.get("CLIPPER_BGM_PROBE_MIN_RATIO", "2.0"))
AR = 22050


def _wav(src, out, start, dur):
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-ss", str(start), "-t", str(dur), "-i", src,
         "-vn", "-ac", "1", "-ar", str(AR), out],
        check=True, capture_output=True)
    import numpy as np
    with wave.open(out) as w:
        return np.frombuffer(w.readframes(w.getnframes()),
                             dtype="<i2").astype(float)


def _durasi(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def ncc(pendek, panjang):
    """Puncak korelasi silang ternormalisasi di semua offset.

    Normalisasinya pakai energi LOKAL potongan panjang per jendela (lewat
    jumlah kumulatif), bukan energi total: tanpa itu bagian lagu yang
    kenceng selalu menang cuma karena dia kenceng.
    """
    import numpy as np
    s = pendek - pendek.mean()
    L = panjang - panjang.mean()
    if len(s) < 2 or len(L) <= len(s):
        return 0.0
    n = 1 << int(np.ceil(np.log2(len(L) + len(s))))
    r = np.fft.irfft(np.fft.rfft(L, n) * np.conj(np.fft.rfft(s, n)), n)
    c = np.cumsum(np.concatenate(([0.0], L ** 2)))
    w = len(s)
    e = c[w:] - c[:-w]
    r = r[:len(e)]
    return float(np.max(np.abs(r) / (np.sqrt(e * np.sum(s ** 2)) + 1e-9)))


def cocokkan(klip, kandidat, tmp, detik=3.0, dari_ekor=4.0):
    hasil = []
    probe = _wav(klip, os.path.join(tmp, "probe.wav"),
                 max(_durasi(klip) - dari_ekor, 0.0), detik)
    for i, k in enumerate(kandidat):
        try:
            penuh = _wav(k, os.path.join(tmp, "c%d.wav" % i), 0, 240)
        except subprocess.CalledProcessError:
            hasil.append((0.0, k))
            continue
        hasil.append((ncc(probe, penuh), k))
    hasil.sort(reverse=True)
    return hasil


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    klip, kandidat = argv[0], argv[1:]
    if len(kandidat) < 2:
        print("butuh minimal 2 kandidat: satu dugaan + satu kontrol negatif")
        return 2
    tmp = tempfile.mkdtemp(prefix="bgmprobe_")
    hasil = cocokkan(klip, kandidat, tmp)
    for nilai, k in hasil:
        print("%8.4f  %s" % (nilai, os.path.basename(k)))
    rasio = hasil[0][0] / max(hasil[1][0], 1e-9)
    print("\nterkuat: %s" % os.path.basename(hasil[0][1]))
    print("rasio ke kandidat berikutnya: %.1fx (ambang %.1fx)"
          % (rasio, AMBANG))
    if rasio < AMBANG:
        print("TIDAK KONKLUSIF: jaraknya terlalu dekat buat nyimpulin apa pun")
        return 1
    print("KONKLUSIF: lagu itu ada di audio file yang dikirim")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
