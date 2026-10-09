"""Preset tidak boleh membungkam transkrip soal MUSIK.

Klip Gibran minta maaf ke ibu korban keracunan terkirim dengan lagu
"hype_dj_nansuya_gang_jedag_jedug" di bawahnya. Aturannya sudah ada di kode:
bgm._CLASH melarang pasangan emotional x hype. Aturan itu tidak pernah
dipanggil.

Sebabnya: `--clip-type jamet` mengisi `a.mood = "hype"` di parser, sehingga
tidak bisa dibedakan dari `--mood hype` yang diketik operator. Di hilirnya
`mood or meta["mood"]` membuat preset MENGALAHKAN transkrip, jadi yang sampai
ke bgm.pick() hanya "hype" dan tidak ada yang bertentangan dengan apa pun.

Yang dijaga tes ini: pemisahan antara "operator mengetik mood" dan "preset
memberi mood default", dan bahwa akhiran (freeze jamet) TIDAK ikut berubah
ketika musiknya diperbaiki. Dua hal itu pernah tercampur dalam satu nilai.
"""
import sys

sys.path.insert(0, "/home/ubuntu/clipper")
import bgm
import edit

# --- 1. aturannya memang ada, dan memang melarang pasangan ini -------------
assert bgm._clashes("emotional", "hype"), \
    "bgm._CLASH kehilangan pasangan emotional x hype"
assert bgm._clashes("hype", "emotional"), "arah pasangan tidak simetris"
assert not bgm._clashes("hype", "inspiring"), \
    "hype x inspiring harus TETAP boleh — keduanya memang berima"
print("aturan clash   : emotional x hype dilarang, hype x inspiring boleh")

# --- 2. track emotional memang tersedia di box ini -------------------------
# Kalau tidak ada, hasil yang benar adalah TIDAK ADA musik, bukan lagu hype.
tr, why = bgm.pick("emotional")
print("pick(emotional): %s" % ((tr or {}).get("file") or "tidak ada musik"))
if tr:
    assert "hype" not in (tr.get("mood") or []), \
        "pick('emotional') mengembalikan track hype: %s" % tr.get("file")

# --- 3. kontrol negatif: pasangan bentrok tidak pernah disubstitusikan -----
# Paksa keadaan "tidak ada track emotional" dan pastikan jawabannya bukan hype.
_real = bgm.load_tracks


def _only_hype(dirpath=None):
    return [t for t in _real(dirpath) if "hype" in (t["mood"] or [])]


bgm.load_tracks = _only_hype
try:
    tr2, why2 = bgm.pick("emotional")
    assert tr2 is None, (
        "hanya ada track hype, tapi pick('emotional') memilih %s — "
        "lebih baik sunyi daripada lagu yang bertentangan"
        % (tr2 or {}).get("file"))
    print("tanpa track emotional: tidak ada musik + alasan %r" % why2)
finally:
    bgm.load_tracks = _real

# --- 4. memperbaiki musik tidak boleh mengubah AKHIRAN ---------------------
# Preset jamet menyetel edit.OUTRO secara terpisah dari mood, jadi akhiran
# freeze harus tetap "jamet" walau musiknya jatuh ke emotional. Kalau keduanya
# dibaca dari satu nilai, perbaikan register akan diam-diam membuang freeze.
_prev = edit.OUTRO
try:
    edit.OUTRO = "jamet"
    assert edit._outro_kind("emotional") == "jamet", \
        "akhiran jamet hilang saat mood emotional — mood dan outro tercampur"
    assert edit._outro_kind("hype") == "jamet", "akhiran jamet tidak stabil"
    print("akhiran        : tetap jamet untuk mood emotional DAN hype")
finally:
    edit.OUTRO = _prev

# --- 5. jalur kode yang memperbaikinya benar-benar ada di job.py -----------
src = open("/home/ubuntu/clipper/job.py").read()
assert "mood_from_preset" in src, "penanda asal mood tidak ada di job.py"
assert src.count("mood_from_preset") >= 4, \
    "mood_from_preset harus disetel, diteruskan, dan dibaca"
i_set = src.index('a.mood = preset["mood"]')
i_flag = src.index("mood_from_preset = True")
assert i_flag > i_set, "penanda harus disetel saat preset mengisi mood"
assert "bgm._clashes(mood, meta[\"mood\"])" in src, \
    "job.py tidak memeriksa clash antara preset dan transkrip"
print("jalur kode     : preset ditandai, clash diperiksa sebelum bgm.pick")

print("\n_v62 ok — preset memberi default, transkrip memutuskan musik, "
      "akhiran tidak terpengaruh")
