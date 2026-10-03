"""Zero cutaways must never ship silently, and one bad source must not cost
the cutaway.

v22 delivered a clip with no b-roll at all and `warnings: []`. Both halves of
that are bugs:

1. _gather_inserts only ever opened hits[0]. The frame gate can now reject a
   whole source ("no window shows the subject"), so when the top hit was
   aftermath footage the cutaway was lost even though hits[1] and hits[2] were
   never looked at.
2. Nothing told anyone. The result JSON said warnings: [] while the clip had
   silently lost every cutaway it was supposed to have.

Measured before the fix, from the v22 log: both terms found credible sources,
every finalist in each was rejected, and the delivered clip measured 2.14 and
3.78 motion in the b-roll band — the speaker, not footage.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import job

# --- a rejected source falls through to the next hit --------------------
HITS = [{"id": "aaa", "url": "u1", "title": "first"},
        {"id": "bbb", "url": "u2", "title": "second"},
        {"id": "ccc", "url": "u3", "title": "third"}]

opened = []


class FakeBrollPlace:
    """prepare() refuses everything except source ccc."""
    HOLD = 3.5
    MIN_GAP = 9.0
    MAX_INSERTS = 5

    @staticmethod
    def phrase_windows(words, clip_start, dur, terms_fn=None):
        return [(11.0, 14.0, "mereka dibom.")]

    @staticmethod
    def prepare(src, out_path, **kw):
        opened.append(os.path.basename(os.path.dirname(src)))
        return "ccc" in src


class FakeBroll:
    @staticmethod
    def action_terms(phrase):
        return ["dibom serangan"]

    @staticmethod
    def action_look(term):
        return "an explosion"

    @staticmethod
    def insert_terms(*a, **k):
        return ["Palestina", "dibom"]

    @staticmethod
    def repeated_names(*a, **k):
        return ["Palestina"]

    @staticmethod
    def anchor_names(*a, **k):
        return {"palestina": "Palestina"}

    @staticmethod
    def proper_nouns(text):
        return ["Palestina"] if "Palestina" in str(text) else []

    @staticmethod
    def anchor_terms(*a, **k):
        return {}

    @staticmethod
    def search(*a, **k):
        return list(HITS)

    @staticmethod
    def vetted(hits, terms, limit=1, **kw):
        # Mirrors the real signature: a caller that forgets to raise `limit`
        # must see a one-item shortlist here too, or this test would pass
        # while production still only tried the top hit.
        return list(hits)[:limit]


class FakeFetch:
    @staticmethod
    def fetch(kind, url, name):
        return [os.path.join("/tmp/media", name, "v.mp4")]


def install(monkey):
    """_gather_inserts imports its deps inside the function, so patch
    sys.modules rather than attributes."""
    saved = {k: sys.modules.get(k) for k in monkey}
    sys.modules.update(monkey)
    return saved


import edit  # noqa: E402  real module, only CANVAS_* are read

monkey = {"broll": FakeBroll, "broll_place": FakeBrollPlace,
          "fetch": FakeFetch, "edit": edit}
saved = install(monkey)
try:
    words = [{"word": "mereka", "start": 11.0, "end": 11.4},
             {"word": "dibom.", "start": 11.4, "end": 12.0}]
    notes = []
    got = job._gather_inserts(words, 0.0, 82.0, "Palestina di Gaza",
                              "/tmp/src.mp4", warnings=notes)
    assert len(got) == 1, f"the third source should have been used: {got}"
    assert opened == ["broll-aaa", "broll-bbb", "broll-ccc"], opened
    assert got[0]["title"] == "third", got[0]
    assert notes == [], f"a successful cutaway must not warn: {notes}"

    # --- and when every source fails, it has to say so ------------------
    opened.clear()

    def refuse(src, out_path, **kw):
        opened.append(src)
        return False

    FakeBrollPlace.prepare = staticmethod(refuse)
    notes = []
    got = job._gather_inserts(words, 0.0, 82.0, "Palestina di Gaza",
                              "/tmp/src.mp4", warnings=notes)
    assert got == [], got
    assert len(notes) == 1, f"a dropped cutaway must warn exactly once: {notes}"
    assert "dibom" in notes[0] and "sources checked" in notes[0], notes[0]
    assert len(opened) == job.BROLL_SOURCE_TRIES, \
        f"expected {job.BROLL_SOURCE_TRIES} attempts, got {len(opened)}"
finally:
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v

# --- the tries count must be worth having ------------------------------
assert job.BROLL_SOURCE_TRIES >= 2, \
    "trying a single source is the bug this test exists for"

print(f"_v23.py OK — a rejected source falls through to the next hit "
      f"(3 opened, third used); when all {job.BROLL_SOURCE_TRIES} fail the "
      f"drop is reported in warnings instead of shipping silently")
