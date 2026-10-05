"""Have a language reviewer correct ASR mishearings before captions are drawn.

Whisper's Indonesian acoustic model rewrites words it does not know into words
it does: `seolah` becomes `sololah`, `saudara` becomes `sudara`. The audio is
unambiguous to a human — the error is lexical, not acoustic, so no amount of
decoder tuning fixes all of it. A reviewer who knows the language catches what
the model cannot.

The guard rails come from the `translation-quality` skill's anti-fabrication
checklist (senshinji/claude-translation-skill), which names the failure mode
exactly: a model asked to improve text will add content that was never in the
source. Its rules transfer to this job directly —

  - maintain 1:1 correspondence, never merge or split
  - never substitute a generic word for specific content
  - never guess at a proper noun

Enforced here rather than requested in the prompt, because a prompt is a
request and this needs to be a guarantee. Captions are drawn from per-word
start/end times, so corrections apply **in place, one word for one word**. A
reviewer that merges, splits, reorders, or adds words is rejected outright
rather than partially trusted: a silently shifted timeline desynchronises every
caption after it.
"""
import difflib
import json
import os
import re
import sys

import agents
import ai
import glossary

# Hard ceiling on how much of a transcript may change. A reviewer rewriting
# half the words is not correcting mishearings, it is paraphrasing, and the
# captions would stop matching what the viewer hears.
MAX_CHANGE_SHARE = float(os.environ.get("CLIPPER_LANG_MAX_SHARE", "0.25"))
# The share guard only means anything over a real transcript. On a handful of
# words any single fix is a large fraction, so below this count the guard is
# skipped and the per-word edit-distance check carries the weight.
MIN_WORDS_FOR_SHARE = int(os.environ.get("CLIPPER_LANG_MIN_WORDS", "20"))
# Words whose corrections are allowed to differ in length from the original.
# Beyond this the "correction" is a different word, not a spelling fix.
MAX_EDIT_RATIO = float(os.environ.get("CLIPPER_LANG_MAX_EDIT", "0.6"))

SYSTEM = (
    "Anda editor bahasa Indonesia yang memeriksa hasil speech-to-text. "
    "Tugas Anda HANYA memperbaiki kata yang salah dengar oleh mesin."
)

INSTRUCTIONS = """Di bawah ini hasil transkrip otomatis sebuah video berbahasa Indonesia.
Mesin sering salah dengar kata yang tidak dikenalnya, misalnya:
- "sololah" seharusnya "seolah"
- "sudara" seharusnya "saudara"
- nama orang, tempat, dan istilah agama sering ditulis salah

ATURAN KETAT:
1. Jumlah kata HARUS sama persis. Jangan menambah, menghapus, atau menggabungkan kata.
2. Jangan mengubah urutan kata.
3. Perbaiki HANYA kata yang jelas salah dengar. Kata yang sudah benar biarkan apa adanya.
4. Jangan membakukan bahasa percakapan. "gua", "lu", "nggak", "udah" biarkan.
5. Jangan menambah atau menghapus tanda baca.

Balas JSON: {"words": ["kata1", "kata2", ...]}
Panjang array HARUS %d, sama dengan jumlah kata di bawah.

Konteks video: %s

Transkrip (%d kata):
%s"""


