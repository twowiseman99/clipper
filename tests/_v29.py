"""A run of short same-subject sentences is one breath, not three thoughts.

Every cutaway in an 82s clip landed inside its first 20 seconds: 10.7, 14.3,
17.6. The cause was not spacing policy, it was this line:

    in_burst = bool(burst) and burst < BURST_MAX

After the first window `burst` is 1, and `bool(1)` never becomes false, so the
burst never ended. Three SEPARATE sentences were spaced with BURST_GAP (2.5s)
as if they were one list:

     9.30-10.70   Mereka dibantai.
    13.16-14.26   Mereka dibom.
    16.76-23.72   Mereka diserang terus-menerus.

Clearing the burst on any sentence-final word fixed the spacing and left
exactly ONE cutaway in 82 seconds, because this speaker ends each item with a
full stop. Both readings are wrong: the punctuation says three thoughts, the
delivery is one escalating breath.

So the unit is the BLOCK. `sentence_blocks()` marks a run of sentences that are
all short, close together, and open with the same word — the anaphora
Indonesian political speech escalates with. A full stop inside such a run does
not end the burst; a full stop anywhere else does.

Measured on the Gontor transcript, the run is unambiguous. The three "Mereka"
sentences are 2 words each, 2.5s apart, same opener; every sentence after them
is 8-26 words with a different opener.

The second half of that clip has no cutaway and that is CORRECT, not a gap to
fill: it talks about kiai, ulama, pendidik and "kehendak untuk belajar" — no
Palestine footage belongs under it, and the venue (Gontor) is barred as a
trigger. The editing-grammar skill is explicit that cuts must land on a beat,
so inventing one at 55s would be a new bug, not an improvement.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import broll_place as bp


def words(pairs, t0=100.0, step=1.0):
    """[(offset, word)] -> whisper-shaped word list."""
    return [{"start": t0 + off, "word": w} for off, w in pairs]


TERMS = {"dibantai", "dibom", "diserang", "palestina", "gaza"}
tf = (lambda w: w.lower().strip(".,!?-") in TERMS)


def place(ws, dur=45.0, clip_start=90.0):
    return bp.phrase_windows(ws, clip_start, dur, terms_fn=tf)


# --- the block: short, same opener, tight gap -> montage spacing -------
block = words([(0.0, "Mereka"), (1.0, "dibantai."),
               (3.5, "Mereka"), (4.5, "dibom."),
               (7.0, "Mereka"), (8.0, "diserang.")])
got = place(block)
assert len(got) == 3, f"the escalating run lost cutaways: {got}"
gaps = [b[0] - a[0] for a, b in zip(got, got[1:])]
assert all(g >= bp.BURST_HOLD - 0.001 for g in gaps), \
    f"inserts overlap, ffmpeg would draw one over the other: {gaps}"
assert all(g <= bp.MIN_GAP for g in gaps), \
    f"the run was spaced as separate thoughts: {gaps}"

# --- a DIFFERENT opener is not a run ----------------------------------
got = place(words([(0.0, "Mereka"), (1.0, "dibantai."),
                   (3.5, "Warga"), (4.5, "dibom."),
                   (7.0, "Kota"), (8.0, "diserang.")]))
assert len(got) == 1, \
    f"unrelated short sentences were montaged together: {got}"

# --- a WIDE gap is not a run ------------------------------------------
got = place(words([(0.0, "Mereka"), (1.0, "dibantai."),
                   (7.0, "Mereka"), (8.0, "dibom."),
                   (14.0, "Mereka"), (15.0, "diserang.")]), dur=60.0)
assert len(got) == 2, f"a 6s gap should fall back to MIN_GAP: {got}"
assert got[1][0] - got[0][0] >= bp.MIN_GAP, got

# --- LONG sentences are not a run, even with a repeated opener ---------
long_run = []
t = 0.0
for w in ("Mereka sudah lama sekali hidup dalam keadaan dibantai. "
          "Mereka juga terus saja setiap harinya terkena dibom.").split():
    long_run.append((t, w))
    t += 0.5
got = place(words(long_run), dur=60.0)
assert len(got) == 1, f"long sentences were treated as a montage: {got}"

# --- sentence_blocks marks only the run -------------------------------
marks = bp.sentence_blocks(block, clip_start=0.0)
assert marks, "the run was not detected at all"
tail = words([(0.0, "Mereka"), (1.0, "dibantai."),
              (3.5, "Mereka"), (4.5, "dibom."),
              (20.0, "Saya"), (21.0, "kira"), (22.0, "begitu.")])
flat = bp.sentence_blocks(tail, clip_start=100.0)
assert 1.0 in flat and 4.5 in flat, flat
assert 21.0 not in flat and 22.0 not in flat, \
    f"a long trailing sentence was folded into the run: {sorted(flat)}"

# --- degenerate input ---------------------------------------------------
assert bp.sentence_blocks([], 0.0) == set()
assert bp.sentence_blocks(None, 0.0) == set()
assert bp.sentence_blocks(words([(0.0, "Mereka"), (1.0, "dibantai.")]),
                          100.0) == set(), \
    "a single sentence is not a run"

# --- the thresholds are tunable and sane -------------------------------
assert bp.BLOCK_WORDS >= 2, bp.BLOCK_WORDS
assert 0 < bp.BLOCK_GAP <= bp.MIN_GAP, (bp.BLOCK_GAP, bp.MIN_GAP)

print(f"_v29.py OK — a run of short same-subject sentences is spaced as one "
      f"montage ({bp.BLOCK_WORDS} words or fewer, {bp.BLOCK_GAP}s apart, same "
      f"opener) while a different opener, a wide gap or long sentences each "
      f"fall back to MIN_GAP={bp.MIN_GAP}s; the Gontor triplet keeps its three "
      f"cutaways instead of collapsing to one")
