"""Punch-ins must arrive in bursts, like the reference, not on a slow timer.

"Sumpah aneh, efeknya kurang sebelum jedag jedug, coba research dulu deh" —
so the reference tutorial (AGv6G13TPUc) was measured instead of guessed at.

Frame-difference motion per second (fps=10, tblend difference, signalstats
YAVG), body of clip only:

    reference               18.4 mean, peaks to 70.6, 0.81 peaks/s
    our render before       10.7 mean, peaks to 34.6, 0.21 peaks/s

And the reference's shape is CLUSTERED: bursts of 1-3 hits inside ~0.6s, then
a 2-4s gap. Five bursts across 13.5s, sizes [3,2,1,3,2].

A flat PUNCH_MIN_GAP of 9s cannot express that. On the 31.8s Gibran clip there
were 27 qualifying beats and it kept 3 — with nothing at all before t=4.7,
which is exactly the stretch the operator called flat.

What this pins:
  - clustering: bursts form, and they are separated by real quiet
  - a punch lands early, not only after several seconds
  - overlapping punches inside a burst cannot stack into a crop that eats
    the frame
  - the depth/hold constants stay in the range measured on real renders

Deliberately NOT asserted: that we match the reference's 18.4 mean. The
reference is a CapCut tutorial of a static graphic being shaken; this is a
press scrum where the footage already moves and the pillar card deliberately
skips the base zoom so the news banner is not cropped. Chasing its number
would mean inventing movement. The honest target is the shape.
"""
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edit  # noqa: E402

FPS = 30

# --- the constants stay inside what was measured ---------------------------
assert 0.08 <= edit.PUNCH_AMOUNT <= 0.14, (
    "PUNCH_AMOUNT %.3f: depth saturates past 0.10 on real renders (0.06->4.34, "
    "0.10->5.87, 0.14->6.74, 0.18->7.37 against a 2.34 control)"
    % edit.PUNCH_AMOUNT)
assert 0.35 <= edit.PUNCH_HOLD <= 0.6, (
    "PUNCH_HOLD %.2fs: 0.9s drifts (5.87), 0.45s hits (7.84), 0.30s reads as "
    "a glitch" % edit.PUNCH_HOLD)
assert edit.PUNCH_BURST >= 2, "a burst of 1 is not a burst"
assert edit.PUNCH_BURST_GAP < edit.PUNCH_MIN_GAP, (
    "burst gap %.2f must be shorter than the gap between bursts %.2f, or every "
    "beat joins one burst" % (edit.PUNCH_BURST_GAP, edit.PUNCH_MIN_GAP))


def fake_words(times, stress):
    return [{"word": "w", "start": t, "end": t + 0.2, "stress": s}
            for t, s in zip(times, stress)]


# --- clustering ------------------------------------------------------------
# Beats dense enough to offer a choice: pairs close together, groups far apart.
times = [1.0, 1.2, 1.45, 1.7,  5.0, 5.3, 5.55,  9.0, 9.4,  14.0, 14.3,
         19.0, 19.5,  24.0, 24.4, 24.8]
stress = [1.9, 1.5, 1.4, 1.3,  1.8, 1.5, 1.35,  1.7, 1.4,  1.6, 1.4,
          1.75, 1.45,  1.65, 1.5, 1.3]
picked = edit._punch_times(fake_words(times, stress), 0.0, 30.0)
assert picked, "no punches from 16 qualifying beats"

bursts = []
cur = [picked[0]]
for t in picked[1:]:
    if t - cur[-1] <= edit.PUNCH_BURST_GAP:
        cur.append(t)
    else:
        bursts.append(cur)
        cur = [t]
bursts.append(cur)

assert any(len(b) >= 2 for b in bursts), (
    "every punch is isolated: %s — the reference arrives in bursts of 1-3"
    % [len(b) for b in bursts])
assert max(len(b) for b in bursts) <= edit.PUNCH_BURST, (
    "a burst of %d exceeds PUNCH_BURST=%d"
    % (max(len(b) for b in bursts), edit.PUNCH_BURST))

# Real quiet between bursts. Without it the clip shakes continuously, which is
# the opposite failure and reads as a template.
gaps = [b[0] - a[-1] for a, b in zip(bursts, bursts[1:])]
assert gaps, "only one burst over 30s"
assert min(gaps) >= edit.PUNCH_MIN_GAP - edit.PUNCH_BURST_GAP - 0.01, (
    "bursts %.2fs apart: they smear into one another" % min(gaps))

# --- something happens early ----------------------------------------------
assert min(picked) <= 3.0, (
    "first punch at %.1fs: the opening is the part the operator called flat"
    % min(picked))

# --- overlapping punches must not eat the frame ---------------------------
# Three hits inside one burst sum their cosine bumps. Evaluate the real
# expression rather than reasoning about it.
expr = edit._punch_expr([1.2, 1.38, 1.7], FPS)
terms = re.findall(
    r"([0-9.]+)\*between\(on,(\d+),(\d+)\)\*\(0\.5-0\.5\*cos\(2\*PI\*"
    r"\(on-(\d+)\)/(\d+)\)\)", expr)
assert len(terms) == 3, "expected 3 bumps, parsed %d from %r" % (len(terms), expr)


def zoom_at(on):
    total = 0.0
    for amp, a, b, a2, per in terms:
        a, b, a2, per = int(a), int(b), int(a2), int(per)
        if a <= on <= b:
            total += float(amp) * (0.5 - 0.5 * math.cos(2 * math.pi * (on - a2) / per))
    return total


peak = max(zoom_at(on) for on in range(0, int(3 * FPS)))
assert peak <= 0.22, (
    "overlapping punches reach %.1f%% zoom: the frame gets cropped" % (peak * 100))
assert peak >= edit.PUNCH_AMOUNT * 0.95, (
    "overlap peak %.4f is below a single punch %.4f — the bumps are cancelling"
    % (peak, edit.PUNCH_AMOUNT))

# --- no beats means no invented beats -------------------------------------
quiet = edit._punch_times(fake_words([2.0, 6.0], [0.3, 0.4]), 0.0, 30.0)
assert quiet == [], "punches invented on a clip with no vocal emphasis: %s" % quiet

print("_v47 ok — %d punches in %d bursts %s, first at %.1fs, quiet gaps >= "
      "%.1fs, overlap peaks at %.1f%% zoom (amount %.2f, hold %.2fs)"
      % (len(picked), len(bursts), [len(b) for b in bursts], min(picked),
         min(gaps), peak * 100, edit.PUNCH_AMOUNT, edit.PUNCH_HOLD))
