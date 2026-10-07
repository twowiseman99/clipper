## 7fa4550 — the snap was eating the melancholy outro

Operator: "Ok berarti kita skrng ada 2 preset ya? Jedag jedug sama preset sedih,
ga lu replace kan codenya?"

Nothing was replaced. But checking it properly — by RENDERING the sombre preset
instead of reading the diff — found a real bug in it.

### Both presets are intact and take different paths

```
sedih  OUTRO=melancholy  kind=melancholy  span 8.00s  5 filters
jamet  OUTRO=jamet       kind=jamet       span 5.00s  9 filters
```

Every jamet change from `b0ad70c` sits behind `kind == "jamet"`: `_jamet_span`,
`JAMET_BODY_MIN`, the fps-before-loop fix. Verified by raising
`OUTRO_JAMET_SECONDS` to 9.0 and confirming the melancholy span does not move.

### The bug the check found

`_outro_snap` moves the ending to the last word **and shrinks it**, because the
caller then does `span = dur - start`.

That is correct for jamet, whose `loop` clones frames and makes its own room — a
snap 0.35s before the cut still yields a full 5s freeze. The melancholy outro
has no such mechanism: its 8s desaturation ramp, vignette, slow-mo and fade all
have to fit inside the remaining footage. Measured with the real transcript:

```
dur 24.00 -> ramp 0.10s     dur 28.55 -> ramp 0.35s
dur 35.00 -> ramp 3.54s     dur 45.00 -> ramp 0.08s
```

The sombre ending was effectively absent on every duration. On the delivered
render SATAVG held at ~11 from the first second to the last — 109% of where it
started — instead of ramping to grey.

The fix is conditional on whether the ending EXTENDS the clip, not a shared
threshold. Tightening the room check for everyone would have un-snapped the
jamet freeze and put it back on top of the payoff line, which is the whole
reason the snap exists:

```python
if not extends and dur - last < span * SNAP_MIN_ROOM:
    return None
```

Both call sites pass `extends=(kind == "jamet")`. Third time this file has been
bitten by one value read from two places, so they were patched together.

### A second thing that looked like a bug and was not

`_outro_output_len` only understood the jamet `trim=`, so for melancholy it
reported `dur` and made the dip to black look like it was scheduled past the end
of the stream (`st=46.93` on a 45.03s file). It is not — the slow-mo stretches
the tail. Confirmed in ffmpeg rather than argued from the graph:

```
dur 24.00  computed 27.43  ffmpeg 27.40  fade 25.93 -> inside
dur 28.55  computed 31.98  ffmpeg 31.97  fade 30.48 -> inside
```

### Re-rendered sedih, md5 differs

```
before fix  45.03s  SATAVG 10.29 -> 11.21  (109%, flat)
after fix   48.37s  SATAVG 10.29 ->  0.00  (greyscale)
```

### Verification

`_v56` is new. It asserts the two presets disagree on mood/outro/broll/flash,
that the melancholy chain has no `loop=` and keeps its `hue=s=` ramp, that the
jamet body floor does not reach the sombre path, and that the snap leaves the
melancholy ramp whole while still firing for jamet.

54 ok, with `_v9`/`_v10` still failing on a deleted transcript.

Negative controls, both verified to fail: swapping sedih's preset to jamet trips
"both presets now use the same mood"; disabling the room check trips "the
melancholy ramp is 0.10s on a 24.00s clip".

Worth recording: no test caught this because none of them rendered the sombre
preset. The jamet work was covered frame by frame while sedih was only ever
reasoned about.

Signed: Dalmislave

## b0ad70c — the jamet freeze runs a full 5 seconds, always

Operator: "Setelah "Sebab itu yg dimasak ibu" / Lansung freze frame jedag jedug
goyang sama perubahan exposure, ikutin beat selama 5 detik", and on the
trade-off: "sementara nomor 2 dulu, selalu 5 detik".

The freeze already landed in the right place — 28.20s, the end of "...yang
dimasak ikut" — so this is about its length. `OUTRO_JAMET_SECONDS` 3.0 -> 5.0,
fixed, not scaled by clip length.

### A frame-rate bug was hiding behind the shorter window

```
overlay -> loop=loop=150:size=1:start=846 -> trim=end=33.200 -> ... -> fps=30
```

`loop` counts FRAMES and `start` is computed as `start*FPS`, so the two have to
agree on what a frame is. This source is 60fps and the conversion sat at the END
of the chain, so loop ran on the 60fps stream:

```
start=846 @60fps  ->  14.10s, not 28.20s
loop=150  @60fps  ->   2.50s of clones, not 5.00s
```

The delivered file reported 33.20s of audio over 31.07s of video — the last
2.13s had **no picture** — and the flicker stopped 2.5s into the freeze.
Measured 932 frames out, exactly `(28.55 + 150/60) * 30`: the arithmetic was
right and the rate was wrong, which is why the graph read as correct on
inspection. Confirmed in ffmpeg on a 60fps source, same expressions:

```
fps AFTER  loop   ->  932 frames / 31.07s
fps BEFORE loop   ->  996 frames / 33.20s
```

### Two guards assumed a shorter freeze

`dur < span * 3` needed 15s of clip before any ending existed, which silently
removed the outro from 9.5s and 12s clips (`_v36`, `_v48`) — the same failure as
the 8s span dropping the outro from a 22s clip, already recorded in
`_outro_filters`. Replaced by `JAMET_BODY_MIN`: the freeze has to leave 4s of
body behind, which is what the original complaint was about.

The body floor was initially gated on `seconds is None`, so callers passing an
explicit span — the renderer and `_v48` both do — stayed on the old rule and a
12s clip still lost its ending. Three call sites, patched together.

`_v43` capped the ending at 15% of runtime, and 5s of a 31.8s clip is 16%. That
cap was written for the 8s stinger; it now asserts the surviving body (26.8s).

### Retuning the hit density for a longer window

`FLASH_WINDOW_FRACTION` 0.50 -> 0.65. A fraction tuned for a 3s window does not
carry to a 5s one, and the largest GAP matters more than the count: one 1.3s
hole in a 5s ending reads as the effect having stopped.

```
0.50 -> 6 hits, median 0.78s, largest gap 1.31s
0.65 -> 7 hits, median 0.78s, largest gap 0.78s
```

### Delivered file

```
33.20s video == 33.20s audio, 996 frames, 1080x1920
freeze 28.20-33.20, 21 exposure frames (last at +4.60s), none in the body
every second of the freeze carries a hit
```

### Verification

`_v55` is new and asserts the output's own duration AND frame count against the
audio, so a rate mismatch anywhere in the chain cannot pass.

