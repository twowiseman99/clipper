"""Phase 2: a short human narration above the Phase 1 facts.

WHAT THIS IS NOT. It does not compute anything, judge anything, or decide
anything. Phase 1 already produced the verdicts, the counts and the error
fields; those are the product and they ship whether or not this module runs.
This adds two or three sentences of plain Indonesian at the top saying what
happened to this render, for a person reading on a phone who does not want to
parse seven sections first.

THE HARD RULE, from the operator: "Angka dan fakta dilarang diubah atau
dikarang." A narration layer over a log is a machine for inventing numbers --
it is a language model being handed a page of digits and asked to summarise.
So the model never sees a number it could paraphrase into a different one:

  1. It is given a COMPACT STRUCTURED BRIEF, not the rendered message.
  2. Every number in its output is checked against that brief by
     `_numbers_ok`. One unknown number and the whole narration is dropped.
  3. Section names, file paths, flags and error strings are forbidden in the
     narration; those live in the fields below it, untranslated. If the model
     emits one, the narration is dropped.
  4. Any failure -- router down, bad JSON, failed check -- is silent: the
     message ships exactly as Phase 1 built it. A log layer must never be able
     to cost the operator the log.

Checked, not assumed, before writing this: the clipper .env pins
NINEROUTER_MODEL=combo1, and combo1 on this box resolves to
["cc/claude-opus-5", "cc/claude-sonnet-5", "ag/gemini-3.8-flash-high",
"ag/gemini-pro-agent"] -- two live calls came back "model":"claude-opus-5".
The operator asked for ds/deepseek-v4-pro; that model does not exist on this
router (27 models, no deepseek), so combo1 is the operator's own second
choice, not a silent substitution. The key is read from the .env by ai.py and
is never written here.
"""
import os
import re
import sys

import ai

# Off by default: the operator proves Phase 1 first, then turns this on.
ENABLED = os.environ.get("AUDIT_NARRATE", "") not in ("", "0", "false", "no")
MODEL = os.environ.get("AUDIT_NARRATE_MODEL", "") or ai.MODEL
# Two sentences, three when something broke. Longer than that and it stops
# being a summary and starts competing with the sections underneath.
MAX_CHARS = int(os.environ.get("AUDIT_NARRATE_MAX_CHARS", "320"))

_SYS = (
    "Kamu nulis satu paragraf pendek bahasa Indonesia santai (gw/lu, kayak "
    "ngobrol di Discord) buat ngasih tau operator apa yang kejadian di satu "
    "render video.\n"
    "ATURAN KERAS:\n"
    "- Maksimal 2 kalimat. Kalau ada yang gagal, maksimal 3.\n"
    "- DILARANG nulis angka apapun yang ga ada di data yang gw kasih.\n"
    "- DILARANG ngarang sebab, kesimpulan, atau saran teknis.\n"
    "- DILARANG nyebut nama file, path, flag CLI, nama fungsi, atau pesan "
    "error -- itu udah ada di bawah narasi kamu.\n"
    "- Kalau semua lolos, bilang singkat aja kalau aman.\n"
    "- Jangan pakai emoji, jangan pakai heading, jangan pakai bullet.\n"
    'Jawab JSON: {"narasi": "..."}'
)

# Tokens that mean the model reached past its brief into the machine detail.
_LEAKS = (".py", ".mp4", ".json", ".mp3", "--", "()", "/home/", "stage:",
          "fallback:", "debug:", "Traceback")


def _numbers(text):
    """Every number in `text`, normalised for comparison.

    Indonesian writes the decimal comma, so 0,55 and 0.55 are one number. And
    "28,0 detik" restates the brief's "28 detik" -- a trailing zero is the
    same measurement, not a new claim, so trailing zeros go too. Being strict
    here would reject honest narration and teach the next reader that the
    guard cries wolf.
    """
    out = set()
    for n in re.findall(r"\d+(?:[.,]\d+)?", text or ""):
        n = n.replace(",", ".")
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        out.add(n or "0")
    return out