def _edit_ratio(a, b):
    """0.0 identical, 1.0 completely different."""
    return 1.0 - difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def review(words, context="", learn=True, status=None, **kwargs):
    """Return `words` with mishearings corrected, timings untouched.

    Runs the dictionary first: names already corrected twice are applied
    without a model call, so a recurring mishearing stops being re-litigated
    every render. Whatever the reviewer then fixes is recorded, which is how
    entries get there in the first place.

    Returns the input unchanged on any failure or any sign the reviewer did not
    follow the one-for-one rule. Captions with a known mishearing are a
    cosmetic problem; captions desynchronised from the audio are a broken clip,
    so every ambiguous case resolves to "leave it alone".

    Pass a dict as `status` to find out WHICH of those happened. Failing soft is
    correct — one unreachable model should not cost a whole render — but failing
    soft and silently is not: a clip shipped with "sololah" in the captions and
    the only trace was a stderr line nobody read. The caller fills in
    status["ok"] and status["reason"] and can surface it beside the result.
    """
    def _done(ok, reason=""):
        if status is not None:
            status["ok"] = ok
            status["reason"] = reason
        return None

    items = list(words or ())
    if not items:
        _done(True, "no words")
        return items

    items, _n = glossary.apply(items)
    original = [str(w.get("word", "")) for w in items]
    prompt = INSTRUCTIONS % (len(original), context or "(tidak diberikan)",
                             len(original), " ".join(original))

    try:
        # Low temperature: this is a correction task with one right answer, not
        # a writing task. Positional (system, user) to match ai.chat_json.
        # The language gate's reviewer is
        # specialized/indonesian-transcript-linguist.md — written for this
        # job because the repo's language-translator is Spanish/English.
        # Its identity and rules lead; SYSTEM stays last and binding so
        # the word-for-word JSON contract and the no-retiming rule cannot
        # be talked out of by a persona.
        out = ai.chat_json(agents.system_for("language", SYSTEM), prompt,
                           temperature=0.1, **kwargs) or {}
    except Exception as exc:
        print("language: review unavailable (%s: %s)"
              % (type(exc).__name__, exc), file=sys.stderr)
        _done(False, "model unreachable (%s)" % type(exc).__name__)
        return items

    fixed = out.get("words")
    if not isinstance(fixed, list):
        print("language: reviewer returned no word list", file=sys.stderr)
        _done(False, "reviewer returned no word list")
        return items
    if len(fixed) != len(original):
        # The one guarantee the whole design rests on. A different length means
        # words were merged or split, and every later timing would be wrong.
        print("language: length mismatch (%d in, %d back) — transcript kept"
              % (len(original), len(fixed)), file=sys.stderr)
        _done(False, "length mismatch (%d in, %d back)"
              % (len(original), len(fixed)))
        return items

    changes = []
    for i, (was, now) in enumerate(zip(original, fixed)):
        if not isinstance(now, str):
            continue
        now = now.strip()
        if not now or now == was:
            continue
        # Punctuation is the renderer's business, not the reviewer's.
        if re.sub(r"\W", "", now.lower()) == re.sub(r"\W", "", was.lower()):
            continue
        if _edit_ratio(was, now) > MAX_EDIT_RATIO:
            print("language: rejected %r -> %r (too different)" % (was, now),
                  file=sys.stderr)
            continue
        changes.append((i, was, now))

    share = len(changes) / max(1, len(original))
    if len(original) >= MIN_WORDS_FOR_SHARE and share > MAX_CHANGE_SHARE:
        print("language: %d/%d words rewritten (%.0f%%) — looks like a "
              "paraphrase, transcript kept"
              % (len(changes), len(original), share * 100), file=sys.stderr)
        _done(False, "%d/%d words rewritten (%.0f%%) — looks like a paraphrase"
              % (len(changes), len(original), share * 100))
        return items

    if not changes:
        print("language: no mishearings found", file=sys.stderr)
        _done(True, "no mishearings found")
        return items

    out_items = [dict(w) for w in items]
    for i, _was, now in changes:
        out_items[i]["word"] = now
    print("language: %d fixed — %s"
          % (len(changes),
             ", ".join("%s->%s" % (w, n) for _i, w, n in changes[:12])),
          file=sys.stderr)
    if learn:
        # Record only what survived every guard. The dictionary is a cache of
        # accepted decisions, so a correction that was rejected above must not
        # reach it through the back door.
        glossary.record([(was, now) for _i, was, now in changes])
    _done(True, "%d fixed" % len(changes))
    return out_items


if __name__ == "__main__":
    # Offline check: the guards, with a stubbed reviewer. No model needed.
    # glossary is stubbed both ways so a self-check neither reads nor writes
    # the real dictionary on this box.
    import functools

    real = ai.chat_json
    real_apply, real_record = glossary.apply, glossary.record
    glossary.apply = lambda words, *a, **k: (list(words), 0)
    glossary.record = lambda *a, **k: 0
    review = functools.partial(review, learn=False)
    try:
        base = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.3}
                for i, w in enumerate("tadi saya inget sudara kita".split())]

        ai.chat_json = lambda *a, **k: {
            "words": ["tadi", "saya", "ingat", "saudara", "kita"]}
        got = review(base)
        assert [w["word"] for w in got] == [
            "tadi", "saya", "ingat", "saudara", "kita"], got
        # timings must be byte-identical to the input
        assert [w["start"] for w in got] == [w["start"] for w in base]

        # too few words back -> keep the original
        ai.chat_json = lambda *a, **k: {"words": ["tadi", "saya"]}
        assert [w["word"] for w in review(base)] == [
            "tadi", "saya", "inget", "sudara", "kita"]

        # The share guard: many small plausible edits are still a rewrite.
        # Each one passes the per-word distance check, so only the share guard
        # can catch this shape — which is why both guards exist.
        long_src = ("tadi saya inget sudara kita di Palestina mereka dibantai "
                    "mereka dibom mereka diserang terus menerus dan kita "
                    "sololah kurang berdaya untuk membantu mereka semua")
        long_base = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.3}
                     for i, w in enumerate(long_src.split())]
        creep = long_src.split()
        for i in range(0, 16, 2):          # 8 of 24 words = 33% > 25%
            creep[i] = creep[i] + "nya"
        ai.chat_json = lambda *a, **k: {"words": creep}
        kept = [w["word"] for w in review(long_base)]
        assert kept == long_src.split(), kept

        # but a couple of genuine fixes in the same transcript go through
        fixes = long_src.split()
        fixes[3], fixes[17] = "saudara", "seolah"
        ai.chat_json = lambda *a, **k: {"words": fixes}
        got2 = review(long_base)
        names = [w["word"] for w in got2]
        assert names[3] == "saudara" and names[17] == "seolah", names
        assert len(got2) == len(long_base)
        assert [w["start"] for w in got2] == [w["start"] for w in long_base]

        # a single word replaced by something unrelated is rejected
        ai.chat_json = lambda *a, **k: {
            "words": ["tadi", "saya", "inget", "Palestina", "kita"]}
        assert [w["word"] for w in review(base)][3] == "sudara"

        # malformed replies fall back instead of raising
        ai.chat_json = lambda *a, **k: {"words": "bukan list"}
        assert len(review(base)) == 5
        ai.chat_json = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x"))
        assert len(review(base)) == 5

        print("language.py self-check OK")
    finally:
        ai.chat_json = real
        glossary.apply, glossary.record = real_apply, real_record
