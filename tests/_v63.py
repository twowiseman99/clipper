"""Freeze mulai SETELAH kalimat bayarannya habis, bukan sebelum dan tidak jauh.

Operator: "harusnya stop di setelah bilang suruh anak bawa bekal, karena ibu
yang paling tau, langsung freeze jedag jedug ikutin beat, berapa kali harus gw
bilang".

Dua cara gagal, dan keduanya pernah terkirim:

1. `--seconds` terlalu pendek. Freeze 5s dihitung dari UJUNG klip, jadi dengan
   --seconds 28.2 freeze mulai di detik 23.2 sementara "anak-anaknya membawa
   kotak dari rumah ... yang dimasak ibu" baru habis di detik 27.9. Kalimat
   bayarannya main di bawah frame beku dengan captionnya ditekan.
2. `--seconds` terlalu panjang. Dengan 33.4 titik snap bergerak ke 153.46s
   sumber, yang memasukkan "tapi dua perempuan rekomisasi apa itu?" (150.8-
   153.2s) — omongan lain yang tidak ada hubungannya, dan klip jadi menggantung.

Jadi angka ini punya BATAS DUA SISI, dan tes yang hanya memeriksa "freeze ada"
lolos di kedua kegagalan. Yang dijaga: titik freeze relatif terhadap kata
TERAKHIR yang relevan, diukur dari transkrip asli.
"""
import json
import sys

sys.path.insert(0, "/home/ubuntu/clipper")
import edit

WORDS = "/home/ubuntu/clipper/media/uf0a29714d9fe/wyvzLKsUNF4.words.json"
CLIP_START = 122.0
# Akhir kalimat bayaran, dibaca dari transkrip asli (bukan fixture): kata
# "dimasak"(149.6) "ikut"(149.9) — glossary memetakan ikut -> ibu.
PAYOFF_END = 149.9
# Omongan berikutnya yang TIDAK boleh ikut masuk.
NEXT_SPEECH = 150.8

raw = json.load(open(WORDS))
words_all = raw if isinstance(raw, list) else raw.get("words", [])

edit.OUTRO = "jamet"


def freeze_at(seconds):
    seg = [w for w in words_all
           if CLIP_START <= float(w.get("start", 0)) <= CLIP_START + seconds]
    st = edit._outro_start(seconds, mood="emotional", words=seg,
                           clip_start=CLIP_START)
    return None if st is None else CLIP_START + st


# --- 1. angka yang dikirim menaruh freeze di jendela yang benar ------------
SHIPPED = 28.4
got = freeze_at(SHIPPED)
assert got is not None, "--seconds %s tidak menghasilkan ending" % SHIPPED
print("--seconds %-5s -> freeze mulai sumber %.2fs" % (SHIPPED, got))
assert got >= PAYOFF_END, (
    "freeze mulai %.2fs, SEBELUM kalimat bayaran habis di %.2fs — kalimatnya "
    "akan main di bawah frame beku" % (got, PAYOFF_END))
assert got <= NEXT_SPEECH, (
    "freeze mulai %.2fs, melewati %.2fs tempat omongan lain mulai — klip "
    "memuat ucapan yang tidak diminta" % (got, NEXT_SPEECH))
print("           lolos: %.2f <= %.2f <= %.2f" % (PAYOFF_END, got, NEXT_SPEECH))

# --- 2. kontrol negatif: kedua kegagalan nyata harus DITOLAK ---------------
too_short = freeze_at(28.2)
assert too_short is not None
assert too_short < PAYOFF_END, (
    "kontrol negatif rusak: --seconds 28.2 seharusnya memotong kalimat")
print("kontrol negatif: --seconds 28.2 -> %.2fs (memotong kalimat, benar "
      "ditolak)" % too_short)

too_long = freeze_at(33.4)
assert too_long is not None
assert too_long > NEXT_SPEECH, (
    "kontrol negatif rusak: --seconds 33.4 seharusnya kelewat jauh")
print("kontrol negatif: --seconds 33.4 -> %.2fs (melewati omongan lain, "
      "benar ditolak)" % too_long)

# --- 3. jendelanya tidak boleh selebar apa saja ----------------------------
# Kalau SEMUA nilai lolos, tes ini tidak menguji apa pun.
ok = [s for s in (27.0, 28.2, 28.4, 29.0, 30.0, 31.0, 32.0, 33.4)
      if (lambda g: g is not None and PAYOFF_END <= g <= NEXT_SPEECH)(
          freeze_at(s))]
assert ok, "tidak ada nilai yang lolos — jendelanya salah"
assert len(ok) < 5, (
    "terlalu banyak nilai lolos (%s) — batasnya tidak mengikat apa pun" % ok)
print("jendela        : hanya %s yang mendarat benar dari 8 yang diuji" % ok)

# --- 4. endingnya memang jamet (freeze + beat), bukan melancholy -----------
assert edit._outro_kind("emotional") == "jamet", \
    "OUTRO=jamet harus tetap jamet walau mood emotional — operator minta " \
    "jedag-jedug, musiknya saja yang ikut transkrip"
print("ending         : jamet (freeze + beat) walau mood emotional")

print("\n_v63 ok — freeze mendarat setelah kalimat bayaran dan sebelum "
      "omongan berikutnya")
