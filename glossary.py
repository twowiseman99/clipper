"""A persistent name dictionary, so the same name is spelled the same way twice.

`language.py` fixes mishearings one clip at a time, starting from nothing on
every render. That leaves two gaps: a name corrected on Monday is misheard
again on Tuesday, and a name Whisper gets wrong the same way every time is
re-litigated by the model each run instead of just being known.

The schema follows `glossary.py` from the `translate-book` skill
(deusyu/translate-book), which solves the same problem one scale up — it keeps
a proper noun consistent across a hundred chapters translated by separate
agents. Taken from it: a versioned file, `source -> target` with a category,
a confidence level, and a frequency count, hand-editable on disk.

Dropped from it: CJK handling, prompt-hash bookkeeping, and the alias table.
Those serve a translation pipeline; this file only ever replaces an
ASR mishearing with the right spelling of the same spoken word.

Entries are earned, not guessed. A name only enters the dictionary after
`language.py` has corrected it with a real model call, so the file is a cache
of decisions already made rather than a list of hopes.
"""
import json
import os
import re
import sys
import tempfile

SCHEMA_VERSION = 1
PATH = os.environ.get(
    "CLIPPER_GLOSSARY",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "glossary.json"))

# A correction has to be seen this many times before it is applied blind.
# Once is a guess; twice is a pattern. Until then the entry is recorded but
# only the model decides.
MIN_SEEN = int(os.environ.get("CLIPPER_GLOSSARY_MIN_SEEN", "2"))
VALID_KINDS = ("person", "place", "org", "term", "word")


def _blank():
    return {"version": SCHEMA_VERSION, "terms": []}


def load(path=PATH):
    """The dictionary on disk, or an empty one. Never raises.

    A corrupt or hand-edited-to-broken file must not stop a render: captions
    with a mishearing beat no captions at all.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return _blank()
    except Exception as exc:
        print("glossary: unreadable (%s: %s) — starting empty"
              % (type(exc).__name__, exc), file=sys.stderr)
        return _blank()
    if not isinstance(data, dict) or not isinstance(data.get("terms"), list):
        print("glossary: unexpected shape — starting empty", file=sys.stderr)
        return _blank()
    if data.get("version") != SCHEMA_VERSION:
        print("glossary: version %r, expected %d — starting empty"
              % (data.get("version"), SCHEMA_VERSION), file=sys.stderr)
        return _blank()
    return data


def save(data, path=PATH):
    """Write atomically, so an interrupted render cannot truncate the file."""
    try:
        d = os.path.dirname(os.path.abspath(path)) or "."
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".glossary-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, path)
        return True
    except Exception as exc:
        print("glossary: could not save (%s: %s)"
              % (type(exc).__name__, exc), file=sys.stderr)
        return False


def _key(s):
    return re.sub(r"\W", "", str(s).lower())


def find(data, word):
    """The entry matching `word` ignoring case and punctuation, or None."""
    k = _key(word)
    if not k:
        return None
    for t in data.get("terms", ()):
        if _key(t.get("source")) == k:
            return t
    return None


def record(corrections, kind="word", path=PATH):
    """Note `[(was, now)]` corrections, bumping `seen` on repeats.

    Called after `language.py` has accepted a correction, so what lands here is
    a decision a model already made and the guards already passed.
    """
    pairs = [(str(a), str(b)) for a, b in (corrections or ()) if a and b]
    if not pairs:
        return 0
    data = load(path)
    added = 0
    for was, now in pairs:
        if _key(was) == _key(now):
            continue
        hit = find(data, was)
        if hit is None:
            data["terms"].append({
                "source": was, "target": now,
                "kind": kind if kind in VALID_KINDS else "word",
                "seen": 1, "confidence": "low",
            })
            added += 1
            continue
        if _key(hit.get("target")) != _key(now):
            # The model disagreed with itself about the same word. Leaving the
            # old target and not promoting is the safe reading: an entry two
            # runs disagree on is exactly the one not to apply blind.
            print("glossary: %r -> %r conflicts with stored %r — left alone"
                  % (was, now, hit.get("target")), file=sys.stderr)
            hit["confidence"] = "low"
            continue
        hit["seen"] = int(hit.get("seen") or 1) + 1
        hit["confidence"] = "high" if hit["seen"] >= MIN_SEEN else "low"
    save(data, path)
    return added


def apply(words, path=PATH):
    """Apply confident entries to `words` in place. Returns (words, n_applied).

    Only `seen >= MIN_SEEN` entries are used. Timings are never touched: this
    replaces the text of a single word with the text of the same single word,
    which is the one operation the caption renderer can absorb safely.
    """
    items = list(words or ())
    if not items:
        return items, 0
    data = load(path)
    table = {}
    for t in data.get("terms", ()):
        if int(t.get("seen") or 0) < MIN_SEEN:
            continue
        src, dst = t.get("source"), t.get("target")
        if src and dst:
            table[_key(src)] = str(dst)
    if not table:
        return items, 0

    out = []
    hits = []
    for w in items:
        word = str(w.get("word", ""))
        fixed = table.get(_key(word))
        if fixed and fixed != word:
            w = dict(w)
            w["word"] = fixed
            hits.append((word, fixed))
        out.append(w)
    if hits:
        print("glossary: %d applied — %s"
              % (len(hits), ", ".join("%s->%s" % p for p in hits[:10])),
              file=sys.stderr)
    return out, len(hits)


if __name__ == "__main__":
    import shutil

    tmpd = tempfile.mkdtemp(prefix="gloss-")
    p = os.path.join(tmpd, "g.json")
    try:
        assert load(p) == _blank()
        assert apply([{"word": "sudara", "start": 0.0, "end": 0.3}], p)[1] == 0

        # First sighting: recorded, but not trusted enough to apply.
        assert record([("sudara", "saudara")], "word", p) == 1
        words = [{"word": "sudara", "start": 0.0, "end": 0.3}]
        got, n = apply(words, p)
        assert n == 0 and got[0]["word"] == "sudara", got

        # Second sighting promotes it, and now it applies without a model call.
        record([("sudara", "saudara")], "word", p)
        got, n = apply(words, p)
        assert n == 1 and got[0]["word"] == "saudara", got
        assert got[0]["start"] == 0.0 and got[0]["end"] == 0.3

        # Input must not be mutated — the caller may still need the original.
        assert words[0]["word"] == "sudara"

        # Punctuation and case are not corrections.
        assert record([("Gontor", "gontor.")], "place", p) == 0

        # A disagreement demotes rather than overwrites.
        record([("sudara", "sudora")], "word", p)
        entry = find(load(p), "sudara")
        assert entry["target"] == "saudara", entry
        assert entry["confidence"] == "low", entry

        # A corrupt file falls back to empty instead of raising.
        with open(p, "w") as f:
            f.write("{ not json")
        assert load(p) == _blank()
        assert apply([{"word": "x", "start": 0, "end": 1}], p)[1] == 0

        print("glossary.py self-check OK")
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
