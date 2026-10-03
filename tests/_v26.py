"""A gate must give the same answer twice, and must be asked the right question.

Two defects found by re-checking a frame the render had rejected.

1. NON-DETERMINISM. vision_json ran at temperature 0.2. The v25 log said
   "o18wLEuDGvQ @37s rejected by vision (off topic: Massive smoke plume from
   explosion)"; re-checking that exact frame returned on_topic=True,
   shows_action=True six times out of six. The log and the re-check disagreed
   because the gate was sampling. A gate that moves between runs cannot be
   debugged from its own log.

2. THE WRONG QUESTION. The subject string was --context plus the term:

       "Prabowo membela Palestina di depan banyak pemimpin negara, di Gontor
        — Palestina"

   --context describes the SPEECH. Asking whether Gaza footage shows "di depan
   banyak pemimpin negara, di Gontor" is asking whether rubble in Gaza shows a
   podium in East Java, and the answer is correctly no. Measured on the same
   frames with the venue and occasion clauses stripped:

       t=105  Israeli armoured vehicle   on_topic False -> True
       t=55   man walking through rubble on_topic False -> True

   Those are real Gaza frames that the full-context string was rejecting.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import ai
import job

# --- the gate is deterministic -----------------------------------------
assert ai.vision_json.__defaults__ is not None
temp = ai.vision_json.__defaults__[-1]
assert temp == 0.0, \
    f"vision_json runs at temperature {temp}: the same airstrike frame was " \
    f"accepted on one call and rejected on another at 0.2"

# chat_json is creative work (hooks, titles) and must NOT be dragged to zero.
assert ai.chat_json.__defaults__ is not None
chat_temp = ai.chat_json.__defaults__[-1]
assert chat_temp > 0.0, \
    "copywriting should keep its temperature; only the gate needs determinism"

# --- the venue never reaches the frame gate ----------------------------
CONTEXT = "Prabowo membela Palestina di depan banyak pemimpin negara, di Gontor"
subj = job._footage_subject(CONTEXT, "Palestina", {"gontor"})
low = subj.lower()
assert "gontor" not in low, f"the venue reached the frame gate: {subj!r}"
assert "pemimpin negara" not in low, \
    f"the speaking occasion reached the frame gate: {subj!r}"
assert "palestina" in low, f"the actual subject was stripped: {subj!r}"

# --- but real subject detail survives ----------------------------------
# A context that genuinely describes the footage must not be gutted.
subj = job._footage_subject("warga Gaza kehilangan rumah akibat serangan",
                            "Gaza", {"gontor"})
assert "kehilangan rumah" in subj, subj

# --- and the term alone is enough --------------------------------------
assert job._footage_subject("", "Palestina", set()) == "Palestina"
assert job._footage_subject(None, "Gaza", set()) == "Gaza"

# A context made entirely of venue and occasion must still leave the term.
only_venue = job._footage_subject("di Gontor", "Palestina", {"gontor"})
assert only_venue == "Palestina", only_venue

# --- the venue set is the one already used for triggers ----------------
# _venue_names is what excludes "Gontor" as a cutaway trigger; the frame gate
# must strip the same names rather than keep a second list that drifts.
venues = job._venue_names(CONTEXT, {"gontor", "palestina"})
assert "gontor" in venues, venues
assert "palestina" not in venues, \
    "the subject of the clip must not be treated as a venue"
stripped = job._footage_subject(CONTEXT, "Palestina", venues)
assert "gontor" not in stripped.lower(), stripped

# --- job.py actually calls it -----------------------------------------
src = open(os.path.join(os.path.dirname(os.path.dirname(
                             os.path.abspath(__file__))),
                        "job.py"), encoding="utf-8").read()
assert "subject = topic" in src, \
    "job.py no longer hands the clip topic to the frame gate"
assert "_clip_topic(context" in src, \
    "the venue-stripping topic is never computed"

print(f"_v26.py OK — vision gate pinned to temperature 0.0 (chat_json left at "
      f"{chat_temp}), and the frame gate is asked about "
      f"{subj!r}-style subjects with the venue and speaking occasion stripped "
      f"(was the whole --context string, which rejected real Gaza rubble)")
