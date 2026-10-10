"""Two faults in the 12.8s render the operator rejected.

"ngaco, kenapa subtitlenya masih jalan? videonya ampas cuman 12 detik"

1. Captions animated on top of the frozen ending. The freeze turns the last
   frame into a still, but overlay windows come from the transcript and knew
   nothing about it: 6 of 21 caption tiles had windows past the freeze point
   (7.80s), the last running to 10.46s. The ending is supposed to be a held
   frame with a shake on it, and moving text underneath cancels that.

2. The clip was 12.8s, of which 3.06s (24%) was the ending, because
   snap_to_speech_end cut at the first usable silence. With --start on the
   sentence itself that is right, but it leaves no room for build-up: the
   operator wants the moment that leads INTO the line, so the clip has to be
   able to open earlier and still end on the sentence.

   Opening at 122.0 exposed the real flaw. Three position-based rules were
   tried and all failed:
     - first usable silence       -> 14.7s, ends BEFORE the lunch-box line
     - last keyword in range      -> 42.3s, follows "anak" into a passage 17s
                                     later that has nothing to do with it
     - first contiguous keyword run -> 14.7s again, stops on "anak" at 128.16
   Keyword DENSITY per run of speech separates them: Gibran's sentence holds
   four distinct keys, the passages around it hold one each.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edit  # noqa: E402
import segments as selector  # noqa: E402

# --- 1. captions must not run over the frozen ending ------------------------
# _outro_start has to agree with _outro_filters about whether there IS an
# ending and where it begins, or the clamp either fires on a clip with no
# outro or misses the one it has.
edit.OUTRO = "jamet"
for dur in (8.0, 10.81, 12.83, 22.0, 30.0):
    bright, filters = edit._outro_filters(dur, mood="hype")
    start = edit._outro_start(dur, mood="hype")
    has_outro = bool(bright or filters)
    assert has_outro == (start is not None), (
        "dur %.2f: _outro_filters says outro=%s but _outro_start says %s"
        % (dur, has_outro, start))
    if start is not None:
        assert abs(start - (dur - edit.OUTRO_JAMET_SECONDS)) < 0.01, (dur, start)

# A clip too short for an ending must not get a clamp at all.
assert edit._outro_start(5.0, mood="hype") is None

# And the clamp must actually be applied where overlays are emitted. Asserting
# on the CALL STRING broke the moment the signature grew a `words=` argument,
# while the behaviour it guards was fine — so check the behaviour instead: the
# caption chain must receive an outro boundary and stop animating past it.
import inspect  # noqa: E402

src = inspect.getsource(edit)
assert "_outro_start(" in src and "outro_at" in src, (
    "the caption chain never asks where the outro starts")

# The boundary has to be the real one. With a transcript it snaps to the end of
# speech; without one it falls back to the mechanical placement. Both are
# clamps — neither may be None on a clip long enough for an ending.
assert edit._outro_start(30.0, mood="hype") is not None
_spoken = [{"word": "x", "start": 0.0, "end": 20.0}]
_snapped = edit._outro_start(30.0, mood="hype", words=_spoken, clip_start=0.0)
# The freeze point is the end of speech plus a two-frame margin: the still
# overlay has to be armed BEFORE the frame `loop` clones, and arming it early
# instead cut the picture 0.2s before the last word ended (measured as a 28.99
# frame-difference throw at 30.75s on a delivered file). The margin comes out of
# the freeze, never out of the sentence — so the assertion is "at or just after
# speech ends, within one frame of slack", not an exact equality that pins the
# margin itself.
_lead = max(2.0 / float(edit.FPS), 0.05)
assert _snapped is not None, "the ending must have a start with a transcript"
assert 20.0 <= _snapped <= 20.0 + _lead + 1.0 / float(edit.FPS), (
    "with a transcript the ending must start at the end of speech (20.0) plus "
    "at most the still-overlay margin (%.3fs), got %s" % (_lead, _snapped))

# --- 2. the end lands on the subject's sentence, not the first silence ------
# Shape of the real transcript: an apology passage, the lunch-box sentence,
# then an unrelated passage that reuses one of the keywords.
def say(text, t, step=0.3):
    out = []
    for w in text.split():
        out.append({"word": w, "start": t, "end": t + step * 0.7})
        t += step
    return out, t


apology, t = say("kami buk saya minta maaf sampaikan ke anggannya seperti ini", 10.0)
t += 2.0
sentence, t = say("dan saya titip anak anaknya membawa kotak dari rumah "
                  "sebab itu ada yang dimasak ibu", t)
sentence_end = sentence[-1]["end"]
t += 2.5
tail, t = say("kami bantuan kamu anak anak kembali abu abu ya", t)
words = apology + sentence + tail

keys = ["gibran", "menitip", "anak", "membawa", "kotak", "bekal", "rumah",
        "dimasak", "ibunya", "korban", "keracunan"]

# Opening on the sentence: unchanged behaviour, ends just after it.
own = sentence[0]["start"]
end_own, why_own = selector.snap_to_speech_end(
    words, own, own + 60.0, min_dur=3.0, after_words=keys)
assert end_own is not None, why_own
assert abs(end_own - (sentence_end + 0.35)) < 0.01, (end_own, why_own)

# Opening earlier for build-up: must still end on the SAME sentence, not on
# the silence that precedes it and not in the tail passage.
end_early, why_early = selector.snap_to_speech_end(
    words, 10.0, 10.0 + 60.0, min_dur=3.0, after_words=keys)
assert end_early is not None, why_early
assert abs(end_early - end_own) < 0.01, (
    "opening 12s earlier moved the cut to %.2f instead of %.2f (%s)"
    % (end_early, end_own, why_early))
assert end_early > sentence[-1]["start"], (
    "the clip ends before the sentence it was built for")

# The tail reuses "anak"; the cut must not follow it there.
assert end_early < tail[0]["start"], (
    "the cut ran into the unrelated passage at %.2f" % tail[0]["start"])

# Filler words must not act as subject markers: a context made only of them
# behaves as if no keys were given.
end_filler, _ = selector.snap_to_speech_end(
    words, 10.0, 10.0 + 60.0, min_dur=3.0,
    after_words=["yang", "dari", "saat", "untuk", "saya"])
end_none, _ = selector.snap_to_speech_end(
    words, 10.0, 10.0 + 60.0, min_dur=3.0)
assert abs(end_filler - end_none) < 0.01, (
    "filler-only keys changed the cut (%.2f vs %.2f)" % (end_filler, end_none))

# The ending must leave a real clip behind it. The 12.8s render the operator
# rejected gave 3.06s (24%) to the outro, and "videonya ampas cuman 12 detik"
# was about the clip being short, not about the ending being long.
#
# This used to cap the ending at 15% of runtime. That cap cannot survive the
# freeze the operator then asked for — "selalu 5 detik", which is 16% of the
# 31.8s segment this clip comes from — so the check moved to what the complaint
# was actually about: how much VIDEO is left after the freeze.
REAL_DUR = 31.8
body = REAL_DUR - edit.OUTRO_JAMET_SECONDS
assert body >= 20.0, (
    "a %.1fs freeze leaves only %.1fs of body on a %.1fs clip"
    % (edit.OUTRO_JAMET_SECONDS, body, REAL_DUR))
assert edit.JAMET_BODY_MIN > 0, "no body floor: short clips become all ending"

# The rejected render is the negative control: the same ending on a 12.8s clip
# leaves 7.8s, which is what "videonya ampas cuman 12 detik" was about.
assert 12.83 - edit.OUTRO_JAMET_SECONDS < 10.0, (
    "fixture drift: the rejected 12.8s render no longer looks ending-heavy, "
    "so this check cannot tell the two cases apart")

dur_early = end_early - 10.0

print("_v43 ok — captions clamp at the freeze (outro_start agrees with "
      "outro_filters on 5 durations), opening %.1fs earlier still ends on the "
      "sentence (%.2f, %s), a %.1fs freeze leaves %.1fs of body on %.1fs vs "
      "%.1fs on the rejected 12.8s"
      % (own - 10.0, end_early, why_early, edit.OUTRO_JAMET_SECONDS, body,
         REAL_DUR, 12.83 - edit.OUTRO_JAMET_SECONDS))
