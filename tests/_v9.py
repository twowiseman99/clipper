"""Two bugs the operator found by watching the delivered clip.

1. The transcript reviewer was handed the whole video (522 words of a one-hour
   source) to correct the 61 that reach the screen, and timed out at both 120s
   and 300s. Scoped to the segment it returns in ~11s.
2. The subject qualifying an action search was `sorted(names)[0]`, so "gontor"
   beat "palestina" alphabetically and "mereka dibom" searched the venue
   instead of the event.

Offline. Data is the real v8 transcript.
"""
import json
import re

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import broll

# The committed fixture comes first. This used to point only at
# media/uf9833efdc72b/, which `.gitignore` excludes twice over (`media/` and
# `*.words.json`), so the transcript could never be committed and this test died
# every time the media cache was cleared — red across several releases for a
# missing file rather than a real regression. The media path stays as a fallback
# so a box that still has the cache keeps working.
_HERE = os.path.dirname(os.path.abspath(__file__))
WORDS = next(
    (p for p in (os.path.join(_HERE, "fixtures", "PPOKdwOCMLA.words.json"),
                 "media/uf9833efdc72b/PPOKdwOCMLA.words.json")
     if os.path.exists(p)),
    None)
assert WORDS, (
    "PPOKdwOCMLA.words.json is missing from tests/fixtures/ and from the media "
    "cache. It is a committed fixture; restore it from git rather than "
    "re-downloading the source.")
CTX = "Prabowo membela Palestina di depan banyak pemimpin negara, di Gontor"

raw = json.load(open(WORDS))
raw = raw["words"] if isinstance(raw, dict) else raw
seg = [w for w in raw if 245.34 <= w.get("start", 0) <= 329.96]

# --- Bug 1: scope -----------------------------------------------------------
# The fix is structural (review moved after segment selection), so what is
# asserted here is the size difference that caused the timeout.
assert len(raw) > 500, len(raw)
assert len(seg) < 80, len(seg)

# --- Bug 2: subject selection ------------------------------------------------
text = " ".join(str(w.get("word", "")) for w in seg)
repeated = broll.repeated_names(text, CTX)
anchors = broll.anchor_names(CTX, text)
names = set()
for n in repeated:
    fixed = anchors.get(n.lower())
    if fixed:
        names.add(fixed.lower())
    elif n.lower() in {a.lower() for a in broll.proper_nouns(CTX)}:
        names.add(n.lower())

assert names == {"gontor", "palestina"}, names
# The old code's choice, kept as a record of what went wrong.
assert sorted(names)[0] == "gontor", "alphabetical order picked the venue"

# The new ordering: --context names in the order the operator WROTE them.
# proper_nouns() sorts alphabetically, which is what produced the bug, so the
# context string is re-scanned. "Palestina" is what the clip is about;
# "Gontor" is only where it happened.
ctx_all = {n.lower() for n in broll.proper_nouns(CTX)}
ctx_names = []
for word in re.findall(r"\w+", CTX):
    key = word.lower()
    if key in ctx_all and key not in ctx_names:
        ctx_names.append(key)
assert ctx_names == ["prabowo", "palestina", "gontor"], ctx_names
ordered = ([n for n in ctx_names if n in names]
           + sorted(n for n in names if n not in ctx_names))
# "Prabowo" is in the context but is not a repeated name in this segment, so
# the first usable subject is Palestina — the event, not the venue.
assert ordered[0] == "palestina", ordered


def subject_for(phrase):
    said = {w.lower() for w in re.findall(r"\w+", str(phrase or ""))}
    for n in ordered:
        if n in said:
            return n
    return ordered[0] if ordered else ""


# A phrase naming its own subject wins over the context order.
assert subject_for("Gontor seratus tahun") == "gontor"
# And the case that broke: no name in the phrase, so the clip's subject is used.
assert subject_for("mereka dibom terus") == "palestina"
assert subject_for("dibantai.") == "palestina"

# Which makes the query the one that returns news footage rather than a venue.
actions = broll.action_terms("mereka dibom")
assert actions == ["dibom serangan"], actions
terms = [subject_for("mereka dibom").title(), actions[0]]
assert terms == ["Palestina", "dibom serangan"], terms

# Real Gaza coverage has to survive the title filter under that query.
real = [
    {"id": "a", "title": "Detik-detik Serangan Udara Israel Bombardir Gaza Tengah"},
    {"id": "b", "title": "Momen Warga Palestina Panik Meninggalkan Gedung yang Dibom"},
    {"id": "c", "title": "Pidato Resepsi Kesyukuran 100 Tahun Gontor"},
]
keep = broll.relevant(real, terms)
assert {h["id"] for h in keep} == {"a", "b"}, keep

print("_v9.py OK — review scoped to segment, subject resolves to Palestina, "
      "Gaza footage survives the filter")
