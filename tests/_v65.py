"""Tidak ada efek akhiran yang boleh menyala saat dia masih BICARA.

Operator: "sebab itu yang dimasak ibu, selesai baru getar jangan pas ngomong
lansung". Terukur di file terkirim: hentakan 28,99 (selisih frame) pada 30,75s
sementara kata terakhir "ikut" baru berakhir 31,00s.

Tersangkanya BUKAN goyangan. Tiga sumber terpisah, dan yang paling keras justru
bukan yang terlihat mencurigakan:

1. `_arm = _freeze_at - 0.2` - still Gibran di-overlay 0,2s LEBIH AWAL.
   Pengarmannya wajib (kalau tepat di titik klon, render jadi byte-identik),
   tapi overlay itu MEMOTONG gambar hidup: frame setelah _arm semuanya sama.
   Itu potongan gambar, bukan goyangan - terbaca sebagai "getar pas ngomong".
2. SLAM dilantai `_freeze_at`, bukan akhir bicara.
3. Flicker dilantai `_outro_start`, yang bisa lebih kecil dari akhir bicara.

Yang dijaga di sini adalah ATURANNYA, bukan angkanya: apa pun yang
beat-driven, lantainya akhir bicara. Dites lewat perilaku fungsi, bukan
dengan mencocokkan string filter - `hue=...:eval=frame` sudah membuktikan
string bisa terlihat benar sementara ffmpeg menolak seluruh graph.
"""
import json
import sys

sys.path.insert(0, "/home/ubuntu/clipper")
import edit

WORDS_JSON = "/home/ubuntu/clipper/media/uf0a29714d9fe/wyvzLKsUNF4.words.json"
BG = ("/home/ubuntu/background_music/"
      "hype_dj_nansuya_gang_jedag_jedug_ncs_copyrigh.mp3")

START, DUR, HOOK = 122.0, 28.4, 2.8

raw = json.load(open(WORDS_JSON))
ws = raw if isinstance(raw, list) else raw.get("words", [])
words = [w for w in ws if START <= float(w.get("start", 0)) < START + DUR + 2.0]
assert words, "fixture kosong"

speech_end = max(float(w.get("end", 0)) - START
                 for w in words
                 if float(w.get("end", 0)) - START <= DUR)
print("akhir bicara   : %.2fs klip (%.2fs di file jadi)"
      % (speech_end, speech_end + HOOK))

edit.OUTRO = "jamet"

# --- 1. goyangan tidak mulai sebelum bicara habis -------------------------
beats = edit._music_beats(BG, DUR + edit.OUTRO_JAMET_SECONDS + 1.0, HOOK,
                          fraction=1.0)
assert beats, "onset tidak terbaca dari track"

_, filters = edit._outro_filters(DUR, mood="hype", words=words,
                                 clip_start=START, beats=beats,
                                 speech_end=speech_end)
crop = [f for f in filters if f.startswith("crop=w=iw-")]
assert crop, "cabang jamet tidak menghasilkan crop goyangan"

import re
starts = sorted(float(m) for m in
                re.findall(r"between\(t,([0-9.]+),", crop[0]))
assert starts, "tidak ada jendela hentakan di crop"
print("hentakan pertama: %.3fs klip" % starts[0])
assert starts[0] >= speech_end - 0.001, (
    "goyangan mulai %.3fs, sebelum bicara habis %.3fs"
    % (starts[0], speech_end))

# --- 2. hentakan mengikuti ONSET, bukan periode tetap --------------------
# Setiap jendela harus bertepatan dengan sebuah onset. Periode tetap 5,77 Hz
# akan memberi jarak seragam 0,173s yang tidak menandai apa pun.
near = [min(abs(s - b) for b in beats) for s in starts]
assert max(near) <= 0.05, (
    "ada hentakan yang tidak di onset mana pun (maks selisih %.3fs) — "
    "goyangan masih pakai periode tetap" % max(near))
gaps = [starts[i + 1] - starts[i] for i in range(len(starts) - 1)]
assert gaps, "hentakan terlalu sedikit untuk diperiksa jaraknya"
spread = max(gaps) - min(gaps)
print("hentakan        : %d, jarak %.3f-%.3fs (sebaran %.3fs)"
      % (len(starts), min(gaps), max(gaps), spread))
# Kontrol negatif: periode TETAP memberi sebaran ~0. Musik sungguhan tidak.
assert spread >= 0.10, (
    "jarak hentakan terlalu seragam (sebaran %.3fs) — ini grid tetap, "
    "bukan onset musik" % spread)

# --- 3. kontrol negatif: tanpa onset, jatuh ke periode tetap -------------
_, f_none = edit._outro_filters(DUR, mood="hype", words=words,
                                clip_start=START, beats=None,
                                speech_end=speech_end)
crop_none = [f for f in f_none if f.startswith("crop=w=iw-")][0]
assert "mod(t-" in crop_none, (
    "tanpa onset harus jatuh ke periode tetap, bukan kehilangan goyangan")
assert "mod(t-" not in crop[0], (
    "dengan onset tersedia, goyangan tidak boleh pakai mod() periode tetap")
print("tanpa track     : jatuh ke periode tetap (goyangan tidak hilang)")

# --- 4. flicker dilantai akhir bicara ------------------------------------
_out_len = edit._outro_output_len(DUR, mood="hype", words=words,
                                  clip_start=START)
_end_at = max(edit._outro_start(DUR, mood="hype", words=words,
                                clip_start=START), speech_end)
fl = edit._burst_times(edit._window_beats(BG, _end_at, _out_len, HOOK), per=1)
assert fl, "flicker kosong di jendela akhiran"
assert min(fl) >= speech_end - 0.001, (
    "flicker mulai %.3fs, sebelum bicara habis %.3fs" % (min(fl), speech_end))
# per=1: satu kedipan per onset. FLASH_BURST=3 membuat 6 onset jadi 18 hit
# berjarak 0,10s — 5 Hz yang tidak menandai apa pun.
wb = edit._window_beats(BG, _end_at, _out_len, HOOK)
assert len(fl) == len(wb), (
    "flicker %d hit dari %d onset — masih dipecah jadi burst"
    % (len(fl), len(wb)))
print("flicker         : %d hit dari %d onset, mulai %.3fs"
      % (len(fl), len(wb), min(fl)))

# --- 5. slam dilantai akhir bicara ---------------------------------------
sb = edit._window_beats(BG, _end_at, _out_len, HOOK,
                        fraction=edit.SLAM_BEAT_FRACTION)
if sb:
    assert min(sb) >= speech_end - 0.001, (
        "slam mulai %.3fs, sebelum bicara habis %.3fs"
        % (min(sb), speech_end))
    print("slam            : %d hit, mulai %.3fs" % (len(sb), min(sb)))

print("\n_v65 ok — tidak ada efek akhiran sebelum bicara habis, "
      "hentakan mengikuti onset")
