# Gate kamus koreksi otomatis: kata umum bahasa Indonesia TIDAK boleh diganti
# secara buta oleh glossary.apply() maupun disimpan oleh glossary.record(),
# kecuali entri bernama (kind person/place/org). Kata bukan umum (salah dengar
# ASR seperti Gipran->Gibran, MPG.->MBG., kerajunan->keracunan) WAJIB tetap
# diganti.
import io
import contextlib
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import glossary

fails = []
tmpd = tempfile.mkdtemp(prefix="v98-gloss-")

try:
    # 1. Cek is_common() dua arah terhadap lexicon 20k
    umum = ["ikut", "kamu", "kota", "titik", "kotak", "suruh", "darah,", "Saya", "memuji", "pi"]
    bukan_umum = ["Gipran", "Giberan", "MPG.", "kerajunan", "sololah", "jawat"]
    for w in umum:
        if not glossary.is_common(w):
            fails.append(f"is_common({w!r}) False, harusnya True")
    for w in bukan_umum:
        if glossary.is_common(w):
            fails.append(f"is_common({w!r}) True, harusnya False")

    # 2. Cek record(): tolak kata umum (kind=word), terima bukan umum & kind=person
    g_rec = os.path.join(tmpd, "rec.json")
    n_umum = glossary.record([("ikut", "ibu"), ("kamu", "kami"), ("kota", "kotak")], kind="word", path=g_rec)
    if n_umum != 0:
        fails.append(f"record kata umum mengembalikan {n_umum}, harusnya 0")
    data_rec = glossary.load(g_rec)
    if data_rec.get("terms"):
        fails.append(f"record menyimpan kata umum: {data_rec.get('terms')}")

    n_bukan = glossary.record([("Gipran", "Gibran"), ("MPG.", "MBG."), ("kerajunan", "keracunan")], kind="word", path=g_rec)
    if n_bukan != 3:
        fails.append(f"record kata bukan umum mengembalikan {n_bukan}, harusnya 3")
    for w in ("Gipran", "MPG.", "kerajunan"):
        if glossary.find(glossary.load(g_rec), w) is None:
            fails.append(f"record gagal menyimpan {w!r}")

    n_person = glossary.record([("Saya", "Syekh")], kind="person", path=g_rec)
    if n_person != 1 or glossary.find(glossary.load(g_rec), "Saya") is None:
        fails.append("record gagal menyimpan kind=person walaupun source kata umum")

    # 3. Cek apply() dua arah + kind=person + timing & jumlah kata utuh
    g_app = os.path.join(tmpd, "app.json")
    glossary.save({
        "version": glossary.SCHEMA_VERSION,
        "terms": [
            {"source": "ikut", "target": "ibu", "kind": "word", "seen": 2, "confidence": "high"},
            {"source": "kamu", "target": "kami", "kind": "word", "seen": 2, "confidence": "high"},
            {"source": "kota", "target": "kotak", "kind": "word", "seen": 2, "confidence": "high"},
            {"source": "Gipran", "target": "Gibran", "kind": "word", "seen": 2, "confidence": "high"},
            {"source": "MPG.", "target": "MBG.", "kind": "word", "seen": 2, "confidence": "high"},
            {"source": "kerajunan", "target": "keracunan", "kind": "word", "seen": 2, "confidence": "high"},
            {"source": "Saya", "target": "Syekh", "kind": "person", "seen": 2, "confidence": "high"},
        ],
    }, g_app)

    words = [
        {"word": "ikut", "start": 0.0, "end": 0.3},
        {"word": "kamu", "start": 0.4, "end": 0.7},
        {"word": "kota", "start": 0.8, "end": 1.1},
        {"word": "Gipran", "start": 1.2, "end": 1.6},
        {"word": "MPG.", "start": 1.7, "end": 2.0},
        {"word": "kerajunan", "start": 2.1, "end": 2.6},
        {"word": "Saya", "start": 2.7, "end": 3.0},
    ]
    err_buf = io.StringIO()
    with contextlib.redirect_stderr(err_buf):
        out, n_applied = glossary.apply(words, g_app)
    err_log = err_buf.getvalue()

    want_words = ["ikut", "kamu", "kota", "Gibran", "MBG.", "keracunan", "Syekh"]
    got_words = [w["word"] for w in out]
    if got_words != want_words:
        fails.append(f"apply dua arah: dapat {got_words}, harusnya {want_words}")
    if n_applied != 4:
        fails.append(f"n_applied={n_applied}, harusnya 4")
    if len(out) != len(words):
        fails.append(f"jumlah kata berubah: {len(out)} != {len(words)}")
    if [(w["start"], w["end"]) for w in out] != [(w["start"], w["end"]) for w in words]:
        fails.append("timing start/end berubah")
    if [w["word"] for w in words] != ["ikut", "kamu", "kota", "Gipran", "MPG.", "kerajunan", "Saya"]:
        fails.append("input words dimutasi")
    if "glossary: 3 dilewati (kata umum) — ikut->ibu, kamu->kami, kota->kotak" not in err_log:
        fails.append(f"log dilewati tidak sesuai: {err_log!r}")

    # 4. File lexicon tidak ada -> tidak crash, ada 1 peringatan, perilaku lama (semua seen>=2 dipakai)
    missing_lex = os.path.join(tmpd, "tidak_ada_lexicon.txt")
    old_env = os.environ.get("CLIPPER_LEXICON")
    try:
        os.environ["CLIPPER_LEXICON"] = missing_lex
        warn_buf = io.StringIO()
        with contextlib.redirect_stderr(warn_buf):
            c1 = glossary.is_common("ikut")
            c2 = glossary.is_common("kamu")
            out_no_lex, n_no_lex = glossary.apply(words, g_app)
        warn_log = warn_buf.getvalue()
        if c1 or c2:
            fails.append("is_common harus False saat file lexicon tidak ada")
        if [w["word"] for w in out_no_lex] != ["ibu", "kami", "kotak", "Gibran", "MBG.", "keracunan", "Syekh"]:
            fails.append(f"fallback tanpa lexicon salah: {[w['word'] for w in out_no_lex]}")
        if n_no_lex != 7:
            fails.append(f"n_no_lex={n_no_lex}, harusnya 7")
        warn_lines = [l for l in warn_log.splitlines() if "lexicon" in l.lower()]
        if len(warn_lines) != 1:
            fails.append(f"peringatan lexicon harus tepat sekali, dapat {len(warn_lines)}: {warn_lines}")
    finally:
        if old_env is None:
            os.environ.pop("CLIPPER_LEXICON", None)
        else:
            os.environ["CLIPPER_LEXICON"] = old_env
finally:
    shutil.rmtree(tmpd, ignore_errors=True)

if fails:
    print("_v98 FAIL:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("_v98 ok: kata umum dilewati + kata bukan umum & person tetap diganti + record menolak kata umum + timing utuh + fallback lexicon aman")
