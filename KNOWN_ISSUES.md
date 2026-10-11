# Known product issues

Defects in the clip the viewer sees, as opposed to defects in the tooling.
Recorded here rather than fixed in passing: each one needs its own
investigation, and a fix shipped in the same breath as a log change cannot be
attributed to either.

Format: what a viewer sees, then the measurement that proves it, then what is
actually unknown. No issue is closed without a render that demonstrates the
fix.

---

## 1. The closing freeze can hold a bystander instead of the subject

**Status:** open, not investigated. Logged 2026-10-11. Sharpened 2026-10-11
after fixing the debug-row truncation (see "What the gate actually says").
**Severity:** the last thing a viewer sees is a stranger's face on a clip
about someone else. On a grief clip that is a factual claim about whose story
it is, the same class as the flag-emoji defect.

**What a viewer sees.** The clip ends on a held still of a face in the crowd —
a woman in a striped jacket, a man in a cap holding up a phone — rather than
Gibran, who the clip is about.

**Agent/gate:** Pemilih Gambar (`freeze`)
**Stage:** freeze
**Source:** `freeze_pick.py:pick` → `job.py:run`

**Evidence render.**

```
render_id : clip_1791642180_122
title     : Gibran Minta Maaf ke Ibu Korban MBG, Pesan Terakhirnya Bikin Hening 😢
clip      : /home/ubuntu/clipper/jobs/clip_1791642180_122.mp4
duration  : 28s, mood emotional, 8 cek, 1 ditolak
video     : 144,27s-150,27s source time (31 frames, step 0,2s)
qualified : 0 of 31
trigger   : best confidence 0,48 vs MIN_CONF 0,55
error     : no qualifying frame
fallback  : mechanical frame (freeze_at as computed, unverified)
ledger    : /home/ubuntu/clipper/jobs/clip_1791642180_122.audit.json
```

**What the gate actually says.** Worth recording precisely, because the
earlier wording here understated it. The per-frame debug rows were being
sliced at 40/26 characters, which cut mid-word and left an unbalanced
bracket, so the reason read as noise: `"Prabowo Subianto (older man at podium
in (turned toward camera, well)"`. With the rows cut on a word boundary it is
legible, and it is not "the gate could not find Gibran" — the gate is
confidently naming a DIFFERENT IDENTIFIED PERSON, Prabowo, at confidence 0,95
across the whole window. The ending is reaching into a stretch of footage
where the subject is not the person on camera at all.

That changes what a fix would be. It is not a threshold question and not a
"pick a better frame in this window" question: the window itself is wrong for
this clip. Measure the subject's actual on-screen spans before anything else.

```
render_id : render5
frames    : 31 judged, 0 qualified, window 249,95s-255,95s
reads     : "Prabowo Subianto (older man at podium…)" at conf 0,95, ok=false
debug     : jobs/freeze-debug/render5.20261011-193007.freeze.json
```

The gate was not wrong to reject those frames — it was reading them
correctly. Its own rejection reasons say so, 30 of 31 variations of the same
observation:

```
145,07s no  conf 0,78  man in dark cap in background crowd (foreground head is in profile)
145,67s no  conf 0,84  the older woman in the blue track jacket (turned toward camera and lit)
149,07s OK  conf 0,48  foreground young man in dark jacket at left (near-profile but sharp)
149,27s no  conf 0,72  Foreground man in dark jacket (likely Gibran) (profile — largest face is)
```

**What that says.** Across the whole 6s window the subject is in profile or
motion-blurred, and every frontal, well-lit face belongs to someone in the
crowd behind him. The one frame marked OK scored 0,48 — below the floor — and
describes a "foreground young man", not the named subject either.

So the gate is working and the FOOTAGE does not contain what the ending needs.
The defect is in what happens next: the fallback keeps the mechanical frame
anyway and ships it, which is the one outcome the operator has ruled out
elsewhere ("no cutaway + warning" is preferred to a wrong cutaway).

**What is unknown, and must be measured before anything is changed:**

1. Is the 6s `LOOKBACK` the problem? A clip whose last 6s are a walking shot
   may have a clean frontal at 12s. Widening the window costs vision calls and
   moves the freeze away from the final sentence — both need measuring, not
   guessing.
2. Is `MIN_CONF 0.55` right for this question? The rejected frames score
   0,72-0,90 for being the WRONG PERSON clearly. Confidence and
   subject-identity are two different axes collapsed into one number.
3. What should the fallback be when no frame qualifies? Candidates: hold the
   `--portrait` still if one was passed; dip to black earlier and skip the
   held frame; keep the mechanical frame but never on a grief clip. This is a
   product decision, not a threshold.
4. Does the delivered file actually show the frame the log blames? Per the
   measuring rule, this must be checked on the FILE — frames of
   `clip_1791642180_122.mp4` at its own ending — not on the gate's log, whose
   timestamps are source-relative.

**Do not** fix this by lowering `MIN_CONF`. The gate's reads are accurate; a
lower floor would ship the bystander with the log claiming it passed.
