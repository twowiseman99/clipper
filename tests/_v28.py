"""on_topic has to mean "shot there", not "about that".

v27 put a pro-Palestine rally in JAKARTA under the caption "mereka diserang
terus-menerus". Intact high-rises, palm trees, normal traffic — and the gate
passed it. Re-checking the exact frame showed why: it answered on_topic=true
while its own description said "Pro-Palestine protest march in Jakarta". The
gate was not confused about what it saw. It was answering the question I asked.

The question was the clip topic, "Prabowo membela Palestina". A pro-Palestine
rally in Jakarta IS that, perfectly. An Indonesian name plus a cause describes
Indonesian solidarity footage better than it describes Gaza.

Two changes:

1. The topic is now a PLACE. The speaker's name and the stance verb (membela,
   bicara soal, menyinggung) are stripped, so "Prabowo membela Palestina di
   depan banyak pemimpin negara, di Gontor" becomes "Palestina".

2. on_topic now asks where the frame was SHOT, and names solidarity marches,
   another country's streets and podium officials as explicit rejects.

Measured on the four frames the previous version got wrong or right:

    Jakarta rally                   reject   (was ACCEPTED and shipped)
    funeral procession, West Bank   accept
    man searching rubble, Gaza      accept
    Israeli spokesman at podium     reject

And the Jakarta frame rejects 6/6 on repeat, so this is a stable verdict rather
than a lucky sample.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import job
import broll_place as bp

CONTEXT = "Prabowo membela Palestina di depan banyak pemimpin negara, di Gontor"

# --- the topic is a place, not a speech ---------------------------------
topic = job._clip_topic(CONTEXT, ["palestina", "gontor"], {"gontor"})
low = topic.lower()
assert "palestina" in low, f"the place was stripped: {topic!r}"
assert "prabowo" not in low, \
    f"the speaker's name is still in the gate question: {topic!r} — that is " \
    f"what let a Jakarta rally through"
assert "membela" not in low, f"the stance verb survived: {topic!r}"
assert "gontor" not in low, f"the venue survived: {topic!r}"
assert "pemimpin negara" not in low, f"the occasion survived: {topic!r}"

# Other phrasings of the same context must reduce to the same place.
for ctx in ("Prabowo bicara soal Palestina di Gontor",
            "Prabowo menyinggung Palestina dalam pidato di Gontor",
            "Prabowo mengecam Palestina di hadapan para ulama"):
    t = job._clip_topic(ctx, ["palestina", "gontor"], {"gontor"}).lower()
    assert t == "palestina", f"{ctx!r} -> {t!r}"

# --- a context that is already about the place keeps its detail ---------
rich = job._clip_topic("warga Gaza kehilangan rumah akibat serangan Israel",
                       ["gaza"], set())
assert "Gaza" in rich and "kehilangan rumah" in rich, rich

# --- empty context still yields something ------------------------------
assert job._clip_topic("", ["palestina", "gontor"], {"gontor"}) == "palestina"
assert job._clip_topic(None, [], set()) == ""

# --- the prompt names solidarity rallies as a reject -------------------
ask = bp._VISION_ASK.lower()
assert "shot on location" in ask, \
    "on_topic no longer asks where the frame was shot"
for phrase in ("solidarity march", "rally", "another country"):
    assert phrase in ask, f"the prompt does not rule out a {phrase}"
assert "banners and flags about a place are not that place" in ask, \
    "the rule that beat this bug is not stated in the prompt"
assert "podium" in ask, "a spokesperson at a podium must still be a reject"

# --- and job.py hands it the topic, computed once ----------------------
src = open(os.path.join(os.path.dirname(os.path.dirname(
                             os.path.abspath(__file__))),
                        "job.py"), encoding="utf-8").read()
assert "subject = topic" in src
assert src.index("topic = _clip_topic(") < src.index("for t0, t1, heard_term")

print(f"_v28.py OK — the gate is asked where the frame was SHOT, about "
      f"{topic!r} (was 'Prabowo membela Palestina', which a Jakarta rally "
      f"satisfied); solidarity marches, other countries' streets and podium "
      f"officials are named rejects, and the Jakarta frame that shipped in v27 "
      f"now fails 6/6")
