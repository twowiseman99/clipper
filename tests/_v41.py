"""--end-at-sentence must cut where speech stops, and the shake must match the
reference's density.

Two operator findings in one render:

1. "Mana gibran ngomong kasih bekal?" — the clip was 22s from --start 143.0,
   but Gibran's sentence runs 143.70-150.20 (6.5s). The remaining 15s was an
   unrelated aside ("tapi dua perempuan rekomendasi apa itu?") and crowd noise
   ("jangan dorong"). --start plus --seconds makes the operator guess the
   length of a thought; the transcript already knows it.

2. "Getarannya terlalu gitu itu" — measured against the reference he sent
   (youtube AGv6G13TPUc, 30-34s): 8 hits in 4.0s, 2.00/second. Ours ran
   5.77/second, nearly 3x denser, because OUTRO_PUNCH_PER_BEAT=3 was tuned
   against a DIFFERENT reference short.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edit  # noqa: E402
import segments as selector  # noqa: E402

# --- the shake density must match the measured reference --------------------
REF_HITS_PER_SEC = 2.00         # 8 hits in 4.0s, measured on AGv6G13TPUc
ours = edit.OUTRO_SHAKE_HZ * edit.OUTRO_PUNCH_PER_BEAT
assert abs(ours - REF_HITS_PER_SEC) / REF_HITS_PER_SEC < 0.15, (
    "shake runs %.2f hits/s against the reference's %.2f — the ending is %.1fx "
    "the reference density" % (ours, REF_HITS_PER_SEC, ours / REF_HITS_PER_SEC))

# The attack must survive the slower rate. The envelope is exp(-DECAY*phase)
# with phase spanning one beat, so DECAY and the period are coupled: at 3
# hits/beat (0.173s) DECAY=2 gave a 0.087s snap, and keeping DECAY=2 at 1
# hit/beat (0.520s) would stretch that to 0.260s — a drift, not a hit.
period = 1.0 / ours
snap = (1.0 / edit.OUTRO_PUNCH_DECAY) * period
assert snap < 0.12, (
    "each hit takes %.3fs to decay: that reads as a slide, not a punch "
    "(DECAY %.1f at a %.3fs period)"
    % (snap, edit.OUTRO_PUNCH_DECAY, period))

# --- snapping the end to where speech stops ---------------------------------
# Synthetic transcript with the shape of the real one: a sentence, a long
# silence, then unrelated talk.
words = []
t = 10.0
for w in "dan saya titip anak-anaknya membawa kotak dari rumah".split():
    words.append({"word": w, "start": t, "end": t + 0.4})
    t += 0.45
sentence_end = words[-1]["end"]
t += 6.0                                  # the silence
for w in "tapi dua perempuan rekomendasi apa itu".split():
    words.append({"word": w, "start": t, "end": t + 0.4})
    t += 0.45

# A 22s window from 10.0 contains all of it; the end must come back to the
# sentence, not the clock.
new_end, why = selector.snap_to_speech_end(words, 10.0, 32.0, min_dur=3.0)
assert new_end is not None, why
assert abs(new_end - (sentence_end + 0.35)) < 0.01, (new_end, sentence_end)
assert "silence" in why, why

# The guard matters more than the snap: the jamet ending returns nothing when
# the clip is under 3x its span, which is how a render lost its outro silently.
# A min_dur it cannot satisfy must refuse rather than hand back a short clip.
short, why_short = selector.snap_to_speech_end(words, 10.0, 32.0, min_dur=20.0)
assert short is None, (short, why_short)
assert "under" in why_short or "less than" in why_short, why_short

# A segment opening on the tail of the previous sentence is the common case,
# because --start is set by eye. The first silence then sits right after those
# few words and would leave almost nothing: the search must skip it and take
# the next usable break.
lead = [{"word": "Ya,", "start": 6.0, "end": 6.2},
        {"word": "Pak.", "start": 6.25, "end": 6.45}] + words
lead_end, why_lead = selector.snap_to_speech_end(lead, 6.0, 28.0, min_dur=3.0)
assert lead_end is not None, why_lead
assert abs(lead_end - (sentence_end + 0.35)) < 0.01, (
    "cut at %.2f: the search stopped on the leading pause instead of the "
    "sentence end (%s)" % (lead_end, why_lead))

# Speech running to the very end is not a snap opportunity.
tight = [{"word": "a", "start": 0.0, "end": 9.8},
         {"word": "b", "start": 9.85, "end": 10.0}]
none_end, why_none = selector.snap_to_speech_end(tight, 0.0, 10.0, min_dur=3.0)
assert none_end is None, (none_end, why_none)

# --- the flag has to be wired, not just defined -----------------------------
import inspect  # noqa: E402

import job  # noqa: E402

assert "snap_end" in inspect.signature(job.run).parameters, (
    "job.run does not accept snap_end")
src = inspect.getsource(job)
assert "--end-at-sentence" in src, "the CLI flag is missing"
assert "snap_end=a.end_at_sentence" in src, (
    "the CLI flag is parsed but never passed to run()")
assert "snap_to_speech_end" in src, "run() never calls the snapper"

print("_v41 ok — shake %.2f hits/s vs reference %.2f (snap %.3fs), end snaps "
      "%.2f -> %.2f on silence, refuses when under min_dur, flag wired"
      % (ours, REF_HITS_PER_SEC, snap, 32.0, new_end))
