"""A name identifies a person, not an event.

The Gibran clip shipped zero cutaways twice. The first cause was the act gate
("korban" demanding war footage — _v33). Fixing that changed the log to

    ok   act required  location only — clip names no violence

and the result was still zero, with 37 frames rejected as off topic. Reading
the whole log rather than the tail showed what the sources actually were:

    Sidang Sengketa Ijazah Gibran Masuki Pembacaan Putusan
    Hakim Arsul Sani Pertanyakan Durasi Pendidikan Gibran
    Polemik Sidang Sengketa Ijazah Gibran di MK

Every one about his diploma case at the Constitutional Court, on a clip about
children poisoned by a school meal. The frame gate was right to reject all of
them. The query was ["Gibran"], because the cutaway was triggered by that bare
proper noun and insert_terms only ever saw the one-word phrase.

Measured on the live search backend, same box, same minute:

    ["Gibran"]              -> 7 hits, all diploma-case hearings
    ["Gibran","keracunan"]  -> Wapres Gibran Minta Maaf ke Orang Tua Murid
                               Keracunan MBG

The footage existed the whole time. Three renders' worth of "no footage passed
the gates" was a query problem wearing a gate's clothes.

Offline: no network, no ffmpeg. The search results above are recorded in the
docstring; what this test pins is the TERMS, which is where the bug was.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import broll
import job

CTX = "Gibran menemui korban keracunan MBG di Karo"
TOPIC = job._clip_topic(CTX, ["Gibran"], {"Karo"})
assert TOPIC == "korban keracunan MBG", TOPIC

# --- the bug: a bare name produced a bare query ----------------------------
# Without the topic, this is what the render asked YouTube for.
assert broll.insert_terms("Gibran", CTX) == ["Gibran"], \
    broll.insert_terms("Gibran", CTX)

# --- the fix: the event rides along -----------------------------------------
terms = broll.insert_terms("Gibran", CTX, topic=TOPIC)
assert terms[0] == "Gibran", terms
assert "keracunan" in terms, terms
# The event word must come BEFORE anything the one-word phrase contributed:
# it is what separates this story from every other story about this person.
assert terms.index("keracunan") <= 2, terms

# --- a venue trigger keeps its own name, and still gets the event -----------
karo = broll.insert_terms("Karo", CTX, topic=TOPIC)
assert karo[0] == "Karo", karo
assert "keracunan" in karo, karo

# --- no duplicates, even when topic and phrase overlap ----------------------
dup = broll.insert_terms("keracunan", CTX, topic=TOPIC)
assert len(dup) == len({w.lower() for w in dup}), dup

# --- no topic: unchanged behaviour ------------------------------------------
# Callers that pass no topic must get exactly what they got before, so this
# cannot change the Palestine path, which goes through action_terms instead.
assert broll.insert_terms("Gibran", CTX, topic="") == ["Gibran"]

# --- the framing words must still stay out ----------------------------------
# This is the earlier bug this function already guarded: context contributes
# proper nouns only, never its wording, or the search chases the framing line.
pal = "Prabowo membela Palestina di depan banyak pemimpin negara, di Gontor"
pal_topic = job._clip_topic(pal, ["Palestina"], {"Gontor"})
pt = broll.insert_terms("Palestina", pal, topic=pal_topic)
for junk in ("banyak", "depan", "pemimpin", "negara", "membela"):
    assert junk not in [w.lower() for w in pt], (junk, pt)

# --- term count stays bounded ------------------------------------------------
# A query of six words finds nothing; the cap is what keeps this usable.
long_ctx = "Gibran menemui korban keracunan MBG di Karo Sumatra Utara kemarin"
lt = broll.insert_terms("Gibran", long_ctx,
                        topic=job._clip_topic(long_ctx, ["Gibran"], {"Karo"}))
assert len(lt) <= 4, lt

print("_v34 ok — the clip's event rides along with the name; "
      "framing words still excluded")
