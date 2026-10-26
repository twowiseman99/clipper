"""Ejaan caption yang DITETAPKAN operator — bukan koreksi salah dengar.

language.review cuma benerin kata yang SALAH DENGAR. Kata yang memang diucapkan
begitu tapi operator mau ditulis lain bukan urusannya, dan dia bener lolosin:
render Gibran 26 Okt lapor "language: no mishearings found" sementara caption
nulis "Buk" dua kali. Operator: "Kenapa buk sih? Harusnya BU ajaa".

Jadi aturan ejaan dijaga di KODE, bukan diminta di prompt (prompt = permintaan,
ini harus jaminan). Satu kata diganti satu kata, timing ga disentuh, tanda baca
nempel di belakang dipertahankan ("Buk." -> "Bu.").
"""
import re

# kata lisan -> ejaan caption. Kunci huruf kecil tanpa tanda baca.
SAPAAN = {
    "buk": "bu",     # operator 26 Okt: "Harusnya BU ajaa"
}

_TOKEN = re.compile(r"^([^\w]*)([\w]+)([^\w]*)$", re.UNICODE)


def _match_case(src, dst):
    if src.isupper() and len(src) > 1:
        return dst.upper()
    if src[:1].isupper():
        return dst[:1].upper() + dst[1:]
    return dst


def fix_word(text):
    m = _TOKEN.match(text or "")
    if not m:
        return text
    pre, core, post = m.groups()
    dst = SAPAAN.get(core.lower())
    if not dst:
        return text
    return pre + _match_case(core, dst) + post


def apply(words):
    """List kata baru (dict disalin) + daftar (lama, baru) yang diganti.

    Whisper mecah kata ulang jadi dua token: "anak" + "-anak", jadi caption
    nulis "anak -anak" (reviewer 26 Okt). Token yang MULAI dengan "-" disambung
    ke kata sebelumnya: start kata pertama, end kata kedua, jadi timing tetap
    nutup rentang yang sama, cuma jadi satu kata.
    """
    out, hits = [], []
    for w in words or ():
        old = str(w.get("word", ""))
        if old.startswith("-") and len(old) > 1 and out:
            prev = dict(out[-1])
            before = prev["word"]
            prev["word"] = before.rstrip() + old
            if "end" in w:
                prev["end"] = w["end"]
            out[-1] = prev
            hits.append((f"{before} {old}", prev["word"]))
            continue
        new = fix_word(old)
        if new != old:
            w = dict(w)
            w["word"] = new
            hits.append((old, new))
        out.append(w)
    return out, hits
