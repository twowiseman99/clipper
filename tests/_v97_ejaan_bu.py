# Gate ejaan operator: "Buk" wajib tampil "Bu" (Dalmi 26 Okt: "Harusnya BU ajaa").
# Dua arah: kata yang wajib diganti DIGANTI, kata yang mirip TIDAK disentuh,
# timing ga gerak, jumlah kata sama.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ejaan

fails = []
kasus = [("Buk,", "Bu,"), ("Buk.", "Bu."), ("buk", "bu"), ("BUK", "BU"),
         ("Bu", "Bu"), ("buka", "buka"), ("bukan", "bukan"), ("Buku", "Buku"),
         ("ibuk", "ibuk"), ("Pak.", "Pak.")]
for src, want in kasus:
    got = ejaan.fix_word(src)
    if got != want:
        fails.append(f"{src!r} -> {got!r}, harusnya {want!r}")

words = [{"word": "Kami,", "start": 0.0, "end": 0.4},
         {"word": "Buk,", "start": 0.8, "end": 1.0},
         {"word": "bukan", "start": 1.1, "end": 1.4}]
out, hits = ejaan.apply(words)
if [w["word"] for w in out] != ["Kami,", "Bu,", "bukan"]:
    fails.append(f"apply: {[w['word'] for w in out]}")
if [(w["start"], w["end"]) for w in out] != [(w["start"], w["end"]) for w in words]:
    fails.append("timing berubah")
if words[1]["word"] != "Buk,":
    fails.append("input dimutasi (harus disalin)")
if hits != [("Buk,", "Bu,")]:
    fails.append(f"hits {hits}")

# kata ulang "anak" + "-anak" -> satu token "anak-anak", timing nutup dua-duanya
ul = [{"word": "anak", "start": 6.2, "end": 6.5},
      {"word": "-anak", "start": 6.5, "end": 7.2},
      {"word": "di", "start": 7.3, "end": 7.4}]
o2, _ = ejaan.apply(ul)
if [(w["word"], w["start"], w["end"]) for w in o2] != [("anak-anak", 6.2, 7.2), ("di", 7.3, 7.4)]:
    fails.append(f"kata ulang: {[(w['word'], w['start'], w['end']) for w in o2]}")
# tanda hubung di kata pertama ga boleh nyambung ke apa-apa
o3, _ = ejaan.apply([{"word": "-anak", "start": 0, "end": 1}])
if [w["word"] for w in o3] != ["-anak"]:
    fails.append(f"hubung di awal: {o3}")

# job.py WAJIB manggil ejaan.apply di jalur caption (modul yang ga dipanggil = ga ada)
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "job.py")).read()
if "ejaan.apply(seg_words)" not in src:
    fails.append("job.py ga manggil ejaan.apply(seg_words)")

if fails:
    print("_v97 FAIL:\n  " + "\n  ".join(fails))
    sys.exit(1)
print(f"_v97 ok: {len(kasus)} kasus ejaan + timing utuh + dipanggil job.py")