`_v54`'s ending check was rewritten. It compared freeze median against body
median, and a longer freeze holds a still frame between hits — so adding
stillness DROPPED the median (5.10px against the body's 6.85px) while the hits
themselves were unchanged at 8.4/s over 15px. The ending was fine and the ruler
was wrong. It now counts hard throws against the control.

53 ok, with `_v9`/`_v10` still failing on a deleted transcript.

Negative controls: the fps-bug render fails `_v55` on the 2.13s audio/video gap;
the earlier rejected render fails `_v54` at 69.6% of frames against 61.6%.

Signed: Dalmislave

## 8d9e06b — nothing in the body moves the frame

Operator, after being asked to check frame by frame: "baru nonton detik awal aja
ud najis gw liat editan editan di detik awal, goyang" gajelas".

The previous two rounds measured BRIGHTNESS only (signalstats YAVG), which is
blind to a crop or a zoom: the frame can slide sideways at a perfectly flat
average luminance. Measured with vidstabdetect on the delivered file:

```
moving frames (>3px)    22 / 240    9.2%
clustered at            0.87 - 1.93s
```

### Two effect families were never on the beat path

**Zoom punch-ins** fire on emphasised WORDS, not beats, so they inherited none of
the freeze window the previous fix installed: 12 of them, three stacked inside
the first 1.7s. Now clamped with `_after()` like the flicker and the slam.

`_zoompan()` also called `_punch_times()` itself, so clamping the caller's copy
changed nothing and the punches shipped anyway. It now accepts `punch_times`.
Same shape as the `FRAME_MODE` trap already documented in that function: a value
with two independent sources is read twice, and fixing the one you edited is not
evidence.

**`_pan_cover`**, the speaker-tracking crop, moved 18.6px inside its window
against 4.3px elsewhere in the body, with two reframes inside 2.1s.

### Turning the pan off was wrong, and the suite said so

`_v46` forbids `CLIPPER_PAN=0`, and it is right. With a fixed window this clip's
subject walks from 0.377 to 0.896 of frame width while the window spans 0.316,
leaving him OUTSIDE it in 56% of samples. The choice is not "movement or no
movement" but "camera move or lost subject".

So the pan stays and gets slower: `PAN_HOLD` and `PAN_SLIDE` 0.6 -> 2.0.

```
hold 0.6 slide 0.6    7 keyframes    4% outside    675 px/s   (shipped)
hold 2.0 slide 2.0    3 keyframes    9% outside    317 px/s   (now)
```

Same subject coverage at a third of the speed, so the reframe stops registering
as an edit while still following him.

### Delivered file, against a fair control

The control is the FULL pillar card — blurred background, foreground overlay,
same scales — with the crop window frozen and no effects at all.

```
body 0-28.2s        62.3% of frames / 6.40px    control 61.6% / 5.10px
freeze 28.2-31.2s   80.4% / 8.18px, peaks to 91px
                    1080x1920, 31.20s
```

A bare scale+crop of the source is NOT a fair control and cost a round: it
measures 4.12px, which reads as "we are still adding movement", while the pillar
composite with a frozen window measures 5.10px. The composite itself carries
about a pixel of it.

### Verification

`_v54` is new and pins movement itself rather than any one filter, so a third
effect family cannot reintroduce this quietly. `_v46` was rewritten: it asserted
a keyframe COUNT, which fails on a slower pan that still tracks correctly, and
now asserts the subject stays inside the window. 52 ok, with `_v9`/`_v10` still
failing on a deleted transcript.

Negative control: the rejected render fails `_v54` at 69.6% of frames against
the control's 61.6%.

Signed: Dalmislave

## 81a02f4 — the effects live in the freeze, not across the clip

Operator, asked to check the delivered render frame by frame: "itu kenapa efeknya
dari awal sampe akhir? harusnya cukup pas di freeze frame aja setelah kotak makan
dari rumah, masih kelebihan terus".

Measured on that file, all 936 frames:

```
brightness jumps in the body     51    0.47s .. 26.07s
brightness jumps in the freeze    0
```

The exact inverse of the request. Earlier rounds tuned the DENSITY of the
flicker — rate, burst shape, spacing — and never questioned its RANGE, which is
why every delivery came back "masih kelebihan".

### Four things had to change together

**The selection happens inside the window.** `_window_beats()` picks onsets from
`[freeze .. end]`. Filtering a whole-clip selection down to the last 3 seconds
does not work: the fraction has already been spent on the body, which left 3
flickers stacked at 30.5s and the freeze's opening 2.3s dead.

**The window is measured against the OUTPUT length, not `dur`.** `dur` is the
body; the freeze clones frames past it. Clamping against `dur` produced a 0.35s
window holding zero beats — the effects would have disappeared rather than moved,
and that failure looks identical to success if the only check is "the body is
clean".

**`FLASH_WINDOW_FRACTION`, separate from `FLASH_BEAT_FRACTION`.** 12% of a whole
clip's 63 onsets is 8 hits; the 3s freeze holds 6 onsets and 12% of those is ONE.
Measured on this track's window: 0.30 gives 2 bursts, 0.50 gives 3 evenly spread
with a 1.11s longest gap.

**The flicker and the slam moved BELOW the outro filters.** The freeze is a
`loop`, and it clones whatever frame it is handed — including a flickering one.
Probed in real ffmpeg on a synthetic clip: the same expression produced 0 events
inside the freeze above the loop and 10 below it. The outro's own brightness ramp
stays above, because it describes what the ending does to the footage rather than
a hit on the held frame, so the two terms are no longer concatenated.

### The slam rule was backwards

It read "keep slams out of the frozen ending" — which is precisely what left the
body shaking for 26s and the ending perfectly still. Throwing a held frame is the
point: the picture stops, the framing keeps hitting the beat.

### Delivered file, frame by frame

```
body (0 .. 28.20s)        0 flickers
                          4 luminance steps, all b-roll cuts: they move and
                          STAY, while a flicker returns within 0.08s
freeze (28.20 .. 31.20)   9 flickers in 3 bursts + 2 slams
first hit                 0.25s into the freeze
longest gap               1.11s
                          1080x1920, 31.20s
```

### Verification

`_v53` is new. 51 ok, with `_v9`/`_v10` still failing on a deleted transcript.

Negative control: selecting over the whole clip puts 21 flickers in the body;
with the window, 0.

Signed: Dalmislave

## fab7671 — the freeze keeps the music, and the effects burst instead of drip

Two operator reports on one delivered render: "frame freeze ga ada suara
videonya lagi jedag jedug" and "kenapa editannya sepanjang ada lagu? sampah".

### The ending had no sound

Three walls stacked, each hiding the next:

1. `total = dur + intro_dur` did not know the jamet freeze EXTENDS the clip, so
   the audio fade was computed for 28.55s of a 31.20s file.
2. amix ran `duration=first`, ending the mix when the speech track ended.
3. the BGM input itself was cut with `-t dur + intro_dur`.

Fixing only the filter graph left the file silent anyway — measured -99 dB from
29.0s while the stream still reported 31.21s. `-t` on an input is a hard cut and
no downstream `apad` brings back seconds that were never decoded.
`_outro_output_len()` now reads the true output length out of the filter list
the renderer actually uses, and the BGM input, pad, trim and fade all take it
from there.

### The effects ran under the whole song

Picking the N loudest onsets spreads them by construction, because a track's
loudest hits are spaced across it: 13 flickers every ~1.8s covering 84% of the
clip.

Measured on the reference tutorial (21 flickers over 19.9s):

```
median spacing    0.10s
intervals <0.8s   16/20  (80%)
longest quiet     4.45s
```

0.10s is tighter than the song's closest two onsets (0.252s). The reference is
not flickering once per beat — it flickers several times inside one.
`_burst_times()` does that now: the beats still come from the music, only the
sub-division is ours.

Three attempts that could not reach it, each measured rather than reasoned
about: grabbing neighbouring onsets (0.53s median — the song's own spacing),
widening the burst (second quarter empty for 15.7s while the song had 8 onsets
in it), slicing the picked list (`[:keep+per]` cuts from the front of a
time-ordered list and deleted the last burst outright).

Delivered file, measured in pixels:

```
                  ours     reference
events/s          1.28     1.05
median spacing    0.05s    0.10s
intervals <0.8s   79%      80%
longest quiet     3.95s    4.45s
bursts            8
quarters          all populated
```

### Two knock-on effects

The onset gate had to drop from 0.35s to 0.18s: at 0.35s the song's 63 onsets
became 43 with a 0.53s median, so a burst was unexpressible before any selection
ran. That raised every downstream fraction — slams went from the approved
0.76/s to 1.02/s, 29 throws against 21 flickers, the heavy effect outnumbering
the light one. `SLAM_BEAT_FRACTION` 0.60 -> 0.40 restores 0.74/s.

`_v49` measured BPM on the SELECTED flickers. Bursts sit a sixteenth apart by
design, so it reported 218 BPM — the reference tutorial would read 600 by the
same arithmetic. It now measures the onset stream (116 BPM) and checks those
onsets land on the track's own grid, which is the property it was standing in
for.

### Verification

`_v52` is new; `_v49`, `_v50` and `_v43` were corrected. 50 ok, with `_v9`/`_v10`
still failing on a deleted transcript file.

Negative control: cutting the BGM input back to the segment length leaves 5 of 6
half-second chunks of the freeze digitally silent; with the fix, 0 of 6.

Signed: Dalmislave

## Captions that hold, an ending that waits for the sentence

Two operator reports on the same render: "kenapa masi ada subtitlenya
dikit-dikit ya?" and "nanti selesai dari si gibran suruh bawa kotak makan,
langsung jedag jedug ... jadi durasi videonya jg engga kependekan".

Same shape behind both: a boundary computed from a count instead of from the
speech.

### Captions covered 64% of the clip

Each phrase's last word ended on its own `end`, so every pause between phrases
blanked the caption lane. Measured on the delivered file:

```
coverage          64.2%
gaps > 0.3s          12, totalling 10.12s
two biggest       2.84s and 1.80s -- with 13 words BEING SPOKEN inside them
```

The last word of a phrase now holds until the next phrase begins, capped by
`CAPTION_HOLD_MAX` (1.2s) so a genuine silence still clears the lane.

```
coverage      64.2% -> 91.7%
leftover gaps    12 -> 2, both verified silent in the transcript
```

### The clip carried 3.3s of someone else's sentence

`snap_to_speech_end` only accepted silences of 1.2s or more. After the payoff
("...yang dimasak ikut") the breath was 0.62s, and the next qualifying silence
was 3.3s later — so "tapi dua perempuan rekomisasi apa itu?" rode along.

A shorter pause now also ends the clip, but only when NOTHING AFTER IT matches
the clip's own keywords. Punctuation cannot be the guard here: this transcript
marks no full stop at "ikut", and gap size does not separate the cases either
(0.62s after the payoff against 0.52s mid-sentence elsewhere).

```
31.81s -> 28.55s, ending on "...yang dimasak ikut"
```

### The freeze landed on the payoff line

`_outro_start` computed `dur - span`, which put the freeze at 23.81s while
"anaknya membawa kotak dari rumah ... yang dimasak" ran to 27.94s. The line the
clip exists for played under a frozen frame with its captions suppressed.
`_outro_snap()` moves the ending to where speech actually stops.

### And then the freeze was 0.35s long

Snapping leaves only 0.35s of clip behind the sentence, so `freeze_secs = dur -
start` produced a 0.35s still and `trim=end=dur` cut it back to that. The jamet
freeze now takes `OUTRO_JAMET_SECONDS` as a floor and trims to
`start + freeze_secs`, so it EXTENDS the output instead of fitting inside the
remainder.

```
body 28.55s -> file 31.20s, freeze 3.00s
```

### Two wrong turns, both caught by measuring

Extending the segment by the outro span to "make room" pulled the aside back in
(28.55s -> 31.55s) and played it UNDER the freeze. The freeze needs no source
footage at all: `loop` clones the frame at the cut and the encoder's `-t` drops
the real tail.

Searching backwards for the last pause that leaves `span` of room picked 18.86s
on a 28.55s clip — a pause in the middle of the dialogue, which is the opposite
of the fix.

### Verified

`jobs/clip_1791296210_122.mp4`, 31.20s, 1080x1920, md5 differs from the
previous render:

```
freeze starts     28.20s   (speech ends 28.20s)
_freeze_floor       0.0    (moving video reads 2.09-2.70)
captions          91.7%    (was 64.2)
```

`tests/_v51.py` pins all four properties and pushes the ending through real
ffmpeg, because a test asserting on a filter string passes while ffmpeg refuses
the graph.

`_v43` asserted on a CALL STRING (`_outro_start(dur, mood=mood)`) and failed the
moment the signature grew a `words=` argument, while the behaviour it guards was
untouched. It now checks the behaviour. Suite: 49 ok; `_v9`/`_v10` still need
the deleted `media/uf9833efdc72b/PPOKdwOCMLA.words.json`.

-- Dalmislave

## v0.8.0 — the shake travelled further than the reference and still felt like a tremor

Operator: "goyangnya jgn kayak geter" tapi goyang aga jauh gitu, kayak bantingan
bantingan agak jauh sesuai beatnya."

Measured with vidstabdetect, median local-motion vector per frame at 1080 wide:

```
                  moving >8px     peak
reference            10.6%       81.1 px
our outro shake      36.7%      144.5 px
```

The old shake travels **further** than the reference and still reads as a
vibration. Amplitude was never the problem. `OUTRO_SHAKE_HZ` is a continuous
sine, so the picture is never at rest — and "always moving a bit" is the
definition of a tremor. A slam is rare, far, then still.

`_slam_offsets()` throws the frame once per beat, sharp attack, fast decay,
static in between. Direction rotates through eight vectors rather than
alternating on one axis: left/right-only at beat spacing is exactly what a shake
looks like.

Probed through real ffmpeg + vidstabdetect:

```
30px/0.18s -> moving 15.3%, peak  77.5 px      frac 0.22 -> 0.25 slams/s, 2.5%
50px/0.18s -> moving 18.7%, peak 130.2 px      frac 0.40 -> 0.42 slams/s, 3.9%
70px/0.18s -> moving 20.0%, peak 185.4 px      frac 0.60 -> 0.58 slams/s, 6.4%
```

Four things that would have broken it silently:

- **pad then crop back** by the same margin. The frame needs somewhere to travel
  into, or a throw just exposes the canvas edge. Output stays 1080x1920 and
  `_v50` asserts it.
- **Slams are kept out of the frozen ending.** The freeze exists so the last
  seconds hold still; animating it would undo last release's fix.
- **Same onsets as the flicker**, so picture and track mark the same time.
- **Wired into the `pillar` branch** — the one we actually render. Last release
  the flicker went into `cover` only and shipped a byte-identical file.

Delivered render (md5 `2e63de4bf10e`): 18 slams in a 23.8s body, 0.76/s.
Measured at the slam timestamps against the frames between them: **16.3px mean
inside vs 8.2px outside** — a throw travels 2.0x the clip's own motion. 31.81s,
1080x1920, freeze still holding to the last frame.

Tests: 48 ok. `_v50` pins travel (peak > 50px) **and** stillness (moving < 20%),
the second being where the old shake failed at 36.7%. `CLIPPER_SLAM_PX=8` makes
it fail with "20.6px, not a tremor", so it rejects a vibration rather than
merely measuring one. `_v9`/`_v10` still fail on a missing fixture, unrelated.

— Dalmislave

## v0.7.9 — the flicker was measuring the wrong thing entirely

Operator: "efeknya kurang rusuh, guide jedag jedug nya gimana sih? di bedain
exposurenya di goyang goyangin ikutin beat lagu walau agak extream."

Every measurement in this project so far looked at **motion**
(frame-difference). Motion cannot see an exposure change. Measuring raw
brightness on the reference showed what was actually missing:

```
                brightness sd   largest jump   flickers/s   bright/dark
reference            30.6           38.2          0.50        11 / 10
ours                 13.9           16.2          0.17         6 /  5
```

And 16 of the reference's 21 flickers sit within 0.3s of a musical onset. Ours
fired on stressed **words**, so the picture and the track marked different time.

Four fixes, each from a number:

- `FLASH` defaulted to **0**. The mechanism was already correct — it was off,
  and capped at 3, which cannot express 21 flickers in 13.5s.
- **Bright-only -> alternating.** The dark half is what reads as exposure being
  pushed around rather than a camera flash going off.
- **Words -> the track.** `_music_beats()` reads RMS onsets from the BGM: rises
  over 6 dB, 0.35s apart, median 0.528s = 113.6 BPM on the hype track. A 3 dB
  gate catches half-beats and reports 237. It returns real measurements or
  nothing; a synthetic BPM grid drifts against the music within a few bars.
- **Amount 0.35 -> 0.18.** Probed on flat grey through real ffmpeg: 0.12 -> 27,
  0.18 -> 40, 0.25 -> 58, 0.35 -> 81. And `FLASH_BEAT_FRACTION=0.35` keeps the
  loudest third: all beats measured 1.01 events/s on a delivered render, half
  gave 0.88, a third gives **0.50** — the reference's rate.

**The expensive bug.** The flicker was only wired into the `cover` branch, so a
pillar render carried none of it. Turning it on produced a byte-identical file
(md5 `f9ef2d296484` twice) — which is the only reason it was caught. A value
with two independent call sites is read twice; checking the one you edited is
not evidence.

Delivered render (md5 `bc2fd50bfdf1`): 15 flicker terms, 7 dark, largest
brightness jump **39.68** against the reference's 38.17. 31.81s, 1080x1920,
freeze still holding to the last frame.

Tests: 47 ok. `_v49` pins the rate, both directions, and the peak on a **flat
grey** source — `testsrc2` reads a 124-point jump on its own and measures
nothing, which an earlier version of this probe fell for and reported the
control as the strongest flash in the sweep. It carries a negative control and
a check that an unreadable track yields no beats rather than a grid.
`_v9`/`_v10` still fail on a missing fixture, unrelated.

— Dalmislave

## v0.7.8 — the freeze stopped early, and the gate that watched it was blind

Operator: "harusnya videonya pause sampe akhir."

Two bugs. The second is why the first shipped.

**The freeze ran out before the clip did.** `OUTRO_FREEZE` was a fixed 2.0s
while the jamet ending runs 3.0s. And `loop` **inserts** its clones, so the real
tail follows them instead of being replaced — cloning more frames made the clip
*longer* (31.81s -> 34.83s) and the footage still resumed. Measured on that
render: motion 4-17 after 31.8s with no per-beat decay, against 0.39-0.87 inside
the frozen stretch.

Fix: `freeze_secs = max(OUTRO_FREEZE, dur - start)` covers the whole ending, and
`trim=end=dur` drops the displaced tail. The shake window follows `freeze_secs`
too, or the last second of the still sits motionless.

**The edit gate said PASS on that file.** Its check was "outro = 'jamet', last
3s" — it confirmed the setting it had just chosen and never looked at the
render. The operator found the moving tail; the gate could not.

`job._freeze_floor()` now probes the delivered file. The discriminating number
is the motion **floor**, not the mean: a shaking still returns to ~0 between
beats, moving video never does, and their means are too close to separate.
Verified on the broken render itself — frozen 0.39, resumed tail 2.09, threshold
1.5.

A trap worth recording: `metadata=print` writes to ffmpeg's **log**, which
`-v error` suppresses. The first probe parsed an empty stderr and returned
"could not measure" on a perfectly good file. It writes to `file=` now.

Delivered render (md5 `f9ef2d296484`): 31.81s again, and the still holds to the
last frame — each beat spikes to 21.4 and decays to 0.85 through 31.7s. Gate:
"floor 0.39 | frozen through the last 3s". 1080x1920 unchanged.

`_v36` and `_v40` pinned the old behaviour and were corrected, not deleted:
`_v36` asserted the clip **grew** by `OUTRO_FREEZE` (that growth was the bug),
`_v40` pinned the freeze to the constant rather than to the ending's length.

Tests: 46 ok. `_v48` is new, renders through real ffmpeg, and carries a negative
control — the same probe must read above threshold on moving video or it guards
nothing. It fails on clean HEAD with the original symptom ("freeze is 2.00s but
the ending is 3.00s"), verified with git stash. `_v9`/`_v10` still fail on a
missing fixture, unrelated.

— Dalmislave

## v0.7.7 — the effects were on a timer, the reference is in bursts

Operator: "Sumpah aneh, efeknya kurang sebelum jedag jedug, coba research dulu
deh, cek lagi tutorial dia gimana buatnya."

So the reference (`AGv6G13TPUc`) got measured instead of remembered.
Frame-difference motion per second, body of clip only:

| | mean | peak | peaks/s |
|---|---|---|---|
| reference | 18.4 | 70.6 | 0.81 |
| ours, before | 10.7 | 34.6 | 0.21 |

**The shape was the finding, not the mean.** The reference's hits come in
bursts of 1-3 inside ~0.6s, then a 2-4s gap — five bursts across 13.5s, sizes
[3,2,1,3,2]. A flat 9s `PUNCH_MIN_GAP` cannot express that: on the 31.8s clip
there were 27 qualifying beats and it kept **3**, with nothing before t=4.7s,
which is the stretch the operator was pointing at.

`_punch_times` now carries two gaps — a beat within `PUNCH_BURST_GAP` (0.75s)
joins an existing burst up to `PUNCH_BURST` (3), and a new burst needs
`PUNCH_MIN_GAP` (2.7s, was 9) of clear air. The quiet is deliberate.

Depth and hold measured on real ffmpeg renders (testsrc2, 2.34 control):

| amount | motion | | hold | motion |
|---|---|---|---|---|
| 0.06 | 4.34 | | 0.90s | 5.87 |
| 0.10 | 5.87 | | 0.45s | 7.84 |
| 0.18 | 7.37 | | 0.30s | 8.45 |

Depth saturates past 0.10 and the hold is the bigger lever, so amount
0.06 -> 0.10, hold 0.9 -> 0.45s (0.30s reads as a glitch). `PUNCH_MAX` 8 -> 16,
since a cap of 8 spends itself on isolated hits before any burst can form.

Delivered file (md5 `daded051b085`): body mean 10.74 -> 11.71, peak
34.57 -> 38.24, peaks/s 0.21 -> 0.38, **12 of 14** punches visible above local
baseline, first at t=1.2s. Overlapping punches peak at 12.5% zoom, under the
22% that would crop the frame.

**Not chased:** the reference's 18.4 mean. It is a CapCut tutorial shaking a
static graphic; this is a press scrum where the footage already moves, and the
pillar card skips the base zoom on purpose so the news banner is not sliced
(verified in code, not assumed). Matching that number would mean inventing
movement.

Tests: 45 ok.

— Dalmislave

## v0.7.6 — panning on, shake stays on the frozen ending

Operator: "A, jedag jedugnya baru goyang goyang, di freeze frame gibran dan
video, terus jedag jedug kayak tutorial yg gw kasih."

The crop now follows the subject, and the only other movement is the
jedag-jedug on the frozen last frame. `CLIPPER_PAN=0 -> 1`, with the reason
written next to it in `.env`.

| crop | subject framed |
|---|---|
| centred | 36% |
| best static | 38% |
| panning | 100% (6 keyframes, 0.6s ramps) |

Static could never win here: the subject walks 0.52 of the frame width against
a 0.42-wide window. The previous static render still showed a bystander in the
closing third.

Verified on the delivered file rather than a rebuilt graph — pan has 6
keyframes with 0.6s ramps, freeze is `loop=60` from frame 864 (28.80s), shake
runs from 28.810 at period 0.520s = **1.92 hits/s** against the 2.00 measured
from the operator's reference. Frames at t=2/14/26/29.5 all show the subject.

`_v46` pins both halves: the shake must not begin before the freeze, and the
pan must stay enabled and actually move.

**Two bugs found, both in the new test, not the renderer.** `mood="hype"`
selects the STINGER ending — `_outro_kind` never returns "jamet" from "auto",
because freezing and shaking a frame is a stylistic claim the operator makes
per clip. The first version asserted on the stinger's 4.00 hits/s and reported
it as the jamet shake being twice the reference; the renders were correct all
along. The jamet chain also comes back in the SECOND element of
`_outro_filters`' tuple, so checking only the first found no freeze in an
ending that has one.

Tests: 44 ok.

— Dalmislave

## v0.7.5 — the crop was pointed at the wrong person

Operator: "Salah muka woi harusnya kan gibran."

**A centred crop is a framing decision, not a neutral default.** The pillar
card scales a 16:9 source to 2560 wide and keeps a 1080 crop — 42% of the
width. `_pillar_pan_x` returned a centred window whenever PAN was off, before
it ever looked at a face, and PAN is off in `.env` by the operator's own choice
("user finds the movement distracting").

Centre covers source x 0.29-0.71. The subject sat around 0.74, so he was
outside the rendered frame for 55% of the clip. The render framed an escort
officer and a bystander.

With PAN off the window is now **placed once and still does not move**, scored
by how centred the subject is rather than merely whether he is inside — every
containing position ties, so a subject at 0.74 had accepted a window at 0.53.

| window | subject inside middle 60% |
|---|---|
| centred | 36% |
| placed (0.67) | 38% |
| PAN on | 100% (7 keyframes) |

**Placement is a marginal gain, not a fix.** The subject travels 0.52 of the
frame width against a 0.42-wide window, so no static position can hold him — a
render with the static window still shows the wrong person in the closing
third, checked frame by frame. The real choice is still-at-38% or panning-at-
100%, and that is the operator's call; `.env` stays `CLIPPER_PAN=0`.

**Subject tracking** in `_sample_pan_faces` now uses appearance (coarse HS
histogram) with position and area, instead of largest-face-per-frame: 0.079
mean error against 0.094 on five hand-checked positions, and it carries
identity across frames where the subject is not detected at all.

**Correction to v0.7.4's reasoning.** Three ground-truth points made that look
like 0.344 vs 0.110, and the new test asserted a large improvement on it. Two
further checked frames (t=132 at cx 0.78, t=150 at 0.36) cut the gap to 0.094
vs 0.079 and the assertion failed in the suite. Three points were not a
measurement — they were a story that fitted. The test now asserts
no-regression and records the reversal; the docstrings carrying 0.344 are
corrected.

Tests: 43 ok.

— Dalmislave

## v0.7.4 — the ending stopped fighting the captions

**Subtitles kept animating on the frozen frame.** Operator: "kenapa
subtitlenya masih jalan?"

The jamet ending holds one frame and shakes it. Overlay windows come from the
transcript and knew nothing about that: 6 of 21 caption tiles ran past the
freeze point at 7.80s, the last to 10.46s. Moving text on a still picture
cancels the whole point of freezing it.

New `_outro_start()` mirrors the span logic in `_outro_filters` — including the
`dur < span*3` cutoff, so a clip with no ending gets no clamp — and the caption
chain clamps every window to it.

**The clip could not open before its own point.** 12.8s, of which 3.06s (24%)
was ending. Snapping to the first usable silence is right when `--start` sits
on the sentence, but it leaves no room for build-up.

Opening at 122.0 to include the apology exposed the real flaw. Three
position-based rules, all wrong:

| rule | result |
|---|---|
| first usable silence | 14.7s, ends BEFORE the lunch-box line |
| last keyword in range | 42.3s, follows "anak" into a passage 17s later |
| first contiguous keyword run | 14.7s, stops on "anak" at 128.16 |

**Keyword density per run of speech** separates them. Gibran's sentence holds
four distinct keys (anak, kota, rumah, dimasak); the apology before and the
passage after hold one each. Density also survives the raw transcript, which
still carries the mishearings the glossary fixes later — "kota" for "kotak".
Requiring a specific noun would have missed; four approximate keys did not.

Filler words are excluded. Passing the whole context line was worse than having
no floor at all: "yang", "dari" and "saat" are in every Indonesian sentence, so
the floor followed filler and a 143.0 start stretched to 42s.

`--start 122.0` now gives 31.81s ending on the sentence, ending at 9% of the
clip instead of 24%.

Tests: 41 ok. `_v43` checks `_outro_start` agrees with `_outro_filters` across
five durations, that opening earlier still ends on the same sentence, that a
tail passage reusing a keyword is not followed, and that filler-only keys
behave as no keys at all.

— Dalmislave

## v0.7.3 — captions stopped losing words

**The clip did not contain the line it was built around.** Operator: "Mana
gibran ngomong kasih bekal?"

`_editorial_layer` laid caption tiles with `if cx + t.width > block_w: break` —
anything past the line budget was discarded. `emphasis.py` uppercases stressed
words, and "kotak" scored 1.43 against a 1.15 threshold, so the line grew to
`-anaknya MEMBAWA KOTAK` = 1003px against a 943px limit. "kotak" never reached
a frame.

The widening came from the emphasis pass, the drop from the layout pass.
Neither logged anything, because dropping a tile was not an error in that
function: `warnings: []`, every gate green, word gone. Overflow now wraps to a
second row.

Reproducing it required the full input. Rendering the layer without
`accent_words` produced a different, *correct* 800px tile — the bug was
invisible without the emphasis scores. Only with them did the png match the
shipped one byte for byte (md5 `0ef9c42bf0`).

**`--end-at-sentence`.** The clip ran 22s on a 6.5s sentence, then rolled
through an unrelated aside and crowd noise. `--start` plus `--seconds` makes
the operator guess how long a thought lasts; the transcript already knows.
22.0s -> 10.8s, ending where speech stops.

It takes the first silence that still leaves a usable clip, not simply the
first silence: `--start` is set by eye, so a segment often opens on the tail of
the previous sentence. It refuses rather than hand back a segment too short for
the ending, since `_outro_filters` silently returns nothing below 3x its span.

**Shake density, measured not guessed.** Operator: "Getarannya terlalu gitu
itu." His reference (youtube `AGv6G13TPUc`, 30-34s) runs 8 hits in 4.0s =
2.00/s. Ours ran 5.77/s, because `OUTRO_PUNCH_PER_BEAT=3` was tuned against a
*different* reference short. Now 1 hit/beat = 1.92/s, measured at 2.27/s in the
delivered file.

`OUTRO_PUNCH_DECAY` had to move with it (2 -> 6). The envelope is
`exp(-DECAY*phase)` with phase spanning one beat, so keeping DECAY=2 at the
slower rate stretches each hit from 0.087s to 0.260s — a drift, not a punch.
Two coupled constants, one of them invisible in isolation.

**The transcript was already right.** `glossary.json` had all four fixes
(`titik->titip`, `kota->kotak`, `ikut->ibu`, `rekomisasi->rekomendasi`) and all
four applied; the shipped caption read "TITIP" correctly. The missing word was
a layout bug, not a transcription one.

Tests: 40 ok. `_v41` covers the snap and the shake density, `_v42` renders the
real caption layer and asserts the wrap. `_v9`/`_v10` still fail on a fixture
that was never committed.

— Dalmislave

# Clipper — Release Notes

## v0.7.3 — the jamet freeze shook the wrong thing

Reference: [AGv6G13TPUc](https://www.youtube.com/watch?v=AGv6G13TPUc) at 30-34s,
a CapCut *"jedag jedug zoom x out"* tutorial. Operator's spec:

> selesai itu jeda 2 detik jedag jedug, lu liat kan itu videonya dah ga di play,
> jadi image gitu

The picture **stops**, and the beats land on the still.

### What shipped did the opposite

`loop` inserts N copies of one frame at `start`, so the still occupies
`start .. start+freeze` on the **output** timeline. The shake window opened at
`start + OUTRO_FREEZE` — exactly where the still ends and moving video resumes.

So: the clip froze, sat there motionless for half a second, then started
shaking once it was playing again. Both halves existed; only the arithmetic
relating the two timelines was wrong, which is why the filter graph read as
correct.

```
shake_from = start            (was: start + OUTRO_FREEZE)
OUTRO_FREEZE = 2.0            (was: 0.5)
```

### Verifying it needed a different measurement

The shake translates the frame, so a plain frame-difference reads motion right
through the ending — broken and fixed score the same. `tests/tools/freeze_probe.py`
compensates for the translation (search a small offset range, keep the best
match). Only then is the freeze visible:

```
moving video  6.0 vs 7.3    aligned diff 25.83
moving video  6.0 vs 6.3    aligned diff 17.34
frozen       19.2 vs 20.9   aligned diff  5.21
frozen       19.2 vs 20.0   aligned diff  4.84
```

### _v36 had encoded the bug

It asserted `frozen < 1.0` at the start of the ending — which only holds while
the shake begins *after* the still. A test written against broken behaviour
passes forever and blocks the fix. It now checks the shake's amplitude and that
the clip grew by the hold, since `loop` inserts real frames (22.0 -> 24.0s).

`_v40` is new: the loop and the shake must describe the same stretch of
timeline, and the still must not be motionless.

### Tests

38 ok. `_v9`/`_v10` unchanged (missing fixture).

— Dalmislave

## v0.7.2 — pillar was mostly blur; footage now fills 75% of the height

Operator's verdict on v0.7.1: **"jelek banget"**, **"efeknya juga ampun"**, with
an instruction to get the footage back to at least 75%. Measured, both were
right:

```
card 1080x608 in a 1080x1920 canvas
  footage  32% of screen
  blur     68% of screen
  head    ~13% of canvas height   <- thumbnail on a phone
```

### The fix inverts the trade-off

The card is now scaled by canvas **height** (`PILLAR_COVER=0.75`) instead of
stretched to canvas width. A 16:9 source at 1440px tall is 2560 wide, so only
42% of the source width survives the 1080 crop — the borrowed chyron **cannot**
stay intact at this size.

That is a real choice, not a regression: the banner is the broadcaster's
furniture, the face is the clip. The subject wins.

Because *which* 42% now matters, `_pillar_pan_x` reuses the existing face
sampling and keyframe smoothing to follow the speaker rather than keeping the
middle. On this source the window tracks `0.33 -> 0.45` across the segment.

### Caption was touching the source banner

The 206px editorial block at the 0.62 default lands at 1190-1396. The card's
geometry puts the source banner at 1377 — a 19px overlap, reviewed on a
delivered frame as *"practically touching... the eye has to work to separate
your caption from the broadcaster's headline"*.

`EDIT_Y_FRAC_PILLAR=0.56` clears it by 96px. Captions stay **on the footage**
rather than moving into the blurred band below the card, where they would read
as a sticker stuck over the clip.

### Verified on frames, not on the graph

| | v0.7.1 | v0.7.2 |
|---|---|---|
| footage | 32% | **75%** |
| blur | 68% | **25%** |
| caption to banner | 19px overlap | **96px clear** |
| subject | thumbnail | large, inside crop |

1080x1920 unchanged. md5 differs from the previous render — the check that
caught the no-op fix in v0.7.1.

`_v39` now asserts the card covers at least 60% of canvas height, blur stays
under 40%, the pan expression is a real crop position, the caption block ends
above the banner, and the call site passes the pillar value rather than the
default.

### Tests

37 ok. `_v9`/`_v10` unchanged (missing fixture, fails on clean HEAD).

— Dalmislave

## v0.7.1 — pillar was cropping twice, and the agents got their skills

### pillar framing never actually applied

Three bugs stacked, all invisible from the code:

1. `_zoompan` read the module-level `FRAME_MODE` — the `.env` default
   (`cover`). `--frame-mode` travels as a function argument, so the standing
   `CLIPPER_ZOOM=1.2` breath stayed on top of the finished pillar card.
2. pillar fell through to the `fill` else-branch, which crops the composed
   frame to canvas width. A second crop of an already-correct frame.
3. The shared `[bg][mn]` overlay ran for pillar, which never makes those
   labels.

What proved it: two consecutive "fixed" renders came out **byte-for-byte
identical** (`md5 e1ab71f8`). The `graph.txt` still carried
`z='1+0.1000-0.1000*cos(...)'`.

| | banner | face |
|---|---|---|
| before | `...RAL GIBRAN ... DARI RUM...` | clipped |
| after | `VIRAL GIBRAN ... DARI RUMAH` | whole |

1080x1920 unchanged. Jamet punch still measures 20.8 peak motion in the
closing seconds; the near-zero readings at 18.8-19.0s are `OUTRO_FREEZE=0.5`,
the deliberate hold before the hit.

`_v39` covers all three and deliberately leaves `edit.FRAME_MODE` at `cover`
while passing `pillar` as an argument — the first version of the test set the
constant and passed while the renderer stayed broken.

### Agents carry skills now

`agent_skills.py` maps each reviewing agent to skills matching its job
description, from the two repos supplied: `obra/superpowers` and
`garrytan/gstack` (78 skills total).

| gate | agent | skills |
|---|---|---|
| sourcing | Evidence Collector | verification-before-completion, qa-only |
| footage | Evidence Collector | verification-before-completion, systematic-debugging |
| copy | TikTok Strategist | brainstorming |
| language | Indonesian Transcript Linguist | systematic-debugging, verification-before-completion |
| sound | Focus Music Architect | *(none)* |
| edit | Short-Video Editing Coach | design-review, verification-before-completion |

Name, one-line description and on-disk path reach the prompt — not the body.
`gstack/qa-only/SKILL.md` is 45KB and would bury the technical contract that
took this long to get right. Descriptions are read from each `SKILL.md` at run
time, like the agent names.

The `sound` gate has **no skills on purpose**. Neither repo has anything on
audio or music selection, and padding it with a near-miss would repeat the
invented-mapping mistake that produced the fabricated division labels.

### RTK

`rtk-ai/rtk` 0.51.0 installed with its official Hermes hook (SHA256 verified
against `checksums.txt`). The awareness block is appended verbatim to
`clipper/CLAUDE.md` and `athena-clip/AGENTS.md` under the same
`<!-- rtk-instructions v2 -->` markers `rtk init` uses, so it upserts instead
of duplicating.

Measured on this repo:

```
git log -5   10125 B -> 1614 B   84% saved
git status     769 B ->  393 B   49% saved
ls             733 B ->  927 B   26% WORSE
cat job.py (57KB)              unchanged
```

The plugin is fail-open: no `rtk` on PATH, or a non-zero exit, and Hermes runs
the original command.

### Tests

37 ok. `_v9`/`_v10` still fail on the missing
`media/uf9833efdc72b/PPOKdwOCMLA.words.json` fixture — confirmed failing on
clean HEAD via `git stash`, unrelated to this work.

— Dalmislave

**v0.7.0 "the reviewer named in the log is the reviewer that ran"** · branch `claude/code-clipper-review-v9e3im`
new: `agents.py`, `audit_watch.py`, `tests/_v33`–`_v38`

_Dalmislave_

---

The operator asked to see the agents working: "gw mau lihat progress dan
decision semua agent, apa yg lu kasih ke agent2 kita dan hasilnya gimana".
He pointed a Discord channel at it and the channel stayed empty. Two separate
reasons, both of them mine.

**The ledger was never written anywhere.** `audit.py` built the whole review
every render — six divisions, each with the brief it was handed and the
verdicts it returned — then printed it to stdout and dropped it. Nothing had
ever saved it, so nothing could deliver it. What I had been showing him came
from my own terminal.

`Ledger.save()` now writes `<clip>.audit.json` and `.audit.txt` next to every
render, and `audit_watch.py` posts the ones it has not reported yet, with the
same dedupe shape as `campaign_watch.py`. A ledger that cannot be written
appends a warning instead of losing the clip.

**The agents were named but never consulted.** This is the worse half. The
ledger printed `agent: TikTok Strategist` while the prompt that actually went
to the model was a hand-written `SYSTEM` string in `metadata.py`. The division
labels were invented too — "RESEARCH" for footage, "DESIGN" for sound. The
agency-agents repo declares its divisions in `divisions.json` (18 of them,
with CI that fails when the list disagrees with the directories on disk), and
neither label is in it. `RESEARCH` holds one agent, a synthesist. `DESIGN`
holds ten UI/UX agents and no audio.

He caught it in one line: "kenapa buat2 sendiri, gw mau semuanya rapi ya".

| gate | was | is | file |
| --- | --- | --- | --- |
| sourcing | RESEARCH (invented) | TESTING · Evidence Collector | upstream |
| footage | RESEARCH (invented) | TESTING · Evidence Collector | upstream |
| copy | MARKETING | MARKETING · TikTok Strategist | upstream |
| language | SPECIALIZED | SPECIALIZED · Indonesian Transcript Linguist | **ours** |
| sound | DESIGN (invented) | SPECIALIZED · Focus Music Architect | upstream |
| edit | ENGINEERING | MARKETING · Short-Video Editing Coach | upstream |

Five of six are upstream files, unmodified; `git status` on that repo shows
exactly one untracked file, the Indonesian linguist. It exists because the
repo's `specialized/language-translator.md` is Spanish ↔ English and this work
is not translation — source and target are both Indonesian, and what gets
repaired is Whisper mishearing. `_v37` asserts the language gate never points
at the translator.

`agents.py` now loads each agent's Identity / Core Mission / Critical Rules
and puts it in front of the technical prompt, with a line declaring the
Clipper half binding. The merge direction was the operator's call: persona
from the `.md`, format and limits from the code. A wholesale swap would have
lost the constraints that took a dozen renders to find — the character caps,
the banned-filler list, the no-invented-numbers rule — because these files are
written for general-purpose coding agents and know nothing about 9:16 output.

Heading layout is not consistent across the repo. `tiktok-strategist` opens
`## Critical Rules` straight into a `###` subheading, which a naive scan
returns as empty; `evidence-collector` has no mission section at all. The
extractor stops only at a heading of the same depth or shallower, and requires
no section.

`_v38` intercepts `ai.chat_json` and asserts on what the model would actually
receive. It caught a real bug on the first run: `metadata.SYSTEM` opened with
"You are a viral short-form video strategist", so the merged prompt carried two
competing identities. Two of its earlier assertions were wrong in my favour —
looking for `maksimal 90 karakter` and a JSON contract in the system message
when both live in the user message — and both were fixed in the test rather
than worked around in `agents.py`.

### Two named clip types

`--clip-type sedih|jamet` sets mood, outro and b-roll together. Every
register mismatch the operator has caught had the same shape: three layers
disagreeing about what the clip was about. A heroic anthem over people being
bombed. A flash stinger at a funeral. `auto` cannot select `jamet` — a
jedag-jedug shake on a grief clip is not a style, it is an error.

The jamet ending went missing twice. First the shared 24s guard
(`3 × OUTRO_SECONDS`) rejected a 22s clip, because I had given the instant
freeze-and-shake the span budget of an eight-second melancholy ramp; now
`OUTRO_JAMET_SECONDS = 3.0` with a nine-second guard, melancholy unchanged.
Then I read `edit DID NOT RUN` and reported the outro as missing without
measuring the file — the ledger was wrong, not the render. The ledger only
ever reported cutaways, so "no outro at all" and "outro applied perfectly"
printed identically. The outro now reports a verdict, and too-short reports a
warning.

The shake itself was wrong in shape. A sine spends most of its cycle mid-travel
and reads as a camera bump; the reference short the operator sent spends 40% of
its frames above 6.0 motion. Measured against it with real ffmpeg: median 4.43
vs 4.29, peak 28.1 vs 28.4, hits three times per beat with a sharp decay.

### Framing

A 16:9 source cover-cropped to 1080×1920 keeps 32% of the frame width. Vision
confirmed what that does: the speaker's face cut at both edges, the lower-third
banner sliced in half. `--frame-mode pillar` shows the entire frame over a
pushed-in, darkened, blurred copy of itself — 1080×1920 and 9:16 untouched, as
required. The background needs 1.6× cover scale or the source's own banner
reappears, ghosted, behind the card.

### ffmpeg, again

`crop`'s `w` and `h` are evaluated once when the filter is configured, so they
cannot contain `t` — ffmpeg rejects the whole graph. `x` and `y` can. `zoompan`
accepts a `t`-free expression and then takes over 400 seconds on a 22-second
clip, so the zoom punch goes through `scale` with `eval=frame`. `zoompan`'s
timeline variable is `time`, not `t`, and `between()` works there only with it.

### RTK

Installed from the official release (SHA256 verified against `checksums.txt`)
and wired through `rtk init --agent hermes`, which writes its own plugin and
patches `plugins.enabled`. The plugin fails open: no `rtk` in PATH, or any
error, and the original command runs. Measured here: `git log -5` 10,125 B →
1,614 B, `git status` 769 B → 393 B. `ls` goes **up** 26% in this repo (tree
format, many `temp_subs_*` directories) and a 57 KB Python file is not
compressed at all. The awareness block in `CLAUDE.md` is verbatim from the
repo's `hooks/rtk-awareness-full.md`, with its own markers so `rtk init` can
upsert it later.

### Tests

36 green. `_v9`/`_v10` still fail, and still for the same reason: they need
`media/uf9833efdc72b/PPOKdwOCMLA.words.json`, which was overwritten by a later
render and was never committed. Confirmed against clean HEAD with `git stash`.
Fabricating that fixture would make the suite green and the tests meaningless.

---

**v0.6.1 "a watcher that can say what it could not read"** · branch `claude/code-clipper-review-v9e3im`
new: `campaign_watch.py`, `~/.hermes/scripts/campaign_watch.sh`

_Dalmislave_

---

Standing request, from a while back: watch the clipping marketplaces for
campaigns worth taking — "filter campaign2 yang CPM nya di atas Rp.2500 dan
budget tersisanya 50%" — and report into the channel the operator made for it.

Last time this was blocked on three things. Two are gone:

| then | now |
| --- | --- |
| both marketplaces behind login | konten.com `/api/campaigns` serves 109 campaigns with no auth |
| no channel to report to | operator created one and gave the id |
| Clippo needs a session | **still true** |

So the watcher ships covering konten.com, and **says in every report that
Clippo was not read**, with the HTTP code. A watcher that quietly covers one of
two sources is worse than one that covers neither, because "nothing new" reads
as "I checked everything".

### The budget field had to be measured

The list endpoint has no budget figure — only `budget_bar_percent_override`, a
name that sounds like a display tweak. The real `budget`/`spent` pair lives on
the per-campaign detail endpoint:

```
budget 300.000.000 · spent 246.000.000 → 18,0% left · override says 18
```

8 of 8 campaigns matched within 1.5pp, so the override IS remaining budget and
one cheap list call is enough. `verify_budget_field()` re-runs that check on a
sample every tick and flags the report if it ever stops holding — this is an
undocumented third-party field, and an assumption that silently breaks would
corrupt every number in the report.

### Measured, not assumed

- `urllib` got a blanket **403** from konten.com where `curl` with a browser UA
  got 200. The UA is load-bearing.
- CPM is the **max** across platforms, not the first field present: campaigns
  quote different rates per platform and the operator picks where to post.
- Dedupe verified by running it: first tick reported 32, second tick printed
  **nothing**, and after dropping 3 ids from state the third tick reported
  exactly those 3.
- `--selftest` pins the boundaries that matter — CPM of exactly 2500 does not
  pass "above 2500", 49% does not pass a 50% floor, and `paused` /
  `emergency_stopped` / missing-budget campaigns never qualify.

Runs as `no_agent=true` every 6h, so stdout is the message and silence is the
default. No tokens, and no "still watching" noise.

---

**v0.6.0 "show the brief, not just the verdict"** · branch `claude/code-clipper-review-v9e3im`
6 files · new: `audit.py`, `tests/_v29`–`_v32`

_Dalmislave_

---

## What this release is about

Two things the operator asked for, and one the reviewer caught.

> "Gw mau full log semua agent kita checking" — and then, sharper:
> "apa yg lu kasih ke agent-agent kita dan hasilnya gimana"

The first half shipped as `audit.py`: one ledger, six divisions, every verdict
printed. The second half is what this release adds, because the ledger could
only answer "what did it decide" — never "what was it asked".

That gap hid a real failure. On the Gibran clip the footage gate logged **35
rejects and zero cutaways**, which reads like "no usable footage exists". The
actual cause was the question: the gate was handed the entire `--context` —

```
"Gibran minta maaf ke korban keracunan MBG, menyarankan siswa
 bawa bekal dari rumah yang dimasak ibunya"
```

— fifteen words, and asked whether one news frame showed all of them. Nothing
can. The rejects were correct answers to an impossible question, and the report
showed only the rejects.

### The ledger now records the brief

```
RESEARCH     footage    1 pass · 1 reject
             GIVEN subject = 'korban keracunan MBG'  3 word(s) — from context '...'
             NO   abc @40s  not the action — hospital corridor
             ok   abc @65s  motion 30.3 — collapsed building
MARKETING    copy       0 pass · 0 reject  ← BRIEFED, NO VERDICT
```

Briefs print first, are excluded from the counts (a question is not a verdict),
and a gate that was briefed and then decided nothing is flagged — that is the
`look = ""` shape, where a gate existed, ran, and vetoed nothing for a whole
release behind a clean `warnings: []`.

Wired in: `footage` (subject + act required), `sourcing` (search terms +
candidate count), `copy` (style + mood), `language` (word count), `sound`
(mood + how it was chosen).

### `_clip_topic` keeps the first clause, capped

`--context` is written as "<what happened>, <what was said about it>" and only
the first half is footage-able. Advice is not a frame. Measured:

| context | before | after |
| --- | --- | --- |
| Gibran MBG | 15 words | `korban keracunan MBG` |
| warga Gaza kehilangan rumah akibat serangan Israel | 7 words | unchanged |
| Prabowo membela Palestina … di Gontor | `Palestina` | `Palestina` |

The cap is 7, not 6: at 6 it truncated "…serangan Israel", and that context
genuinely describes footage. `_v27` caught it.

Speaker-action verbs were missing from the stance list, which is why the whole
sentence survived: `minta maaf`, `menyarankan`, `mengimbau`, `mengajak`,
`menjanjikan`, `memastikan`, `menjenguk`, `mengunjungi`, `menemui`.

## The endings

### Longer, layered sad outro

`OUTRO_SECONDS` 5 → 8, plus a vignette and film grain that only ever ramp up —
zero pulses, because the clip is about people being killed. Measured on the
delivered file: Y 138 → 105 across the window, and the three flashes sit at
17.5 / 33.9 / 45.2, all before the outro starts.

### Dip to black — and the reviewer's correction

Shipped as `fade=t=out:st=…:d=1.2:c=black`, placed **last** so slow-motion's
stretch is already in the timeline. Oden measured the delivered file and found
the final frame at **Y=21 — dark grey, not black**: a fade only reaches zero at
`st+d`, and the clip ended exactly there. `OUTRO_FADE_LEAD=0.3` now lands it
early, so there is held black to close on.

Two timelines to keep straight, both documented at the call site: these filters
attach to `[0:v]` **before** the intro is concatenated, so every number is
segment-relative. An 82s segment with a 7s intro delivers 92.4s with the dip at
91.2–92.4. Adding `intro_dur` would push the fade off the end of its own stream.

### `CLIPPER_OUTRO=jamet`

The TikTok edit, by request: freeze the frame, then shake it on the beat.
Measured on the delivered clip — motion 3.5 → **0.006 at the freeze** → 15.3
shaking.

- Freeze uses `loop`, not `setpts`. `setpts` produced duplicate DTS
  ("non monotonically increasing dts to muxer") and dropped frames.
- The shake is a moving **crop**, scaled back to canvas. A zoom pulse changes
  output dimensions per frame, and 1080×1920 does not move to buy a look.
- Never selected by `auto`. A shaking ending on a funeral is not a style
  choice, so `emotional`/`sad`/`reflective` still get the melancholy ending —
  asserted in `_v32`.

### The shake tempo is measured, not guessed

I wrote 2.1 Hz from "~126 BPM". Then I measured the track:

| method | result |
| --- | --- |
| energy envelope | 76.9 BPM — half-tempo harmonic, wrong |
| onset envelope (rising energy only) | **115.4 BPM**, beat 0.520s |

So 1.923 Hz, one shake per beat. My guess was 10 BPM off, enough to read as
off-beat. Correlate onsets, not energy.

## ffmpeg filter classes, again

Three filters, three different rules — and the graph is rejected whole, after
the download and transcribe are already paid for:

| filter | time expressions |
| --- | --- |
| `vignette` | **needs** `eval=frame`, else the ramp is a constant |
| `hue` | per-frame already; has no `eval` option at all |
| `gblur` | **rejects** them — gated with `enable=` instead |
| `noise` | same — `enable='gte(t,…)'` |

`_v31`/`_v32` invoke real ffmpeg per layer. A test asserting on the filter
string passes while ffmpeg refuses the graph.

## Known failing: `_v9`, `_v10`

Both load `media/uf9833efdc72b/PPOKdwOCMLA.words.json` — a render working
directory keyed by URL, never committed, and gone once a different video was
rendered. **They fail identically on a clean HEAD**, verified with `git stash`,
so this is not a regression from this release. They need a committed fixture;
I tried synthesising one and stopped, because tuning fake data until hardcoded
timestamps matched would have made the tests pass without testing anything.

---

**v0.5.0 "the frame has to be shot where the clip says it is"** · branch `claude/code-clipper-review-v9e3im`
9 files · new: `tests/` (18 regression tests + runner)

_Dalmislave_

---

## What this release is about

One rule, stated by the operator and broken by this pipeline four separate
times in a day:

> "semua frame harus bener footage dari palestina yang dibahas, itu rule
> kunci, kalau cuman gambaran dari footage lain, gw gamau"

Every fix below came from watching a delivered clip and measuring it, not from
a failing test. The tests came after, and are in `tests/` so the next change
cannot quietly undo them.

### The same bug, four wrong answers

The b-roll gate asks a vision model whether a frame belongs in the clip. It
worked correctly every time. The question was wrong four times:

| asked | result |
| --- | --- |
| "is this frame readable?" | generic crowd footage under a massacre caption |
| "does this frame show *dibom*?" | real footage of the same event discarded; **zero cutaways shipped** |
| "does this frame show *Prabowo membela Palestina*?" | a solidarity rally in **Jakarta** shipped under "mereka diserang" |
| "was this frame **shot on location** at *Palestina*?" | correct |

The lesson is in the shape of that table: a gate that is broken by its own
prompt looks exactly like a gate that is working. Diagnosis has to start from
the delivered artefact.

## The gate

**The unit is the clip, not the word.** `job._clip_topic()` computes one subject
for the whole clip, above the window loop. Asking per word rejected a funeral
procession as "not dibantai" and then threw away the entire source — and a veto
has no fallback, so over-strictness shows up as *no* b-roll, not worse b-roll.

**The subject is a place.** The speaker's name, the stance verb (`membela`,
`bicara soal`, `menyinggung`) and the venue are stripped, so
`"Prabowo membela Palestina di depan banyak pemimpin negara, di Gontor"`
becomes `"Palestina"`. Keeping the name is what let Jakarta through: an
Indonesian politician plus a cause describes Indonesian solidarity footage
perfectly.

**`on_topic` means shot there.** The prompt now names the rejects: a solidarity
march or rally in another country ("banners and flags about a place are not
that place"), another country's streets or skyline, an official at a podium
anywhere, studios, maps, stock imagery. Measured:

```
Jakarta rally                  reject   6/6 on repeat (shipped in v27)
Israeli spokesman at podium    reject
funeral procession, West Bank  accept
man searching rubble, Gaza     accept
crowds at Rafah crossing       accept
```

**Temperature 0.0, not 0.2.** The same airstrike frame was rejected during a
render and accepted 6/6 on re-check. A gate that samples cannot be debugged
from its own log. `chat_json` stays at 0.7 — hooks and titles need variety.

**8 finalists, judged 4 at a time.** Three was tuned for "is this readable",
where almost any live frame passes. Under "is this the event", only 2 of 14
windows in a real Kompas package qualified and neither was in the top 3 by
motion. Parallel because eight sequential calls add ~30s per source.

**One rejected source no longer costs the cutaway.** `vetted()` defaulted to
`limit=1`, so the retry loop had nothing to retry: the log said "1 sources
checked" while the code intended three. Both caps are gone.

**A verified channel clears a lower view floor.** The 20k floor existed to
screen out reupload accounts, and on a verified channel verification already
does that job. Real Kompas footage at 603, 5 480 and 7 214 views was being
discarded; unverified channels still face the full floor.

## Failures that say so

Zero cutaways with `warnings: []` shipped once. Any dropped cutaway now appends
a warning naming the topic that had no footage, and `_gather_inserts` takes the
warning list so it cannot report success while silently producing nothing.

## Overlay

The cutaway is masked to the upper band via `geq` on the alpha plane — **not**
crop, which would change framing. 1080x1920 and 9:16 are untouched, per
"jgn diakalin dgn ratio videonya diubah ya pantang jg tu". Measured on the
delivered file, inside the cutaway window:

```
y=0     9.96   band
y=720   3.81   feather
y=1440  1.60   lectern, clean
```

Opacity inside the band is 0.78, raised from 0.55: at full frame a 0.55 blend
"actively degrades the evidence", with the keffiyeh pattern colliding with the
rubble texture and both layers weakened.

## Tests

`bash tests/run_all.sh` — 9 module self-checks, `job.py --selftest`, and 18
regression tests, each named for the render that exposed its bug. See
`tests/README.md` for the table.

They invoke real ffmpeg and the real router. Every bug in that table passed a
string-level assertion first: `hue` has no `eval` option, ffmpeg rejects the
whole graph, and a test asserting on the filter *string* stays green while the
render dies after download and transcription.

Four of these tests had to be **rewritten** during this work, because the rule
they encoded was the bug: `_v27` asserted the topic was two words or more,
which is exactly what kept "Prabowo" in the prompt.

---

**v0.4.0 "cutaways you can actually see, and failures that say so"** · branch `claude/code-clipper-review-v9e3im`
6 files · new: `broll_place.py`, `glossary.py`

_Dalmislave_

---

## B-roll cutaways, mid-clip

The clip now cuts away to real footage while the speaker keeps talking. The
insert is a timed overlay, not a concat: audio runs underneath untouched, so
nothing of the speech is lost.

Footage is searched on YouTube and never generated. Four gates stand between a
search result and the frame, and each one exists because something got through:

1. **Repeated names only.** A name has to recur at least twice. A one-off
   sentence-case capital — "Apalagi" at the start of a sentence — was read as a
   name and cut a Palestine clip to cartoon game art.
2. **Trusted spelling.** Names from `--context` are treated as correct; names
   from the transcript must snap to one of them (edit distance ≤ 0.2) or they
   are dropped rather than searched. `Gontar` searches as `Gontor`; `Gorontalo`
   stays `Gorontalo`, because it is a different place and 0.34 wrongly merged
   them.
3. **Title relevance.** The result's title must carry one of the search words.
4. **Credibility floor** (`broll.credible`): min 20k views, verified channel or
   50k+ followers, uploaded within four years, and a title free of
   game/animasi/AI/hoax/trailer markers. A missing upload date is a rejection,
   not a pass.

On the Gontor clip the floor rejected three candidates with reasons: 8,046 views
below the minimum, 1,606 days old past the 1,460 ceiling, and an unverified
channel with 684 followers.

### Stressed words open a window too

A name alone searches the subject in the abstract and returns more podium
footage — which is what the clip is already showing. The moment the speech
stresses **dibom**, **diserang**, **dibantai**, **mengungsi** or **kelaparan**,
the viewer is picturing the event, and the query becomes the subject plus that
action: `Palestina` + `dibom serangan` returns news coverage of what is being
described.

The action list is hand-written and closed, 19 entries. Not a model call: a
wrong guess spends a download and puts unrelated footage on screen, and a closed
list cannot drift onto an arbitrary word.

### Hold and spacing

A cutaway holds **3.5s** (`CLIPPER_BROLL_HOLD`), up to **5 per clip**, no closer
than **9s** apart. The first version held 2.2s and the operator could not find
it on playback — it read as a glitch rather than a shot. 9s is the floor the
editing-grammar skill sets at one effect per 8-12s.

## Failures now travel with the result

`job.py` returns a `warnings` list. Failing soft is correct — one unreachable
model should not cost a whole render — but failing soft and silently is not.

A clip shipped with `sololah` burned into its captions because the transcript
reviewer timed out and the only evidence was one line on stderr. Now:

```json
"warnings": ["transcript review skipped: model unreachable (ReadTimeout)
              — captions are raw Whisper output"]
```

`language.review()` takes an optional `status` dict and fills in which guard
fired: model unreachable, length mismatch, paraphrase rejected, or clean.

The reviewer's timeout went from a hardcoded 120s to `NINEROUTER_TIMEOUT`,
default 300s. A 400-word transcript round trip did not fit in 120s.

## Censor: two words that should never have shipped

`dibom` and `diserang` were passing through unmasked — the two words this clip
leans on hardest.

`bom` sat in `_STRICT`, the set of stems that match only bare with no prefix
allowed. The intent was to keep "bom" out of "bombardir"; the effect was that
`dibom` sailed past. And `serang` was not in the stem list at all.

Both fixed, and the reason prefixes are safe here is the closed suffix list: a
stem must END the word, so `bombardir`, `serangga` (an insect) and
`serangkaian` stay clean. Indonesian meN-/peN- also mutates the first letter, so
`nyerang` is a second entry covering `menyerang` and `penyerangan`.

Verified both directions in the self-check — the masked forms are asserted, not
assumed, and 60+ innocent words are checked for false positives.

## Still broken

- **Transcript accuracy is not measured end to end.** 10/12 words on one 45s
  passage is one data point, not a 99% claim.
- **The action list is Indonesian political vocabulary only.** A clip about
  something else gets name-driven cutaways and nothing more.
- **Cutaway placement is not verified automatically.** Finding the insert in a
  delivered clip still means extracting frames and looking at them. A reported
  insert at 50s was actually at 60s, and only frame extraction caught it.

---

**v0.3.1 "punch-in on the beat, transcript reviewed before it becomes a subtitle"** · branch `claude/code-clipper-review-v9e3im`
4 files · new: `language.py`

_Dalmislave_

---

## Punch-in cuts

A brief tighter crop on vocally stressed words, riding on top of the existing
slow zoom. Beats come from `emphasis.py` scores, not a timer — a cut that does
not land on a beat reads as a mistake. Spacing is capped at one per 9s
(`CLIPPER_PUNCH_MIN_GAP`), because one effect per 8-12s is plenty and more
makes a clip read as a template.

Measured on the Gontor clip: 5 punches at 11.5s, 23.0s, 34.2s, 55.0s, 67.0s —
gaps of 11.5 / 11.2 / 20.8 / 12.0s, every one on a word that passed the stress
threshold. Rendered frames put the subject at ~46% of frame height at rest and
~52% at the peak of a punch: visible on a phone, not a zoom transition.

Shaped as summed cosine bumps rather than a step, so each punch ramps in and
out like a camera move. A clip with no vocal emphasis gets no punches rather
than invented ones, and `CLIPPER_PUNCH=0` turns it off.

## Transcript accuracy

Three changes, in the order they run:

**Beam search** (`CLIPPER_WHISPER_BEAM=5`) instead of greedy decoding.
Measured on 245-290s of the Gontor speech against words the press transcripts
confirm: greedy 8/12, beam 10/12 — it recovered `dibom`, `kurang`, `berdaya`.
Costs 72s → 91s on this box, against a ~220s render.

**Topic prompt** — the `--context` line is now also passed to the decoder, so
names it has never seen in Indonesian stop being rewritten into common words
that sound similar.

**Language review** (`language.py`) — the remaining errors are lexical, not
acoustic, so no decoder setting fixes them: `sololah` for `seolah`, `sudara`
for `saudara`. A reviewer corrects those **in place, one word for one word**.

Word timings must survive, because captions are drawn from them. The guards
come from the `translation-quality` skill's anti-fabrication checklist
(senshinji/claude-translation-skill), enforced in code rather than asked for in
the prompt:

- a reply of the wrong length is rejected outright — merged or split words
  would desynchronise every later caption
- a single word replaced by something unrelated is rejected (edit distance)
- more than 25% of a long transcript changed is treated as a paraphrase and
  discarded wholesale
- any failure returns the transcript untouched

On the real passage the reviewer changed exactly 2 of 48 words
(`sudara-sudara` → `saudara-saudara`, `sololah` → `seolah`) with timings
byte-identical. `CLIPPER_LANG_REVIEW=0` disables it.

## Still broken / not done

- **BGM library still has one track.** Mood tagging has nothing to choose from.
- **Flash transitions and b-roll insertion are not implemented.** `broll.py`
  finds footage; nothing places it on the timeline yet.
- **The language reviewer costs one model call per job** and is not cached, so
  a re-render re-reviews. The transcript sidecar caches the raw Whisper output,
  not the reviewed version.
- **Accuracy is measured on one passage of one video.** 10/12 on a 45s window
  is not a 99% claim — it is one data point.

---

**v0.3.0 "editorial captions, stress from audio, b-roll search"** · branch `claude/code-clipper-review-v9e3im`
10 files · new: `emphasis.py`, `broll.py`, `censor.py`, `bgm_add.py`, `docs/`

_Dalmislave_

---

## What this is

Project #1 of **Oden Tal Company** (`docs/ODEN_TAL_COMPANY.md`). This release
adds a third caption style, derives word emphasis from the speaker's audio
instead of guessing, sources b-roll from YouTube, and closes five security
findings in the new code.

## Editorial caption style

`--caption-style editorial` draws serif captions with a per-line opaque plate
(alpha 215) plus a 3px stroke, keeping the karaoke word highlight. Legibility
needed all three layers: a shadow alone vanished over bright footage.

The enlarged word is a **line break**, not an emphasis marker, so it is now
always the last word of the phrase. Two earlier attempts (any stressed word,
then any stressed word in the back half) both scrambled reading order —
`tadi saya inget sudara` rendered as `tadi saya sudara / INGET`. Emphasis is
carried by caps and colour, which do not move words.

## Emphasis from audio

`emphasis.py` scores each word on loudness and per-syllable pace relative to
its **neighbours** rather than the whole clip, so quiet passages can still
carry stress. Stopwords are blocked and at most 40% of a phrase can be marked
(`CLIPPER_EMPH_MAX_SHARE`). `CLIPPER_EMPH_THRESHOLD` tunes how many words
qualify; the current default of 1.15 marks ~32% of words, which may be too
many — it is a taste call, not a bug.

A failed audio read scores everything 0.0 and the captions fall back to the
model's punchline pick, so emphasis never blocks a render.

## B-roll search

`broll.py` finds cutaway footage **on YouTube for the clip's own subject** —
nothing is generated. Queries are built from proper nouns (the speaker's name
anchors hook footage) plus content words from the phrase being spoken. The
source video is excluded, and results are filtered by duration.

## Security findings closed

Five issues in code written this cycle:

- `emphasis.py` — ffmpeg had no `timeout`; a stalled decode would hang the
  render. Now bounded by `CLIPPER_EMPH_TIMEOUT` (120s) with a fail-soft return.
- `emphasis.py` — `sys` was never imported, so the error path itself would
  raise. Only reachable on failure, which is when it matters.
- `broll.py` — video ids arrive over the network and were interpolated into a
  URL unchecked. Now matched against `[A-Za-z0-9_-]{11}`; durations are
  coerced with a guard.
- `broll.py` — search terms came from a transcript and could contain a colon,
  which would change what `ytsearchN:` requests. Terms are scrubbed.
- `edit.py` — `accent_words` comes from the model and was lowercased without a
  type check; a non-string item would raise mid-render.

## Memory

`_pcm()` returned a list of Python floats — 47.8 MB for an 82s clip, scaling
with length. Now an `array('h')` with scaling folded into the reducer: 5.8 MB
for identical output.

## Also in this release

- `censor.py` — masks profanity and anatomical terms with asterisks.
- `bgm_add.py` — downloads background music tagged by mood; ducking is 0.8
  under the hook and 0.2 under speech, 0.6s fade.
- Zoom cycles on a cosine (~12s) because a single slow push across 82s is not
  visible.
- `docs/9ROUTER.md` — tunnel and model-routing notes, no keys.
- `segments.py` — the topical picker's exception is printed instead of
  swallowed. A transient router error had been presenting as "no good segment".

## Still broken / not done

- **BGM library has one track** (`inspiring_giants_league.mp3`, tagged
  `inspiring`). Clips with mood `emotional` fall back to it and the log says
  so. Needs more tracks per mood.
- **Whisper mishears Indonesian names and particles** — `seolah` → `sololah`,
  `saudara` → `sudara`. Captions show the mistake. No correction list yet.
- **Punch-in cuts and flash transitions are not implemented.** B-roll search
  works but insertion into the timeline does not.
- `trace_path` in the newly installed codebase index misses cross-module
  callers (it reported 1 caller for `score_words`; grep finds 3, including
  `job.py:317`). Use `search_code` instead.

---

**v0.2.4 "camera that follows the speaker"** · branch `claude/code-clipper-review-v9e3im`
1 commit · 5 files · `edit.py`: face-tracked camera (YuNet); `fetch.py`: SABR bypass

_Dalmislave_

---

## What this is

The camera now follows the speaker's face instead of only pushing in centred.
This release also commits the download fix that had been running uncommitted
on the box.

## Face-tracked camera

When `CLIPPER_ZOOM` is on, the renderer detects faces with a YuNet model
(`models/face_detection_yunet_2023mar.onnx`, bundled) on the cropped 9:16
frame, once per second. The zoom centre follows the primary face (nearest the
previous position, so a two-person shot tracks one speaker rather than hopping)
along a piecewise-linear path, clamped so the crop never leaves the frame. No
face detected, and the camera falls back to the centred push-in. Set
`CLIPPER_FACE_TRACK=0` to disable.

## Download fix, finally committed

`fetch.py` had been running with an uncommitted patch: `player_client`
`web_embedded` (supports cookies, bypasses the SABR streaming YouTube forces on
the web client) and `remote_components ejs:github` (JS solver for the `n`/nsig
parameter). That is what makes a flagged VPS download at 2160p instead of
failing the bot-check; it is now in the tree.

## Still broken

No `cookies.txt` (YouTube capped at 360p and hits the bot-check without one),
empty BGM folder (silent clips), no Clippo session or uploader tokens (full
pipeline only).

---

**v0.2.3 "motion and word-by-word captions"** · branch `claude/code-clipper-review-v9e3im`
1 commit · 3 files · `edit.py` + `job.py`: Ken Burns push-in, karaoke default, .env fix

_Dalmislave_

---

## What this is

Two render changes the operator asked for: captions that highlight the spoken
word, and a slow camera push-in so a static talking-head shot moves.

## Camera movement (Ken Burns push-in)

`CLIPPER_ZOOM` (default 1.0 = off) pushes the frame in by that factor over the
clip. It is a centred zoom on the full-frame ("cover") path only: a zoom on the
fill/fit band would drag the band edge around. Captions are overlaid after the
zoom, so they stay sharp while the picture moves. The zoompan filter got `fps=`
pinned, otherwise zoompan's default 25 fps stretches the clip by a second and
desyncs the audio; verified 5s in, 5s out.

## Word-by-word captions

`caption_style="karaoke"` was already implemented (white text, active word
light blue `#87CEFA`) but not the default. The box now runs it via
`CLIPPER_CAPTION_STYLE=karaoke`.

## A latent bug fixed: .env was loaded too late

`edit.py` (and `fetch.py`, `transcribe.py`) read `CLIPPER_*` at import time,
but `.env` was only parsed when `metadata` imported `ai`, which happens after
`edit` in `job.py`'s import order, so every `CLIPPER_*` override in `.env` was
silently ignored. `job.py` now loads `.env` at the top, before any module
imports.

## Still broken

Unchanged: no `cookies.txt` (360p), empty BGM folder (silent clips), no Clippo
session or uploader tokens.

---

**v0.2.2 "copy that represents the clip"** · branch `claude/code-clipper-review-v9e3im`
1 commit · 2 files · `metadata.py`: viral-title craft + a real description

_Dalmislave_

---

## What this is

Titles and descriptions were reading flat: a title could be the first sentence
of the transcript, and a description could come back as nothing but `#Shorts`.
Both are fixed.

## Title craft

The `metadata.py` prompt now asks the model to sell the specific moment, not
the topic: open a curiosity gap, prefer a punchy mini-quote over a label, and
stay true to what is actually said. Verified live: "Gaji Diakuin Kecil, Tapi
Kok Mobilnya Ganti Mulu?" instead of a flat restatement.

## Description must represent the clip

The prompt now requires a 2-3 sentence summary of who or what the clip is and
its key moment, before the hashtags. A fallback in `generate()` does the same
when the router is unreachable: a description of only hashtags is rebuilt from
the transcript, so `#Shorts` alone can never ship again.

## Still broken

Unchanged from v0.2.1: no `cookies.txt` (360p), empty BGM folder (silent
clips), and no Clippo session or uploader tokens (full pipeline only).

---

**v0.2.1 "9Router on-box"** · branch `claude/code-clipper-review-v9e3im`
1 commit · 2 files, `ai.py` +1 line · AI copy path now works against 9Router
running on the box itself.

_Dalmislave_

---

## What this is

9Router now runs locally on the box (`localhost:20128`) with Dalmi's key, and
the copy path works end to end. Two things changed to make that true.

## Fix: `ai.py` requests a non-streamed reply

9Router streams by default (SSE `data:` chunks), and `ai.py`'s `raw_decode`
could not parse that, so every copy call raised `JSONDecodeError`. The client
now sends `"stream": false` and gets a single `chat.completion` object back.
`ai.py` self-check passes (`chat_json OK`).

## Config: model pinned to one this router serves

The old default `ds/deepseek-v4-pro` is not in this 9Router's catalogue
(26 models, all `cc/*` and `ag/*`). `NINEROUTER_MODEL` is now
`cc/claude-sonnet-5`; cheaper swaps are `cc/claude-haiku-4-5-20251001` or
`ag/gemini-3-flash-low`.

## Still broken

- No `cookies.txt`: YouTube capped at 360p, and flagged-VPS requests hit the
  bot-check.
- Empty BGM folder (`bgm/`): clips render silent.
- Clippo session and uploader tokens absent: the full pipeline cannot submit
  or upload. The clip path is unaffected.

---

**v0.2 "reference style"** · branch `claude/code-clipper-review-v9e3im`
15 commits, 12 files, +1343 / −122 · one new module (`bgm.py`), one new manifest
(`requirements.txt`)

_Dalmislave_

---

## What this release is

v0.1 proved the spine: crawl Clippo → download → transcribe → pick a segment →
render → upload to YouTube. It looked nothing like the clips it was imitating.

v0.2 is about the picture. The renderer was rebuilt against two reference clips
until the output matches their format, and the parts of the pipeline that
decide *what* gets rendered — how long a clip may be, where it will be posted,
which music sits under it — stopped being hardcoded.

Nothing here changes how tasks are discovered or uploaded.

---

## Renderer

**The footage fills the frame.** `frame_mode="cover"` (new default) crops the
source to 9:16 and uses it as the whole canvas — no band, no blurred fill. The
earlier band was an artifact of feeding it landscape crops. `fill` (a 40% band
over a blurred copy) and `fit` (whole frame letterboxed) remain for landscape
sources, where covering means a hard zoom.

**Phrase captions.** Whole phrases in one colour instead of a per-word
highlight: gold with a heavy black stroke, centred, two lines maximum, with the
punchline tinted magenta. Phrases break where the speaker pauses; when one runs
past six words it is cut at the clearest pause inside the window and continued
as the next caption, never truncated. The per-word karaoke style is still there
behind `caption_style="karaoke"`.

Side effect worth knowing: this is roughly one overlay PNG per phrase instead
of one per word. A 60-second clip drops from ~150 ffmpeg inputs to ~25.

**Pull-quote hook.** A teal quote mark above a stack of white boxes, one per
wrapped line, so the right edge stays ragged. `**Double asterisks**` in the hook
text render bold and the rest regular; an unmarked hook renders bold
throughout. `hook_style="card"` gives the single continuous card instead.

**Two openings.** Pass `intro=` a b-roll clip and the hook lives there, cutting
to the segment when the card leaves — the way both references open. Without one
the hook rides over the opening seconds instead. The trade-off is real: with no
intro, the seconds under the hook carry no subtitle, because nothing is allowed
to share the screen with it.

**Everything stays out of the platform UI.** TikTok, Reels and Shorts paint over
roughly the bottom 15% of the frame. Captions and the hook are both anchored by
their *bottom* edge and grow upward, so neither a long hook nor a three-line
caption can walk off under the app. The self-check asserts it for one-, three-
and five-line hooks.

---

## Music

New `bgm.py`. The model never picks a file — it cannot hear music, and a
hallucinated filename is unrenderable. It labels the *clip* with one of seven
moods, which it can do from the transcript, and the mood resolves to a track
locally against `background_music/tracks.json`. Adding or retiring a track never
touches the prompt, and the label rides along in the metadata call that already
runs per clip, so it costs no extra round-trip.

Within a mood the track is chosen by a stable hash of the clip's identity: the
same clip re-rendered after a retry gets the same track, which `random.choice`
could not promise. Sibling clips of one task exclude each other's track.

Royalty-free is not attribution-free: a manifest entry with an `attribution`
line has it appended to the clip's description before upload.

```json
{"tracks": [
  {"file": "01.mp3", "mood": ["hype"], "attribution": "Music: X by Y (CC BY 4.0)"},
  {"file": "02.mp3", "mood": ["hype", "funny"]}
]}
```

Without a manifest, moods are read from filenames like `03_tense_slowbuild.mp3`.
An empty folder means no BGM, not an error.

---

## Clip length and destinations

**One cut has to fit everywhere it goes.** `duration_window()` takes the whole
destination set and returns the tightest window — highest floor, lowest ceiling.
YouTube Shorts in the set binds at 90s; without it, TikTok's 180 opens up.

| Platform | Window |
|---|---|
| YouTube Shorts | 30–90s |
| TikTok | 30–180s |
| Instagram Reels | 30–90s |

Overridable per host: `CLIPPER_DURATION_YOUTUBE=20-90`.

The old floors were 60s for TikTok and Instagram, which meant a sharp
thirty-second moment could never be clipped for them at all.

**Destinations are derived, not chosen.** The campaign brief says which
platforms it wants; the `accounts` table says where there is an account cleared
for campaign work; only platforms with a working uploader are publishable. The
intersection is the destination set. A human can pin it per campaign from the
dashboard when the rule gets it wrong.

The `accounts` table had been inert since it was written — a paused or banned
account changed nothing. It is now the gate, and it reads the *applied* status:
the promotion `evaluate()` suggests is explicitly not enough, so a bad stat sync
cannot push a platform into campaign work on its own.

Clippo's submission form takes only TikTok and Instagram URLs, so a clip
published to YouTube earns nothing from a campaign. Paying surfaces are
therefore sized on their own; YouTube is a destination only while nothing paying
is live — which is the current state.

---

## Reliability

- `metadata.generate` no longer fails the whole task when 9Router is
  unreachable; it degrades to transcript-derived copy.
- `ai.py` retries transport errors and 5xx with backoff, and still raises 4xx
  immediately.
- Dashboard escaping now covers quotes and `>`. Campaign ids come from Clippo's