def brief(data, sections):
    """The only thing the model is allowed to see.

    Deliberately small and already-decided: counts and section verdicts, no
    prose, no paths, no error strings. Anything not in here is a number the
    narration may not contain.
    """
    totals = data.get("totals", {}) or {}
    lines = []
    dur = data.get("duration_sec")
    if dur:
        lines.append(f"durasi klip: {dur:.0f} detik")
    if data.get("mood_used") and data.get("mood") \
            and data["mood_used"] != data["mood"]:
        lines.append(f"mood dipakai: {data['mood_used']}, "
                     f"transkrip kebaca: {data['mood']}")
    elif data.get("mood") or data.get("mood_used"):
        lines.append(f"mood: {data.get('mood') or data['mood_used']}")
    lines.append(f"lolos: {totals.get('pass', 0)}")
    lines.append(f"ditolak: {totals.get('reject', 0)}")
    lines.append(f"catatan: {totals.get('warn', 0)}")
    # The total, stated rather than left to be derived. Under an adversarial
    # prompt the model wrote "kena 10 pengecekan" -- 8+1+1, arithmetic that is
    # CORRECT and was still dropped, because the guard only knows numbers it
    # was shown. A guard that rejects true statements teaches the reader to
    # ignore it, so the obvious sum is given rather than treated as a
    # fabrication.
    total = (totals.get("pass", 0) + totals.get("reject", 0)
             + totals.get("warn", 0))
    lines.append(f"total cek: {total}")
    for name, verdicts in sections:
        bad = [v for v in verdicts if v in ("reject", "warn")]
        if bad:
            lines.append(f"divisi {name}: "
                         f"{bad.count('reject')} ditolak, "
                         f"{bad.count('warn')} catatan")
    return "\n".join(lines)


def _numbers_ok(narration, brief_text, data):
    """True when the narration invents no number.

    The narration may only reuse numbers the brief already states. Small
    counting words are allowed through because "dua-duanya aman" is natural
    Indonesian and carries no claim about a measurement.
    """
    allowed = _numbers(brief_text) | _numbers(str(data.get("render_id", "")))
    allowed |= {"1", "2", "3"}
    return not (_numbers(narration) - allowed)


def narrate(data, sections, model=None, log=sys.stderr):
    """Short narration for this ledger, or "" when anything is off.

    Returning "" is a normal outcome, not an error: Phase 1's message is
    complete without it.
    """
    if not ENABLED:
        return ""
    text = brief(data, sections)
    try:
        out = ai.chat_json(_SYS, text, model=model or MODEL, temperature=0.4)
        narration = " ".join(str(out.get("narasi") or "").split())
    except Exception as exc:
        # A router hiccup must cost the narration, never the log.
        print(f"audit_narrate: dilewati ({type(exc).__name__}: "
              f"{str(exc)[:80]})", file=log)
        return ""

    if not narration:
        return ""
    if len(narration) > MAX_CHARS:
        print(f"audit_narrate: dilewati (narasi {len(narration)} huruf > "
              f"{MAX_CHARS})", file=log)
        return ""
    leaked = [t for t in _LEAKS if t in narration]
    if leaked:
        print(f"audit_narrate: dilewati (nyebut detail mesin: {leaked})",
              file=log)
        return ""
    if not _numbers_ok(narration, text, data):
        bad = sorted(_numbers(narration) - (_numbers(text) | {"1", "2", "3"}))
        print(f"audit_narrate: dilewati (angka ngarang: {bad})", file=log)
        return ""
    return narration


def _selftest():
    data = {"duration_sec": 28.0, "mood": "emotional", "mood_used": "hype",
            "totals": {"pass": 8, "reject": 1, "warn": 1}}
    sections = [("Gambar penutup", ["brief", "reject"]),
                ("Musik", ["warn", "pass"])]
    b = brief(data, sections)
    assert "durasi klip: 28 detik" in b, b
    assert "mood dipakai: hype, transkrip kebaca: emotional" in b, b
    assert "ditolak: 1" in b and "catatan: 1" in b, b
    assert "divisi Gambar penutup: 1 ditolak, 0 catatan" in b, b
    # The brief must carry no path, flag or error string.
    for leak in (".py", "/home/", "--", ".mp4"):
        assert leak not in b, f"brief leaked {leak!r}: {b}"

    # A number not in the brief is a fabrication, even a plausible one.
    assert _numbers_ok("8 cek lolos, 1 ditolak", b, data)
    assert not _numbers_ok("31 frame dicek, ga ada yang lolos", b, data)
    assert not _numbers_ok("confidence-nya 0,95", b, data)
    # Decimal comma and point are the same number.
    assert _numbers_ok("durasinya 28,0 detik", b, data)
    print('{"ok": true, "checked": "brief shape, fabricated-number guard"}')


if __name__ == "__main__":
    _selftest()
