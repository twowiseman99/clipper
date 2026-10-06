"""Editing pipeline — renders one clip from source footage (PRD §3.6).

Ported from old main.py. Kept: PIL karaoke captions (3-word chunks, active-word
highlight), split-screen (bg gameplay + centered main video), bg darken/zoom,
BGM mix + fadeout. Dropped: RGB-shift anti-copyright (brand footage is legal —
decision 2026-07-26), upscale fx (canvas is fixed 1080x1920, the old check was
a no-op there), torch/nvenc probing (VPS is CPU; codec via env).

Split-screen and BGM are toggleable per call (PRD: campaign brief may forbid
visual additions -> clean mode).
"""
import os
import random
import re
import itertools
import shutil
import subprocess
import sys
import uuid
from collections import namedtuple

from PIL import Image, ImageDraw, ImageFont

import broll_place
import censor
import emphasis

# One timed image pasted onto the canvas: PNG path, position, visible window.
Overlay = namedtuple("Overlay", "path x y t_start t_end")

_counter = itertools.count()


def _name(prefix):
    """Short, unique PNG filename. A long clip carries hundreds of overlay
    inputs, and ffmpeg takes them as command-line args — full-length uuid names
    blow past the OS argument limit, so keep them tiny and run ffmpeg with the
    temp directory as its working directory."""
    return f"{prefix}{next(_counter):04d}.png"

_BASE = os.path.dirname(os.path.abspath(__file__))
FFMPEG = os.environ.get("CLIPPER_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
_PARENT = os.path.dirname(_BASE)

FONT_PATH = os.environ.get(
    "CLIPPER_FONT",
    r"C:\Windows\Fonts\arialbd.ttf" if sys.platform == "win32"
    else "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)
# Regular weight, for the un-emphasised half of a hook line. The reference
# style mixes both in one sentence, so the pair must be the same family.
FONT_PATH_REGULAR = os.environ.get(
    "CLIPPER_FONT_REGULAR",
    r"C:\Windows\Fonts\arial.ttf" if sys.platform == "win32"
    else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
BG_DIR = os.environ.get("CLIPPER_BG_DIR", os.path.join(_PARENT, "background_video"))
BGM_DIR = os.environ.get("CLIPPER_BGM_DIR", os.path.join(_PARENT, "background_music"))
CODEC = os.environ.get("CLIPPER_CODEC", "libx264")
# Encoder knobs matter most on a small VPS: "medium" (x264's default) buys
# quality that a re-encoded social clip never shows. Tune per host via env.
PRESET = os.environ.get("CLIPPER_PRESET", "veryfast")
BITRATE = os.environ.get("CLIPPER_BITRATE", "6M")
THREADS = int(os.environ.get("CLIPPER_THREADS", str(os.cpu_count() or 4)))
FPS = int(os.environ.get("CLIPPER_FPS", "30"))
BGM_VOLUME = float(os.environ.get("CLIPPER_BGM_VOLUME", "0.2"))
# The hook is the music's moment: the b-roll under it is muted and the bed
# carries the energy, then it ducks under the speaker so the talking stays
# legible. Two levels, not one, because the two seconds are doing opposite jobs.
BGM_HOOK_VOLUME = float(os.environ.get("CLIPPER_BGM_HOOK_VOLUME", "0.8"))
BGM_FADE = float(os.environ.get("CLIPPER_BGM_FADE", "0.6"))
# Mute the b-roll's own audio under the hook so the music bed owns it.
BGM_MUTE_BROLL_HOOK = os.environ.get(
    "CLIPPER_MUTE_BROLL_HOOK", "1").strip().lower() not in ("0", "false", "no")

CANVAS_W, CANVAS_H = 1080, 1920
BLUR_SIGMA = 28.0   # background blur strength (full-res equivalent)
BG_DARKEN = -0.12   # blurred fill is dimmed just enough to sit back
BLUR_SCALE = 0.25   # blur is computed at this scale, then upscaled back
SUB_Y = 1500
FONT_SIZE = 60
SPACING = 12
PADDING = 40
STROKE = 5
ACTIVE_COLOR = "#87CEFA"

# Phrase captions, the reference style.
# Whole phrases in one colour instead of a per-word highlight: gold by default,
# magenta for the beat the model marks as the punchline. Heavy black stroke is
# what keeps them legible over any footage.
PHRASE_COLOR = "#FFD24A"
PHRASE_ACCENT = "#FF3FA4"
PHRASE_FONT_SIZE = 54
PHRASE_STROKE = 6
PHRASE_LINE_GAP = 6
PHRASE_MAX_WORDS = 3      # words per line
# Two lines, then a new caption. Three is past what anyone reads off a feed,
# and a phrase that runs long is flushed and continued rather than truncated.
PHRASE_MAX_LINES = 2      # lines per phrase before it is flushed
PHRASE_GAP_SPLIT = 0.45   # a pause this long ends the phrase
PHRASE_X_FRAC = 0.09      # left margin, fraction of canvas width
PHRASE_Y_FRAC = 0.80      # block BOTTOM on a full frame (reference: 76-84%)
# "editorial": the reference-clip look — thin serif, no stroke, mixed roman and
# italic inside one phrase, and the punchline word set large on its own line.
# Deliberately quieter than the gold phrase style: it reads as designed rather
# than auto-captioned, which is the whole point of it.
EDIT_FONT_SERIF = os.environ.get(
    "CLIPPER_SERIF", "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf")
EDIT_FONT_SERIF_ITALIC = os.environ.get(
    "CLIPPER_SERIF_ITALIC", "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf")
EDIT_FONT_SERIF_BOLD = os.environ.get(
    "CLIPPER_SERIF_BOLD", "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf")
EDIT_SIZE = int(os.environ.get("CLIPPER_EDIT_SIZE", "72"))
EDIT_PUNCH_SIZE = int(os.environ.get("CLIPPER_EDIT_PUNCH_SIZE", "132"))
EDIT_X_FRAC = 0.09        # left margin: the block runs across the frame
EDIT_Y_FRAC = 0.62        # block TOP, below the speaker's face
# In pillar framing the source keeps its own lower-third banner, and the
# card's geometry puts that banner at y=1377 of a 1920 canvas. The editorial
# block is 206px tall, so the 0.62 default lands at 1190-1396 and overlaps it
# by 19px — reviewed on a delivered frame as "practically touching, the eye
# has to work to separate your caption from the broadcaster's headline".
# 0.56 clears it by 96px. The blurred band below the card (1680-1920) also
# fits, but a caption floating in the blur reads as a sticker rather than part
# of the clip, so the caption stays on the footage and moves up instead.
EDIT_Y_FRAC_PILLAR = float(os.environ.get("CLIPPER_EDIT_Y_PILLAR", "0.56"))
EDIT_LINE_GAP = 2
EDIT_SHADOW = (0, 0, 0, 170)
# Legibility floor. A speaker in white clothing swallowed plain white serif, so
# every word sits on its own dark plate and carries a stroke. 0 alpha drops the
# plate for footage dark enough not to need it.
EDIT_BOX_ALPHA = int(os.environ.get("CLIPPER_EDIT_BOX_ALPHA", "215"))
EDIT_BOX_RADIUS = int(os.environ.get("CLIPPER_EDIT_BOX_RADIUS", "10"))
EDIT_BOX_PAD = int(os.environ.get("CLIPPER_EDIT_BOX_PAD", "14"))
EDIT_STROKE = int(os.environ.get("CLIPPER_EDIT_STROKE", "3"))
# Stress score above which a word is set in caps (see emphasis.py).
EMPH_THRESHOLD = float(os.environ.get("CLIPPER_EMPH_THRESHOLD", "1.15"))
# "phrase" (reference look) or "karaoke" (per-word highlight, PRD §3.6)
CAPTION_STYLE = os.environ.get("CLIPPER_CAPTION_STYLE", "phrase")
# How the footage sits on the canvas:
#   "cover" — the footage fills the whole 9:16 frame, cropped to fit. No band,
#             no blurred fill. This is what the reference clips look like, and
#             what a clean feed already framed for vertical wants.
#   "fill"  — scale to FILL_HEIGHT_FRAC of the canvas and crop to width, over a
#             blurred copy of itself. A middle ground for landscape footage.
#   "fit"   — scale the whole frame in, never cropping; band height follows the
#             source aspect. Nothing is lost, the subject is smaller.
# "cover" is the default. It is a no-op crop on vertical footage and a hard
# zoom on landscape footage, so a landscape source is the case for "fit".
FRAME_MODE = os.environ.get("CLIPPER_FRAME_MODE", "cover")
# "pillar" framing: how much of the canvas width the full source frame fills.
# 1.0 is edge to edge. On a 16:9 source that makes the card 608px tall in a
# 1920 canvas — about a third of the height — so the inset must be as wide as
# the canvas allows or the caption inside it stops being readable on a phone.
# Verified by eye on a real frame at 0.94: the headline was "close to the lower
# limit for comfortable mobile viewing".
PILLAR_FILL = float(os.environ.get("CLIPPER_PILLAR_FILL", "1.0"))
# How much of the canvas HEIGHT the sharp footage occupies. The original
# pillar put the whole 16:9 frame edge to edge, which is only 608px of a 1920
# canvas: 32% footage, 68% blurred filler, and a head about 13% of the frame
# height. The operator's verdict on that render was "jelek banget" and
# "efeknya juga ampun", which is the correct read — on a phone the subject was
# thumbnail-sized and two thirds of the screen carried no information.
#
# At 0.75 the footage is 1440px tall. A 16:9 source scaled to that height is
# 2560 wide, so only 42% of the source width survives the 1080 crop — the
# source's own lower-third chyron cannot stay intact at this size. That is the
# real trade: a readable subject, or an intact borrowed banner. The banner is
# the broadcaster's furniture, the face is the clip, so the subject wins and
# the crop window follows it rather than keeping the middle.
PILLAR_COVER = float(os.environ.get("CLIPPER_PILLAR_COVER", "0.75"))
# Background blur strength. Strong enough that the duplicated frame reads as
# texture rather than a second picture competing with the subject.
PILLAR_BLUR = float(os.environ.get("CLIPPER_PILLAR_BLUR", "28"))
# How far the background copy is pushed in, as a multiple of canvas width.
# 1.7 puts the source's own lower-third banner (measured at 88% of frame
# height on Tribunnews footage) outside the visible crop, so the
# backdrop cannot echo the headline back at the viewer.
PILLAR_BG_ZOOM = float(os.environ.get("CLIPPER_PILLAR_BG_ZOOM", "1.7"))
# Backdrop brightness drop and desaturation. The background has to lose the
# argument with the foreground; blur alone still leaves a bright, colourful
# field that pulls the eye off the subject.
PILLAR_BG_DIM = float(os.environ.get("CLIPPER_PILLAR_BG_DIM", "0.28"))
PILLAR_BG_SAT = float(os.environ.get("CLIPPER_PILLAR_BG_SAT", "0.55"))
FILL_HEIGHT_FRAC = 0.62
# Camera movement: a slow centred push-in (Ken Burns) on the full-frame path.
# 1.0 is off; 1.12 pushes in 12% by the last frame. Captions are overlaid after
# the zoom, so they stay sharp while the picture moves. A zoom on the fill/fit
# band would drag the band edge around, so it applies to "cover" only.
ZOOM = float(os.environ.get("CLIPPER_ZOOM", "1.0"))
# Seconds for one in-and-out zoom cycle. 0 keeps the old single slow push.
ZOOM_CYCLE = float(os.environ.get("CLIPPER_ZOOM_CYCLE", "12"))
# Punch-in: a brief tighter crop on vocally stressed words. This is the
# cheapest effect that reads as "edited" — the grammar is punch-in before
# flash, flash before anything louder. Beats come from emphasis.py scores, so
# a clip with no vocal emphasis gets no punches rather than invented ones.
PUNCH = os.environ.get("CLIPPER_PUNCH", "1") not in ("0", "", "false")
# How much tighter the crop gets at the peak. 0.06 is ~6%: visible on a phone
# without looking like a zoom transition.
PUNCH_AMOUNT = float(os.environ.get("CLIPPER_PUNCH_AMOUNT", "0.10"))
# Seconds from start to finish of one punch, ramped in and out.
#
# Both numbers MEASURED on real ffmpeg renders (testsrc2, frame-difference
# peak inside the punch window, against a 2.34 no-punch control):
#
#   amount  0.06 -> 4.34    hold  0.90s -> 5.87
#           0.10 -> 5.87          0.60s -> 6.53
#           0.14 -> 6.74          0.45s -> 7.84
#           0.18 -> 7.37          0.30s -> 8.45
#
# Depth saturates past 0.10 — the extra crop is barely more motion and starts
# cutting into the frame. The HOLD is the bigger lever: the same zoom over
# half the time reads as a hit rather than a drift. 0.30s was faster still and
# reads as a glitch rather than a camera move, which the editing grammar warns
# about, so 0.45s is the floor.
PUNCH_HOLD = float(os.environ.get("CLIPPER_PUNCH_HOLD", "0.45"))
# One effect per 8-12s is plenty for a 60-90s clip; closer together and the
# clip reads as a template rather than an edit.
PUNCH_MIN_GAP = float(os.environ.get("CLIPPER_PUNCH_MIN_GAP", "2.7"))
# Hits inside a burst, and how close they have to be to count as one burst.
#
# MEASURED off the operator's reference (AGv6G13TPUc). Its motion peaks arrive
# in groups of 1-3 within ~0.6s, then a 2-4s gap: five groups across 13.5s of
# body. The old flat 9s spacing could not express that shape — it kept 3 of 27
# qualifying beats on a 31.8s clip and left the first 4.7s with nothing, which
# is what "efeknya kurang sebelum jedag jedug" was describing.
PUNCH_BURST = int(os.environ.get("CLIPPER_PUNCH_BURST", "3"))
PUNCH_BURST_GAP = float(os.environ.get("CLIPPER_PUNCH_BURST_GAP", "0.75"))
PUNCH_MAX = int(os.environ.get("CLIPPER_PUNCH_MAX", "16"))
# Flash: a brief white pop on the very strongest beats. Off by default —
# "transitions serve the narrative, not the ego", and a punch-in already marks
# the beat. Turn on with CLIPPER_FLASH=1 when a clip needs more lift.
FLASH = os.environ.get("CLIPPER_FLASH", "0") not in ("0", "", "false")
# Brightness added at the peak. 0.35 is clearly visible without blowing the
# image out to white, which loses the speaker's face for those frames.
FLASH_AMOUNT = float(os.environ.get("CLIPPER_FLASH_AMOUNT", "0.35"))
FLASH_HOLD = float(os.environ.get("CLIPPER_FLASH_HOLD", "0.22"))
# Harder cap than punches: a flash interrupts the image, so three in a 90s
# clip is already a lot.
FLASH_MAX = int(os.environ.get("CLIPPER_FLASH_MAX", "3"))
# Outro: how the clip closes. Two shapes, because the ending has to match what
# the clip is about — a flash stinger under a man apologising for people being
# killed is the wrong register, and reads as a template applied without
# listening.
#
#   "stinger"    fast bright pulses, the jedak-jeduk ending. Energy, outrage,
#                hype. Chosen for angry/energetic moods.
#   "melancholy" the footage drains to black and white and dims as it ends.
#                Grief, reflection, an apology. Chosen for emotional/sad moods.
#   "none"       no treatment.
#
# Default "auto" picks from the clip's mood, which bgm.py already derives from
# the transcript, so the ending follows the content rather than a flag.
OUTRO = os.environ.get("CLIPPER_OUTRO", "auto").strip().lower()
# How long the closing treatment runs. 3s read as too short on playback: by the
# time a viewer registers the colour leaving, the clip is over. 5s let the drain
# land; the operator then asked for longer still ("outro sedihnya panjangin"),
# so 8s. The guard in _outro_filters keeps this from eating a short clip: the
# treatment is skipped unless the clip is at least 3x the span, i.e. 24s here.
OUTRO_SECONDS = float(os.environ.get("CLIPPER_OUTRO_SECONDS", "8.0"))
# The jamet ending needs its own, shorter span. The melancholy outro is a slow
# ramp — desaturate, vignette, grain, slowmo, dip — and 8s is what gives that
# room to land. A freeze-frame shake is instant: the face stops, the beat hits,
# three seconds is plenty and more just stalls the clip. Separate constants
# also mean the guard below (dur < span*3) scales per ending, so a 22s viral
# cut can still have an outro while a 22s sombre cut correctly cannot.
OUTRO_JAMET_SECONDS = float(os.environ.get("CLIPPER_OUTRO_JAMET_SECONDS", "3.0"))
# Stinger shape. Pulses per second: 4 reads as rhythm, past about 6 it is a
# strobe, which is unpleasant and an accessibility problem.
OUTRO_RATE = float(os.environ.get("CLIPPER_OUTRO_RATE", "4"))
OUTRO_AMOUNT = float(os.environ.get("CLIPPER_OUTRO_AMOUNT", "0.42"))
OUTRO_HOLD = float(os.environ.get("CLIPPER_OUTRO_HOLD", "0.12"))
# Melancholy shape. How far colour drains. Full greyscale was the first attempt
# and the operator called it "aneh": a face drained to pure grey reads as the
# visual language of an obituary, and the man is mid-speech. 0.5 shifts the
# register without killing the image.
OUTRO_DESAT = float(os.environ.get("CLIPPER_OUTRO_DESAT", "0.5"))
# And how far it dims by the final frame. Zero by default now: with the partial
# desaturation above, a dim on top read as two effects stacked, and the dim was
# the part that made the ending feel like a fade-to-nothing rather than a held
# moment. Raise it if a clip's footage is bright enough to need it.
OUTRO_DIM = float(os.environ.get("CLIPPER_OUTRO_DIM", "0.0"))
# Slow-motion on the closing seconds. The last line lands and the image eases
# off rather than stopping at full speed, which is what the operator asked for
# and what a held final beat actually needs. 0.7 = 70% speed; low enough to
# read as deliberate, high enough that lip movement does not turn into a
# stutter. Implemented with setpts (no frame interpolation), so the audio is
# untouched: the speech must stay in sync.
OUTRO_SLOWMO = float(os.environ.get("CLIPPER_OUTRO_SLOWMO", "0.7"))
# Vignette on the closing seconds: the frame edges darken inward so attention
# collapses onto the speaker as the clip ends. This is the "agak norak" layer
# the operator asked for — showy enough to read as a deliberate ending, and
# unlike a flash it adds no pulses, which a grief clip must not have. In
# radians at full strength; PI/4.5 is a visible corner fall-off, PI/2 is a
# porthole.
OUTRO_VIGNETTE = float(os.environ.get("CLIPPER_OUTRO_VIGNETTE", "0.698"))
# Film grain over the same window, so the drained image reads as aged footage
# rather than a broken encode. Low: 6 is texture, past ~15 it looks like noise
# in the source and the operator reviews frames at full size.
OUTRO_GRAIN = float(os.environ.get("CLIPPER_OUTRO_GRAIN", "6"))
# Dip to black on the very last beat. Short on purpose: a dim spread across the
# whole window is what the operator called "aneh" (OUTRO_DIM, now 0) because the
# ending read as fading to nothing instead of holding. Confined to the final
# ~1.2s it is a closing gesture rather than a slow drain, and it gives the clip
# a hard end instead of cutting mid-frame on loop.
OUTRO_FADE = float(os.environ.get("CLIPPER_OUTRO_FADE", "1.2"))
# How far before the final frame the fade finishes. The reviewer measured the
# last frame at Y=21 — dark grey, not black — because a fade only reaches zero
# at st+d and the clip ended there. 0.3s of held black closes it properly.
OUTRO_FADE_LEAD = float(os.environ.get("CLIPPER_OUTRO_FADE_LEAD", "0.3"))
# Moods that get the quiet ending. Everything else gets the stinger.
OUTRO_SAD_MOODS = ("emotional", "sad", "reflective", "somber", "serious")
# --- "jamet" ending (the TikTok edit) --------------------------------------
# Operator's brief: "editan jamet, kayak video viral tiktok, ikutin beat gambar
# goyang-goyang setelah di pause bagian gibran". So: hold the frame, then shake
# it on the beat. This is the loud sibling of the melancholy ending and is only
# reachable by asking for it (CLIPPER_OUTRO=jamet) or via a hype/funny mood.
#
# How long the frozen frame holds. The operator's spec, from the reference
# tutorial: "nanti berakhirnya di gibran setelah ngomong suruh bawa bekal,
# selesai itu jeda 2 detik jedag jedug, lu liat kan itu videonya dah ga di
# play, jadi image gitu" — the picture STOPS and the beat-shake happens on the
# still, which is the whole jedag-jedug convention. At 0.5s the clip went back
# to moving video almost immediately and the ending read as a stumble rather
# than a freeze.
OUTRO_FREEZE = float(os.environ.get("CLIPPER_OUTRO_FREEZE", "2.0"))
# Shakes per second. This must match the music or the edit looks drunk rather
# than on-beat, so it is MEASURED, not guessed: 1.923 Hz is one shake per beat
# of the jedag-jedug track at 115.4 BPM (beat = 0.520s), found by onset-envelope
# autocorrelation. A plain energy envelope reported 76.9 BPM on the same file —
# the half-tempo harmonic — so onsets (rising energy only) are what to correlate.
# Re-measure when the track changes; CLIPPER_OUTRO_SHAKE_HZ overrides per clip.
OUTRO_SHAKE_HZ = float(os.environ.get("CLIPPER_OUTRO_SHAKE_HZ", "1.923"))
# Shake amplitude in pixels on a 1080-wide canvas. 28 is visible without
# tearing the subject off-frame; past ~60 the face leaves the safe area.
OUTRO_SHAKE_PX = float(os.environ.get("CLIPPER_OUTRO_SHAKE_PX", "28"))
# Hits per beat. MEASURED against the reference, not chosen: the operator's
# CapCut tutorial (youtube AGv6G13TPUc, 30-34s) runs 8 hits in 4.0s — 2.00 per
# second, one hit every 0.500s. At 1.923 Hz the track's own beat gives 1.92/s,
# so one hit per beat matches the reference within 4%.
#
# This was 3 (5.77 hits/s, one every 0.173s), tuned against a DIFFERENT
# reference short (shorts/twn4fIJ0PUk) where the brief was "40% of frames
# above 6.0 motion". Carrying that number over to this ending made it nearly
# 3x denser than the clip it was supposed to look like, and the operator's
# verdict was "getarannya terlalu gitu". Two references, two answers: the
# density belongs to whichever clip is being matched, so re-measure instead of
# inheriting.
OUTRO_PUNCH_PER_BEAT = float(os.environ.get("CLIPPER_OUTRO_PUNCH_PER_BEAT", "1"))
# How fast each hit decays inside its slot. The envelope is exp(-DECAY*phase)
# where phase runs 0..1 across ONE BEAT, so this number is only meaningful
# together with the period — it is not an absolute speed.
#
# That coupling bit once already: at 3 hits/beat the slot was 0.173s and
# DECAY=2 put the whole excursion in 0.087s, a snap. Dropping to 1 hit/beat
# stretches the slot to 0.520s, and the same DECAY=2 would spread that one
# excursion over 0.260s — a slow drift, exactly the thing the operator
# rejected earlier ("itu kan geser doang"). DECAY=6 restores the 0.087s snap
# at the new period, so the ending gets FEWER hits with the same attack
# instead of fewer, mushier ones.
OUTRO_PUNCH_DECAY = float(os.environ.get("CLIPPER_OUTRO_PUNCH_DECAY", "6"))
# Zoom punch depth as a scale factor on top of the positional kick. The
# reference short pairs every hit with a scale pop; position alone looked like
# a camera bump rather than an edit. 0.08 = an 8% snap in on each beat.
OUTRO_PUNCH_ZOOM = float(os.environ.get("CLIPPER_OUTRO_PUNCH_ZOOM", "0.08"))
# Every mood the pipeline is known to produce (bgm.py's buckets plus the sad
# list). A mood outside this set means the caller and this module disagree, so
# the stinger default is a guess rather than a decision — worth a warning.
_OUTRO_KNOWN_MOODS = OUTRO_SAD_MOODS + (
    "hype", "funny", "inspiring", "tense", "mysterious", "chill")
# Ceiling on one ffmpeg render. Only ever trips on a stall — see the call site.
RENDER_TIMEOUT = int(os.environ.get("CLIPPER_RENDER_TIMEOUT", "2400"))
# Follow the speaker's face when zooming, instead of staying centred. Detection
# uses a YuNet face detector on the cropped 9:16 frame; no face, and the
# camera stays centred. cv2 is imported lazily so the self-check runs without it.
FACE_TRACK = os.environ.get("CLIPPER_FACE_TRACK", "1") not in ("0", "false", "no", "")
# YuNet ONNX face detector (much fewer false positives than the Haar cascade).
FACE_MODEL = os.path.join(_BASE, "models", "face_detection_yunet_2023mar.onnx")
# Panning the 9:16 crop window across the source instead of holding it centred.
# A 16:9 source only keeps its middle 32% in a 9:16 frame, so a wide two-shot
# puts both speakers outside the crop and the clip stares at the table between
# them. Panning slides that window to wherever the speaker actually is. The
# aspect ratio never changes; only which part of the source the window keeps.
PAN = os.environ.get("CLIPPER_PAN", "1") not in ("0", "false", "no", "")
PAN_STEP = 0.5        # seconds between face samples
PAN_DEADZONE = 0.18   # face may drift this fraction of the window before moving
PAN_HOLD = 0.6        # seconds off-centre before the camera commits to a move
PAN_SLIDE = 0.6       # seconds a reframe takes, so it reads as a pan not a cut

# Where the captions sit relative to the footage:
#   "below"  — the footage is shrunk to the reference clip's proportion and
#              stays centred; captions live in the clear strip under it.
#              Nothing is ever covered.
#   "inside" — captions sit on the footage (the reference look). The footage
#              stays as large as frame_mode allows.
# These cannot both be maximised: a 62%-tall video leaves no strip that is also
# clear of the platform's own UI, so "below" trades video size for a clean
# caption lane. See BELOW_* below.
CAPTION_PLACE = os.environ.get("CLIPPER_CAPTION_PLACE", "below")
# TikTok/Reels/Shorts paint their caption, handle and buttons over roughly the
# bottom 15% and right edge of the frame. Anything below this is at risk of
# being covered by the app, so the caption lane has to end above it.
PLATFORM_SAFE_BOTTOM = 0.82
# 40% centred is the proportion the reference clip uses throughout (measured
# 42/39/33/40% across its shots, always centred on 50%). It also happens to
# leave exactly enough room underneath for a caption lane.
BELOW_HEIGHT_FRAC = 0.40     # footage height when captions go below it
BELOW_CAPTION_BOTTOM = 0.81  # caption block bottom, inside the safe area
# Hook card bottom (not top): a two-line and a four-line hook then both sit
# inside the footage instead of the longer one spilling onto the blurred fill.
BELOW_HOOK_BOTTOM = 0.69


def _random_asset(dirpath, exts):
    try:
        files = [os.path.join(dirpath, f) for f in os.listdir(dirpath)
                 if f.lower().endswith(exts)]
        return random.choice(files) if files else None
    except OSError:
        return None


EMOJI_FONT = os.environ.get(
    "CLIPPER_EMOJI_FONT",
    r"C:\Windows\Fonts\seguiemj.ttf" if sys.platform == "win32"
    else "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
)
# emoji + ZWJ/variation-selector runs (rendered with the color-emoji font)
_EMOJI_RE = re.compile(
    "([\U0001F000-\U0001FAFF\U0001F1E6-\U0001F1FF\u2600-\u27BF\u2B00-\u2BFF"
    "\uFE0F\u200D]+)"
)


def _emoji_tile(chunk, px):
    """Render an emoji run to an RGBA tile at height ~px. Noto Color Emoji is
    a bitmap font (fixed size 109) — render there and rescale when needed."""
    for size in (px, 109):
        try:
            f = ImageFont.truetype(EMOJI_FONT, size)
            bbox = f.getbbox(chunk)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            if w <= 0 or h <= 0:
                return None
            img = Image.new("RGBA", (w + 8, h + 8), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((4 - bbox[0], 4 - bbox[1]), chunk, font=f,
                                     embedded_color=True)
            if size != px:
                img = img.resize((max(1, int(img.width * px / size)),
                                  max(1, int(img.height * px / size))))
            return img
        except OSError:
            continue
    return None


def _mixed_text_image(text, font, fill, stroke_width=0):
    """Render text that may contain emoji: text runs use `font`, emoji runs the
    color-emoji font. Returns (RGBA image, visual_text_width)."""
    px = getattr(font, "size", FONT_SIZE)
    tiles, vis_w = [], 0
    for chunk in _EMOJI_RE.split(text):
        if not chunk:
            continue
        if _EMOJI_RE.fullmatch(chunk):
            tile = _emoji_tile(chunk, px)
            if tile is not None:
                tiles.append(tile)
                vis_w += tile.width
            continue
        bbox = font.getbbox(chunk)
        left, top, right, bottom = bbox if bbox else (0, 0, 10, px)
        w, h = right - left, bottom - top
        pad = stroke_width + 8
        img = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
        kw = {"stroke_width": stroke_width, "stroke_fill": "black"} if stroke_width else {}
        ImageDraw.Draw(img).text((pad - left, pad - top), chunk, font=font, fill=fill, **kw)
        tiles.append(img)
        vis_w += w
    if not tiles:
        return Image.new("RGBA", (10, px), (0, 0, 0, 0)), 10
    height = max(t.height for t in tiles)
    total_w = sum(t.width for t in tiles)
    canvas = Image.new("RGBA", (total_w, height), (0, 0, 0, 0))
    x = 0
    for t in tiles:
        canvas.paste(t, (x, (height - t.height) // 2), t)
        x += t.width
    return canvas, vis_w


HOOK_Y = 300          # hook block top, centered style (split-screen mode)
# Hook block BOTTOM on a full frame. Anchoring the bottom rather than the top
# is what keeps a four-line hook from growing down past the platform's UI —
# the block grows upward instead, and the last line is always readable.
CLEAN_HOOK_BOTTOM = 0.81
CLEAN_SUB_Y = 1040    # karaoke line in full-frame mode (mid-frame, above hook)
HOOK_X_LEFT = 162     # left margin, 15% of canvas (measured off the reference)
HOOK_EDGE_PAD = 32    # breathing room kept clear on the right of a left-hugged hook
HOOK_FONT_SIZE = int(os.environ.get("CLIPPER_HOOK_FONT", "64"))
HOOK_DUR = float(os.environ.get("CLIPPER_HOOK_SECONDS", "7"))
HOOK_MAX_CHARS = 26   # wrap width per boxed line
# The hook is the one piece of text a scroller reads before deciding, so it
# runs as wide as the frame allows. 0.94 leaves a thin margin on each side:
# text touching the very edge reads as a rendering bug, not as a design.
HOOK_MAX_W = int(0.94 * CANVAS_W)
HOOK_PAD_X, HOOK_PAD_Y = 22, 10
# Two hook treatments seen across the reference clips:
#   "boxes" — one white box per line, ragged right, a teal quote mark above.
#   "card"  — a single continuous white card, no icon.
# "boxes" is the default: it is what the podcast reference uses, and the ragged
# right edge is what makes it read as a pull-quote rather than a caption.
HOOK_STYLE = os.environ.get("CLIPPER_HOOK_STYLE", "boxes")
QUOTE_TEAL = "#64BBA8"   # sampled from the reference
QUOTE_H = 69             # icon height on our canvas, scaled from the reference
HOOK_LINE_GAP = 5


def _parse_emphasis(text):
    """Split "plain **bold** plain" into [(word, is_bold)] tokens.

    The reference style bolds only the loaded half of a hook sentence and
    leaves the connective words regular, which is what makes it read like a
    headline instead of a caption. metadata.py emits the ** markers.
    """
    tokens, bold = [], False
    for chunk in re.split(r"(\*\*)", text.strip()):
        if chunk == "**":
            bold = not bold
            continue
        for word in chunk.split():
            tokens.append((word, bold))
    return tokens


def _wrap_tokens(tokens, max_chars=HOOK_MAX_CHARS):
    """Greedy wrap of (word, bold) tokens into lines, emphasis preserved."""
    lines, cur, width = [], [], 0
    for word, bold in tokens:
        add = len(word) + (1 if cur else 0)
        if cur and width + add > max_chars:
            lines.append(cur)
            cur, width = [], 0
            add = len(word)
        cur.append((word, bold))
        width += add
    if cur:
        lines.append(cur)
    return lines


def _rich_line_image(line, bold_font, reg_font, fill="black"):
    """One hook line whose words may switch weight. Returns an RGBA image."""
    runs, buf, cur_bold = [], [], line[0][1]
    for word, bold in line:
        if bold != cur_bold:
            runs.append((" ".join(buf), cur_bold))
            buf, cur_bold = [], bold
        buf.append(word)
    runs.append((" ".join(buf), cur_bold))

    # _mixed_text_image pads each tile, so advance by the VISUAL width and let
    # the padding overlap — otherwise every weight switch reads as a double
    # space. Same trick the karaoke layer uses.
    pad = 8
    tiles, widths = [], []
    for text, bold in runs:
        img, vis_w = _mixed_text_image(text, bold_font if bold else reg_font, fill)
        tiles.append(img)
        widths.append(vis_w)
    space = reg_font.getlength(" ") if hasattr(reg_font, "getlength") else HOOK_FONT_SIZE * 0.3
    ink_w = sum(widths) + space * (len(tiles) - 1)
    height = max(t.height for t in tiles)
    img = Image.new("RGBA", (int(ink_w) + pad * 2, height), (0, 0, 0, 0))
    x = 0.0
    for t, w in zip(tiles, widths):
        img.paste(t, (int(x), (height - t.height) // 2), t)
        x += w + space
    return img.crop((pad, 0, pad + int(ink_w), height))


def _quote_icon(tmp_dir, h=QUOTE_H):
    """Teal rounded box with white quote marks, sitting above the hook lines."""
    img = Image.new("RGBA", (int(h * 1.6), h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=10,
                        fill=QUOTE_TEAL)
    try:
        f = ImageFont.truetype(FONT_PATH, int(h * 1.15))
    except OSError:
        f = ImageFont.load_default()
    q = "\u201c"
    bbox = f.getbbox(q)
    d.text(((img.width - (bbox[2] - bbox[0])) / 2 - bbox[0],
            (img.height - (bbox[3] - bbox[1])) / 2 - bbox[1] + h * 0.16),
           q, font=f, fill="white")
    path = os.path.join(tmp_dir, _name("q"))
    img.save(path)
    return path


def _hook_layer(text, tmp_dir, dur=HOOK_DUR, y=HOOK_Y, left=False, bottom=False,
                style=HOOK_STYLE):
    """Visual hook — ONE white box behind every line, black text.

    style="boxes" draws one white box per line with a teal quote mark above,
    the pull-quote look; style="card" draws a single continuous card instead.
    left=True hugs HOOK_X_LEFT, otherwise the block is centered.
    bottom=True reads `y` as the card's bottom edge, so the card grows upward
    and a longer hook cannot push past whatever sits under it.
    Returns a list of Overlay specs (always exactly one).
    """
    try:
        bold_font = ImageFont.truetype(FONT_PATH, HOOK_FONT_SIZE)
    except OSError:
        bold_font = ImageFont.load_default()
    try:
        reg_font = ImageFont.truetype(FONT_PATH_REGULAR, HOOK_FONT_SIZE)
    except OSError:
        reg_font = bold_font

    tokens = _parse_emphasis(text)
    # A hook with no ** markers is uniformly weighted — and it reads as bold,
    # not as body text, so an unmarked hook renders bold throughout.
    if not any(b for _, b in tokens):
        tokens = [(w, True) for w, _ in tokens]
    lines = _wrap_tokens(tokens)
    if not lines:
        return []
    rendered = [_rich_line_image(l, bold_font, reg_font) for l in lines]

    # A long hook at the headline size can outgrow the canvas. Step the font
    # down until the widest line fits rather than letting it run off the frame
    # or shrinking the image afterwards, which softens the text.
    # A left-hugged block starts at HOOK_X_LEFT, so it has that much less room
    # than a centred one — measuring against the centred width let the boxes
    # run off the right edge.
    max_w = HOOK_MAX_W
    if left:
        max_w = min(max_w, CANVAS_W - HOOK_X_LEFT - HOOK_EDGE_PAD)
    size = HOOK_FONT_SIZE
    while (max(r.width for r in rendered) + HOOK_PAD_X * 2) > max_w and size > 32:
        size -= 4
        try:
            bold_font = ImageFont.truetype(FONT_PATH, size)
            reg_font = ImageFont.truetype(FONT_PATH_REGULAR, size)
        except OSError:
            break
        rendered = [_rich_line_image(l, bold_font, reg_font) for l in lines]

    if style == "card":
        inner_w = max(r.width for r in rendered)
        inner_h = sum(r.height for r in rendered) + HOOK_PAD_Y // 2 * (len(rendered) - 1)
        card = Image.new("RGBA", (inner_w + HOOK_PAD_X * 2, inner_h + HOOK_PAD_Y * 2),
                         (255, 255, 255, 255))
        cy = HOOK_PAD_Y
        for r in rendered:
            card.paste(r, (HOOK_PAD_X, cy), r)
            cy += r.height + HOOK_PAD_Y // 2
        path = os.path.join(tmp_dir, _name("h"))
        card.save(path)
        x = HOOK_X_LEFT if left else (CANVAS_W - card.width) // 2
        top = y - card.height if bottom else y
        return [Overlay(path, int(x), int(top), 0.0, dur)]

    # "boxes": each line gets its own white box, so the right edge stays ragged
    boxes = []
    for r in rendered:
        box = Image.new("RGBA", (r.width + HOOK_PAD_X * 2, r.height + HOOK_PAD_Y),
                        (255, 255, 255, 255))
        box.paste(r, (HOOK_PAD_X, HOOK_PAD_Y // 2), r)
        path = os.path.join(tmp_dir, _name("h"))
        box.save(path)
        boxes.append((path, box.width, box.height))

    icon_path = _quote_icon(tmp_dir)
    icon_w, icon_h = Image.open(icon_path).size
    icon_gap = 22
    total = icon_h + icon_gap + sum(h for _, _, h in boxes) + \
        HOOK_LINE_GAP * (len(boxes) - 1)

    top = (y - total) if bottom else y
    overlays = [Overlay(icon_path,
                        int(HOOK_X_LEFT if left else (CANVAS_W - icon_w) // 2),
                        int(top), 0.0, dur)]
    cy = top + icon_h + icon_gap
    for path, w, h in boxes:
        overlays.append(Overlay(path,
                                int(HOOK_X_LEFT if left else (CANVAS_W - w) // 2),
                                int(cy), 0.0, dur))
        cy += h + HOOK_LINE_GAP
    return overlays


def _best_split(chunk, max_words, limit):
    """Where to cut a window that hit the word limit: the clearest pause in it.

    Fast continuous speech has no gap worth cutting on, and this returns the
    limit so the caption simply fills. When the speaker does breathe inside the
    window, cutting there keeps a phrase like "GAK USAH" from being sliced
    across two captions.
    """
    gaps = [chunk[i]["start"] - chunk[i - 1]["end"] for i in range(1, len(chunk))]
    cands = [(gaps[i - 1], i) for i in range(max_words, min(limit, len(chunk)))]
    if not cands:
        return limit
    best_gap, best_i = max(cands)
    median = sorted(gaps)[len(gaps) // 2]
    return best_i if best_gap > max(0.12, median * 1.6) else limit


def group_phrases(words, gap_split=PHRASE_GAP_SPLIT,
                  max_words=PHRASE_MAX_WORDS, max_lines=PHRASE_MAX_LINES):
    """Group a word list into caption phrases, split on natural pauses.

    A phrase ends where the speaker pauses (>= gap_split seconds). If it fills
    max_words * max_lines words first, it is cut at the clearest pause inside
    that window instead of exactly on the count, and the remainder carries into
    the next caption — nothing is dropped.
    Returns [{start, end, lines: [[word, ...], ...]}].
    """
    phrases = []
    limit = max_words * max_lines

    def emit(chunk):
        phrases.append({
            "start": chunk[0]["start"],
            "end": chunk[-1]["end"],
            "lines": [chunk[i:i + max_words] for i in range(0, len(chunk), max_words)],
        })

    cur = []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None or nxt["start"] - w["end"] >= gap_split:
            emit(cur)
            cur = []
        elif len(cur) >= limit:
            k = _best_split(cur, max_words, limit)
            emit(cur[:k])
            cur = cur[k:]
    if cur:
        emit(cur)
    return phrases


def _phrase_layer(words, clip_start, tmp_dir, accent_words=(), y_frac=PHRASE_Y_FRAC,
                  centred=True, max_lines=PHRASE_MAX_LINES):
    """Phrase captions (reference style): whole lines in one colour, left
    aligned, heavy black stroke, sitting inside the footage band.

    y_frac is the BOTTOM of the block: captions grow upward, so a one-line and
    a three-line phrase share a baseline and neither can spill past the band on
    a wide source.

    One PNG per phrase instead of one per word — a 60s clip drops from ~150
    overlay inputs to ~25, which is most of the render cost.
    """
    try:
        font = ImageFont.truetype(FONT_PATH, PHRASE_FONT_SIZE)
    except OSError:
        font = ImageFont.load_default()
    accent = {a.lower().strip(".,!?") for a in accent_words if a}
    pad = PHRASE_STROKE + 8
    max_w = CANVAS_W - 2 * PADDING if centred else (
        CANVAS_W - int(PHRASE_X_FRAC * CANVAS_W) - PADDING)
    overlays = []

    for ph in group_phrases(words, max_lines=max_lines):
        plain = [re.sub(r"[.,!?]", "", w["word"].upper()) for line in ph["lines"] for w in line]
        color = (PHRASE_ACCENT
                 if accent and any(p.lower() in accent for p in plain)
                 else PHRASE_COLOR)
        tiles = []
        for line in ph["lines"]:
            text = " ".join(re.sub(r"[.,!?]", "", w["word"].upper()) for w in line)
            text = censor.mask(text)
            img, _ = _mixed_text_image(text, font, color, stroke_width=PHRASE_STROKE)
            if img.width > max_w:  # very long word — shrink the whole line
                s = max_w / img.width
                img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))))
            tiles.append(img)
        block_w = max(t.width for t in tiles)
        block_h = sum(t.height for t in tiles) + PHRASE_LINE_GAP * (len(tiles) - 1)
        block = Image.new("RGBA", (block_w, block_h), (0, 0, 0, 0))
        cy = 0
        for t in tiles:
            # every tile carries the same padding, so centring on the block is
            # symmetric and needs no pad correction
            block.paste(t, ((block_w - t.width) // 2 if centred else 0, cy), t)
            cy += t.height + PHRASE_LINE_GAP
        path = os.path.join(tmp_dir, _name("p"))
        block.save(path)

        t_start = max(0.0, ph["start"] - clip_start)
        t_end = max(t_start + 0.3, ph["end"] - clip_start)
        x = ((CANVAS_W - block_w) // 2 if centred
             else int(PHRASE_X_FRAC * CANVAS_W) - pad)
        overlays.append(Overlay(path, x, int(y_frac * CANVAS_H - block_h),
                                t_start, t_end))
    return overlays


def _editorial_layer(words, clip_start, tmp_dir, accent_words=(),
                     x_frac=EDIT_X_FRAC, y_frac=EDIT_Y_FRAC):
    """Reference-clip captions: thin serif, no box, mixed roman/italic, and the
    punchline word set large — with the per-word karaoke highlight kept.

    Every word of the phrase is drawn in every frame of that phrase; only the
    colour of the word currently being spoken changes. An earlier cut dropped
    the words after the punchline, which made captions look like they were
    losing text mid-sentence.

    Layout is two lines: the phrase runs small on the top line, and the
    punchline word sits under it at EDIT_PUNCH_SIZE. That size jump is what
    makes the style read as designed rather than auto-captioned.
    """
    try:
        f_small = ImageFont.truetype(EDIT_FONT_SERIF, EDIT_SIZE)
        f_small_it = ImageFont.truetype(EDIT_FONT_SERIF_ITALIC, EDIT_SIZE)
        f_small_bold = ImageFont.truetype(EDIT_FONT_SERIF_BOLD, EDIT_SIZE)
        f_punch = ImageFont.truetype(EDIT_FONT_SERIF_BOLD, EDIT_PUNCH_SIZE)
    except OSError:
        return _phrase_layer(words, clip_start, tmp_dir, accent_words)

    # accent_words arrives from the model via metadata.generate, which already
    # filters to spoken words. Coerced again here because _editorial_layer is
    # also called directly (self-check, other callers), and a non-string item
    # would raise mid-render instead of simply not being accented.
    accent = {str(a).lower().strip(".,!?") for a in accent_words if a}
    max_w = CANVAS_W - int(x_frac * CANVAS_W) - PADDING
    overlays = []

    def tile(text, font, colour):
        """One word, transparent behind it — the plate is drawn per line."""
        bbox = font.getbbox(text)
        pad = EDIT_BOX_PAD
        img = Image.new("RGBA", (bbox[2] - bbox[0] + pad * 2,
                                 bbox[3] - bbox[1] + pad * 2), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # The stroke is the second line of defence: on footage bright enough to
        # wash out even the plate, black-on-white edges still hold the shape.
        d.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=colour,
               stroke_width=EDIT_STROKE, stroke_fill="black")
        return img

    for ph in group_phrases(words, max_lines=1, max_words=4):
        items = [w for line in ph["lines"] for w in line]
        toks = [censor.mask(re.sub(r"[.,!?]", "", w["word"])) for w in items]
        keep = [(t, w) for t, w in zip(toks, items) if t]
        if not keep:
            continue
        toks = [t for t, _ in keep]
        items = [w for _, w in keep]

        # Words the speaker audibly leaned on (emphasis.py), set apart from the
        # single punchline word. "mereka DISERANG terus MENERUS" needs both
        # stressed words marked, not just one.
        hot = {i for i, w in enumerate(items)
               if w.get("stress", 0) >= EMPH_THRESHOLD
               and re.sub(r"[^\w]", "", w["word"]).lower() not in emphasis.STOPWORDS
               and len(re.sub(r"[^\w]", "", w["word"])) > 2}
        # The big word is a LINE BREAK, not a highlight: everything before it
        # goes on the top line. So it can only ever be the LAST word of the
        # phrase. Picking a stressed word in the middle — "tadi saya inget
        # sudara" with "inget" enlarged — pushes word 4 up beside words 1-2 and
        # the caption reads out of order. Stress is already shown with caps, so
        # the break carries no emphasis duty and stays where reading order
        # demands. Two earlier attempts (any stressed word, then any stressed
        # word in the second half) both shipped scrambled captions.
        hit = len(toks) - 1

        for active in range(len(toks)):
            # top line: the whole phrase except the punchline, alternating
            # roman and italic so it never reads as one flat weight
            top = [(t, i) for i, t in enumerate(toks) if i != hit]
            tiles_top = []
            for n, (t, i) in enumerate(top):
                colour = ACTIVE_COLOR if i == active else "white"
                if i in hot:
                    # Stressed words go uppercase in the bold cut: the delivery
                    # is visible in the caption instead of being flattened.
                    tiles_top.append(tile(t.upper(), f_small_bold, colour))
                else:
                    tiles_top.append(
                        tile(t, f_small_it if n % 2 else f_small, colour))
            punch_text = toks[hit].upper() if hit in hot else toks[hit]
            punch = tile(punch_text, f_punch,
                         ACTIVE_COLOR if hit == active else "white")

            top_w = sum(t.width for t in tiles_top)
            top_h = max((t.height for t in tiles_top), default=0)
            # If the top line does not fit, WRAP it instead of letting the
            # paste loop below silently drop the overflow.
            #
            # That drop was real and expensive: emphasis.py uppercases stressed
            # words, so "-anaknya membawa kotak" became "-anaknya MEMBAWA
            # KOTAK" at 1003px against a 943px limit, and "kotak" — the word
            # the whole clip was about — never reached the frame. The operator
            # caught it by reading the caption ("Mana gibran ngomong kasih
            # bekal?"); nothing in the logs mentioned it, because dropping a
            # tile is not an error anywhere in this function.
            #
            # Caption text is not optional content. A phrase that cannot fit on
            # one line gets two.
            rows = [[]]
            row_w = [0]
            for t in tiles_top:
                if row_w[-1] + t.width > max_w and rows[-1]:
                    rows.append([])
                    row_w.append(0)
                rows[-1].append(t)
                row_w[-1] += t.width
            top_h = sum(max((t.height for t in r), default=0) for r in rows)
            top_w = max(row_w) if row_w else 0
            block_w = min(max_w, max(top_w, punch.width))
            block_h = top_h + EDIT_LINE_GAP + punch.height
            block = Image.new("RGBA", (max(1, block_w), block_h), (0, 0, 0, 0))

            # One plate per LINE, drawn before the words. Per-word plates left a
            # stepped, colliding silhouette where the big punchline met the
            # small line; a single rounded bar per line reads as deliberate.
            if EDIT_BOX_ALPHA:
                d = ImageDraw.Draw(block)
                y = 0
                for r, rw in zip(rows, row_w):
                    if not r:
                        continue
                    rh = max(t.height for t in r)
                    d.rounded_rectangle([(0, y), (min(rw, block_w) - 1, y + rh - 1)],
                                        radius=EDIT_BOX_RADIUS,
                                        fill=(0, 0, 0, EDIT_BOX_ALPHA))
                    y += rh
                d.rounded_rectangle([(0, block_h - punch.height),
                                     (punch.width - 1, block_h - 1)],
                                    radius=EDIT_BOX_RADIUS,
                                    fill=(0, 0, 0, EDIT_BOX_ALPHA))

            y = 0
            for r in rows:
                if not r:
                    continue
                cx = 0
                for t in r:
                    block.paste(t, (cx, y), t)
                    cx += t.width
                y += max(t.height for t in r)
            block.paste(punch, (0, block_h - punch.height), punch)

            path = os.path.join(tmp_dir, _name("e"))
            block.save(path)
            t_start = max(0.0, items[active]["start"] - clip_start)
            nxt = (items[active + 1]["start"] if active + 1 < len(items)
                   else items[active]["end"])
            t_end = max(t_start + 0.1, nxt - clip_start)
            overlays.append(Overlay(path, int(x_frac * CANVAS_W),
                                    int(y_frac * CANVAS_H), t_start, t_end))
    return overlays


def _karaoke_layer(words, clip_start, tmp_dir, sub_y=SUB_Y):
    """Karaoke captions as timed overlays.

    Each (chunk, active-word) state is flattened into ONE image rather than one
    per word, so a clip carries a third of the overlay inputs.
    """
    try:
        font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    except OSError:
        font = ImageFont.load_default()
    max_w = CANVAS_W - PADDING * 2
    overlays = []
    chunks = [words[i:i + 3] for i in range(0, len(words), 3)]
    for chunk in chunks:
        for i_w, active in enumerate(chunk):
            w_start = max(0.0, active["start"] - clip_start)
            nxt = chunk[i_w + 1]["start"] if i_w + 1 < len(chunk) else active["end"]
            w_end = max(w_start + 0.1, nxt - clip_start)

            tiles, widths = [], []
            for j, w_item in enumerate(chunk):
                text = re.sub(r"[.,!?]", "", w_item["word"].upper())
                text = censor.mask(text)
                color = ACTIVE_COLOR if i_w == j else "white"
                img, tw = _mixed_text_image(text, font, color, stroke_width=STROKE)
                tiles.append(img)
                widths.append(tw)

            total = sum(widths) + SPACING * (len(tiles) - 1)
            scale = min(1.0, max_w / total) if total else 1.0
            if scale < 1.0:
                tiles = [t.resize((max(1, int(t.width * scale)),
                                   max(1, int(t.height * scale)))) for t in tiles]
                widths = [w * scale for w in widths]
                total = max_w

            height = max(t.height for t in tiles)
            line_img = Image.new("RGBA", (int(total) + 2 * int((STROKE + 8) * scale),
                                          height), (0, 0, 0, 0))
            pad = int((STROKE + 8) * scale)
            x = 0
            for j, t in enumerate(tiles):
                line_img.paste(t, (int(x), (height - t.height) // 2), t)
                x += widths[j] + SPACING * scale
            path = os.path.join(tmp_dir, _name("k"))
            line_img.save(path)
            overlays.append(Overlay(path, int((CANVAS_W - total) / 2) - pad,
                                    sub_y, w_start, w_end))
    return overlays


_GRAPH_FLAG = None


def _graph_flag():
    """Which flag this ffmpeg uses to read a filter graph from a file.

    ffmpeg 8 dropped -filter_complex_script for the generic -/filter_complex,
    so a box that updates ffmpeg fails every render with "Unrecognized option"
    and nothing else to go on. The graph has to come from a file either way
    (see the argument-length note in render_clip), so the only question is the
    spelling. Ask the binary once rather than guessing from a version string:
    distro builds and static builds disagree about what a version means.
    """
    global _GRAPH_FLAG
    if _GRAPH_FLAG is None:
        try:
            out = subprocess.run([FFMPEG, "-h", "full"], capture_output=True,
                                 text=True, timeout=30).stdout
        except Exception:
            out = ""
        _GRAPH_FLAG = ("-filter_complex_script" if "filter_complex_script" in out
                       else "-/filter_complex")
    return _GRAPH_FLAG


def _zoom_parts(dur, fps):
    """Shared zoompan bits: the frame budget and the zoom-factor expression."""
    n = max(1, int(dur * fps))
    if ZOOM_CYCLE > 0:
        # A single slow push across 80s is invisible — the frame moves a few
        # pixels a second. Cycling in and out on a fixed period is the movement
        # the reference clips actually have: it reads as a live camera rather
        # than a still. Half a cosine period gives in-and-back-out per cycle.
        span = ZOOM - 1.0
        z = (f"1+{span / 2:.4f}-{span / 2:.4f}"
             f"*cos(2*PI*on/{max(1, int(ZOOM_CYCLE * fps))})")
    else:
        z = f"min(1+{ZOOM - 1:.4f}*on/{n},{ZOOM:.4f})"
    return n, z


def _mood_words(mood):
    """Mood as a list of lowercase words, whatever shape the caller passed.

    bgm.pick() returns a track whose "mood" is a LIST (a file can carry several
    mood words), and job.py forwards that straight through. `str(["emotional"])`
    is `"['emotional']"`, which matched nothing, so every clip with music fell
    through to the stinger branch: a grief clip about Palestinians being killed
    shipped with 20 white flashes in its final five seconds, twice, while the
    settings all read correctly in Python. Accepting both shapes here is the fix;
    the lesson is that a silent fallback on a mood mismatch is the bug, which is
    why _outro_kind now warns instead of guessing.
    """
    if mood is None:
        return []
    if isinstance(mood, str):
        items = [mood]
    elif isinstance(mood, (list, tuple, set)):
        items = list(mood)
    else:
        items = [mood]
    return [str(m).strip().lower() for m in items if str(m).strip()]


def _outro_kind(mood=None):
    """Which ending this clip gets: "stinger", "melancholy", "jamet" or "none".

    CLIPPER_OUTRO forces one; the default "auto" reads the mood. A clip about
    people being killed closes quietly whatever the platform convention says —
    the stinger belongs to outrage and hype, not to grief.

    "jamet" is the TikTok edit: freeze the frame, then shake it on the beat.
    It is never chosen by "auto", because it is a strong stylistic claim about
    the subject — funny on a politician's slip, grotesque on a funeral. The
    operator asks for it per clip.
    """
    choice = (OUTRO or "").strip().lower()
    if choice in ("0", "false", "no", "none", "off"):
        return "none"
    if choice in ("stinger", "flash", "1", "true", "yes"):
        return "stinger"
    if choice in ("melancholy", "sad", "fade"):
        return "melancholy"
    if choice in ("jamet", "tiktok", "shake", "freeze"):
        return "jamet"
    # auto
    words = _mood_words(mood)
    if any(w in OUTRO_SAD_MOODS for w in words):
        return "melancholy"
    if not words:
        # No mood at all is a real case (no music, no transcript signal) and the
        # stinger is the documented default. Only warn when a mood was supplied
        # and simply did not match: that is the shape bug above, and it must not
        # be silent — the wrong ending is a register error, not a cosmetic one.
        return "stinger"
    if not any(w in _OUTRO_KNOWN_MOODS for w in words):
        sys.stderr.write(
            f"edit: unrecognised mood {words!r}; defaulting to the stinger "
            f"ending. Add it to OUTRO_SAD_MOODS if this clip should close "
            f"quietly.\n")
    return "stinger"


def _outro_start(dur, mood=None, seconds=None):
    """Where the closing treatment begins, or None when there is no ending.

    Mirrors the span logic in _outro_filters so callers do not duplicate it.
    The caption chain needs this because overlay windows come from the
    transcript and would otherwise animate on top of a frozen frame.
    """
    kind = _outro_kind(mood)
    span = float(seconds if seconds is not None else OUTRO_SECONDS)
    if kind == "jamet" and seconds is None:
        span = OUTRO_JAMET_SECONDS
    if kind == "none" or span <= 0 or dur < span * 3:
        return None
    return max(0.0, dur - span)


def _outro_filters(dur, mood=None, seconds=None):
    """(brightness_term, extra_filters) for the closing treatment.

    The brightness term joins the beat-flash expression in one `eq`; the extra
    filters are appended to the video chain. Both are "" / [] when the clip is
    too short to give the ending its own space — a treatment covering most of
    the clip is not an ending.
    """
    kind = _outro_kind(mood)
    span = float(seconds if seconds is not None else OUTRO_SECONDS)
    # The jamet ending is a freeze plus a shake, not a ramp, so it reads in a
    # fraction of the time the melancholy fade needs. Holding it to the same
    # 8s span silently dropped the whole outro from a 22s clip — the operator
    # asked for "muka gibrannya di stop jadi image terus goyang" and got a
    # plain cut, with nothing in the ledger but "edit DID NOT RUN".
    if kind == "jamet" and seconds is None:
        span = OUTRO_JAMET_SECONDS
    if kind == "none" or span <= 0 or dur < span * 3:
        return "", []
    start = max(0.0, dur - span)

    if kind == "stinger":
        count = max(2, int(round(span * OUTRO_RATE)))
        terms = []
        for i in range(count):
            # Quadratic spacing: the gaps tighten toward the end of the run.
            t = start + ((i / count) ** 0.82) * span
            b = min(dur, t + OUTRO_HOLD)
            if b > t:
                terms.append(
                    f"{OUTRO_AMOUNT:.3f}*between(t,{t:.3f},{b:.3f})"
                    f"*pow(1-(t-{t:.3f})/{b - t:.4f},2)")
        return "+".join(terms), []

    if kind == "jamet":
        # Freeze, then shake on the beat. `loop` clones one frame N times
        # rather than re-timestamping it: setpts-based freezing produced
        # duplicate DTS ("non monotonically increasing dts to muxer") and the
        # encoder dropped frames, which is not a thing to discover on a render.
        #
        # The shake is a crop window moved by two out-of-phase sines, then
        # scaled back to canvas. Scaling the picture instead (a zoom pulse)
        # changes the output dimensions per frame, and 1080x1920 is not
        # negotiable here — the operator's rule is that resolution never moves
        # to buy a look.
        # The freeze runs to the END of the clip, not for a fixed 2s.
        #
        # `loop` INSERTS its clones into the stream: the tail of the real
        # footage still follows them. With OUTRO_FREEZE=2.0 on a 31.8s clip the
        # still occupied 28.80-30.80s and then the video started playing again
        # for the last 3s — measured on the delivered file, frame-difference
        # motion 8.2-24.8 after 30.80s where a still reads 0. The operator:
        # "harusnya videonya pause sampe akhir".
        #
        # Cloning (dur - start) seconds instead means the clones alone fill the
        # rest of the clip, and the real tail is pushed past the end where the
        # encoder's -t drops it. OUTRO_FREEZE is kept as a FLOOR so a clip
        # whose ending is shorter than one freeze still gets a readable still.
        freeze_secs = max(OUTRO_FREEZE, dur - start)
        frames = max(1, int(round(freeze_secs * FPS)))
        pad = OUTRO_SHAKE_PX
        # The shake runs ON the frozen frame, not after it. `loop` inserts
        # `frames` copies of one frame at `start`, so the still occupies
        # start .. start+freeze_secs on the output timeline.
        #
        # This used to read `start + OUTRO_FREEZE`, which put the shake in the
        # moving video that follows the still — so the picture stopped, sat
        # there motionless, and only then started shaking once it was playing
        # again. The operator's spec is the opposite and is the actual
        # jedag-jedug convention: "videonya dah ga di play, jadi image gitu",
        # the beats land on the still.
        shake_from = start
        # The shake window has to cover the whole frozen stretch, which now
        # runs to the end of the clip. Keyed to freeze_secs rather than the
        # OUTRO_FREEZE constant: with the constant it stopped at 30.80s and the
        # last 3s of the still sat motionless.
        end = start + freeze_secs
        win = f"between(t,{shake_from:.3f},{end:.3f})"
        # One beat period. The shake is keyed to the track, not to taste:
        # 1.923 Hz is the measured onset rate of the supplied jedag-jedug song
        # (115.4 BPM), so one hit lands on every beat.
        period = 1.0 / max(0.1, OUTRO_SHAKE_HZ * OUTRO_PUNCH_PER_BEAT)
        # Phase inside the current beat, 0 at the hit, 1 just before the next.
        ph = f"mod(t-{shake_from:.3f},{period:.5f})/{period:.5f}"
        # Beat index, used to flip direction so consecutive hits do not drift
        # the picture in one direction.
        idx = f"floor((t-{shake_from:.3f})/{period:.5f})"
        flip = f"(1-2*mod({idx},2))"
        # Sharp attack, fast decay. This is the whole difference between
        # "jedag-jedug" and "slow drift": a sine spends most of its time near
        # the middle of its travel, so the frame-to-frame change is small and
        # even. Measured against the reference short the operator sent
        # (youtube.com/shorts/twn4fIJ0PUk, 12.3s, 307 frames): the reference
        # hits 122 frames above 6.0 motion with a median of 4.29 and peaks at
        # 28.4, while the sine version of this outro managed 7.7 at its best
        # and read as a gentle slide. exp(-k*phase) puts the whole excursion in
        # the first fifth of each beat, which is what a punch looks like.
        env = f"exp(-{OUTRO_PUNCH_DECAY:.2f}*({ph}))"
        # The zoom punch, done by shrinking the crop WINDOW and scaling back to
        # canvas. Scaling the picture itself would change the output dimensions
        # per frame, and 1080x1920 never moves to buy a look.
        # crop's w and h are evaluated ONCE when the filter is configured, so
        # they cannot contain `t` — ffmpeg fails the pad with "Error when
        # evaluating the expression" and the render dies after the download and
        # transcribe are already paid for. Verified directly:
        #     crop=w='iw-56-(70*exp(-8*mod(t,0.52)))'  -> rejected
        #     crop=w=iw-56:x='...exp(-8*mod(t,0.52))'  -> accepted
        # Only x and y are per-frame. The zoom punch therefore goes through
        # zoompan, which has its own per-frame `time` variable, and the crop
        # window stays a fixed size and only MOVES.
        cw = f"iw-{2 * pad:.0f}"
        ch = f"ih-{2 * pad:.0f}"
        # The zoom punch goes through scale with eval=frame, NOT zoompan.
        # zoompan is accepted by the parser but is pathologically slow here: it
        # re-initialises its scaler every frame at 1080x1920, and a 22s clip
        # that renders in ~100s did not finish in 400s with zoompan in the
        # chain. Measured on this box, 3s of synthetic video: both filters cost
        # ~0.3s, so the blowup only shows at real resolution and length —
        # benchmark the real thing, not a toy.
        #
        # scale=w=...:eval=frame re-evaluates per frame and is cheap; cropping
        # back to canvas afterwards keeps 1080x1920 exactly, which is the rule
        # that never bends.
        zoom = (f"1+{OUTRO_PUNCH_ZOOM:.3f}*{env}*{win}")
        return "", [
            f"loop=loop={frames}:size=1:start={int(round(start * FPS))}",
            # loop INSERTS its clones, so the clip grows by freeze_secs and the
            # real tail is pushed after the still instead of being replaced by
            # it. Measured on the first attempt at this fix: the clip ran
            # 34.83s instead of 31.81s and the last 3s was moving video again
            # (frame-difference 4-17 with no per-beat decay, against 0.4-0.9
            # inside the frozen stretch). Cutting the stream back to `dur`
            # drops exactly that tail and leaves the still holding to the end.
            f"trim=end={dur:.3f}",
            "setpts=PTS-STARTPTS",
            (f"crop=w={cw}:h={ch}"
             f":x='(iw-ow)/2+{pad:.0f}*{flip}*{env}*{win}'"
             f":y='(ih-oh)/2+{pad * 0.6:.0f}*{flip}*{env}*{win}':exact=1"),
            (f"scale=w='{CANVAS_W}*({zoom})':h='{CANVAS_H}*({zoom})'"
             f":eval=frame"),
            f"crop={CANVAS_W}:{CANVAS_H}",
            "setsar=1",
            f"fps={FPS}",
        ]

    # melancholy: colour drains and the image dims, both ramping across the
    # window. `hue` evaluates its expressions per frame already — it is marked
    # timeline-capable, and unlike `eq` it has no `eval` option at all. Passing
    # one is not a no-op: ffmpeg 6.1 rejects the whole filter graph with
    # "Option not found", which killed a render after the download and
    # transcribe had already been paid for.
    ramp = f"min(1,max(0,(t-{start:.3f})/{span:.4f}))"
    bright = f"-{OUTRO_DIM:.3f}*{ramp}" if OUTRO_DIM > 0 else ""
    desat = []
    if OUTRO_DESAT > 0:
        desat.append(f"hue=s='1-{OUTRO_DESAT:.3f}*{ramp}'")
    if OUTRO_VIGNETTE > 0:
        # `vignette` needs eval=frame to re-read the expression per frame;
        # without it the angle is evaluated once at init and the ramp is a
        # constant. Unlike `hue`, this filter DOES accept eval — the two are
        # not interchangeable, and assuming they were cost a whole render.
        desat.append(
            f"vignette=a='{OUTRO_VIGNETTE:.4f}*{ramp}':eval=frame")
    if OUTRO_GRAIN > 0:
        # No ramp: `noise` takes no time expression. Applied flat over the
        # whole clip it would be visible from frame one, so it is gated by
        # enable=, which every filter supports regardless of eval.
        desat.append(
            f"noise=alls={OUTRO_GRAIN:.0f}:allf=t:enable='gte(t,{start:.3f})'")
    if 0 < OUTRO_SLOWMO < 1:
        # Stretch presentation timestamps from `start` onward. Frames before the
        # window keep their own timestamps, so only the ending slows down.
        #
        # Video only, deliberately: slowing the audio would detune the speech
        # and drift it out of sync with the captions, which are burned in at
        # the original times. The clip therefore runs slightly longer than its
        # audio and the last word lands before the final frame, which is the
        # intended held beat.
        factor = 1.0 / OUTRO_SLOWMO
        desat.append(
            f"setpts='if(lt(T,{start:.3f}),PTS,"
            f"({start:.3f}/TB)+(PTS-{start:.3f}/TB)*{factor:.4f})'")
    if OUTRO_FADE > 0:
        # Placed last, after setpts, because fade works on the timeline it
        # receives: the slow-motion above stretches the tail, so the clip's
        # real end is later than `dur`. Computing st= from `dur` would start
        # the fade early and finish it before the final frame.
        #
        # Note which timeline that is. These filters attach to [0:v], the
        # speech segment BEFORE the intro is concatenated in front (see the
        # call site), so every number here is segment-relative. An 82s segment
        # with a 7s intro delivers a 92.4s file whose dip lands at 91.2-92.4 —
        # still the end of the clip, because the intro only shifts it. Do not
        # "fix" this by adding intro_dur: that would push the fade past the
        # end of the stream it is applied to.
        end = start + (span / OUTRO_SLOWMO) if 0 < OUTRO_SLOWMO < 1 else dur
        # Finish the fade slightly BEFORE the last frame, not on it. Ending it
        # exactly at `end` left the final frame at Y=21 (dark grey) rather than
        # black: fade reaches zero only at st+d, so the last rendered frame is
        # always a hair above it, and the reviewer measured that. Landing the
        # fade early gives a few frames of held black to close on.
        st = max(start, end - OUTRO_FADE - OUTRO_FADE_LEAD)
        desat.append(f"fade=t=out:st={st:.3f}:d={OUTRO_FADE:.3f}:c=black")
    return bright, desat


def _outro_expr(dur, mood=None, seconds=None):
    """Brightness-only view of the outro, kept for callers that want the term."""
    return _outro_filters(dur, mood=mood, seconds=seconds)[0]


def _flash_expr(times, dur):
    """An `eq` brightness term that pops white briefly at each time, or "".

    A flash is a brightness pulse, not a pasted white image: an overlay PNG has
    fixed alpha, so fading one in and out means generating frames, while `eq`
    evaluates an expression per frame for free. Shaped as a sharp attack and a
    slower fall, which is what a camera flash does — a symmetric bump reads as
    a lighting error instead of a beat.

    Separate from punch-in by design: the grammar is hard cut, then punch-in,
    then flash. Flashes are capped harder because they interrupt the image,
    and they only ever land where a punch already landed, so the clip never
    gains a beat that the audio did not have.
    """
    if not FLASH or not times:
        return ""
    terms = []
    for t in times[:FLASH_MAX]:
        # between() gates it; the ramp runs 1 -> 0 across FLASH_HOLD seconds.
        a = max(0.0, t - FLASH_HOLD / 2)
        b = min(dur, a + FLASH_HOLD)
        if b <= a:
            continue
        terms.append(f"{FLASH_AMOUNT:.3f}*between(t,{a:.3f},{b:.3f})"
                     f"*pow(1-(t-{a:.3f})/{b - a:.4f},2)")
    if not terms:
        return ""
    return "+".join(terms)


def _punch_times(words, clip_start, dur, threshold=EMPH_THRESHOLD):
    """Clip-relative times of the words worth punching in on.

    The cut has to land on a real beat or it reads as a mistake, so the beat
    comes from the same stress scores the captions use — loudness and pace,
    not a timer.

    Spacing is CLUSTERED, not even. Measured off the operator's reference
    tutorial (AGv6G13TPUc), frame-difference motion per second:

        reference, body of clip      18.4 mean, peaks to 70.6
        our render, body of clip     10.7 mean, peaks to 34.6

    The reference's hits arrive in bursts of 1-3 inside about half a second,
    then leave a 2-4s gap: five bursts in 13.5s. A flat PUNCH_MIN_GAP of 9s
    cannot produce that shape at all — on a 31.8s clip with 27 qualifying
    beats it kept 3, none in the first 4.7s, and the operator's reading was
    "efeknya kurang sebelum jedag jedug".

    So two gaps: beats within PUNCH_BURST_GAP of a kept beat may join its
    burst (up to PUNCH_BURST), and a new burst needs PUNCH_MIN_GAP of clear
    air. The quiet stretches are the point — they are what makes the next
    burst land, and "not every beat needs a cut" still holds.

    Returns [] when nothing qualifies, which is a valid outcome: a clip with
    no vocal emphasis should not be given invented emphasis.
    """
    if not PUNCH or dur <= 0:
        return []
    scored = []
    for item in words or ():
        if float(item.get("stress") or 0.0) < threshold:
            continue
        t = float(item.get("start") or 0.0) - clip_start
        if 0.5 <= t <= dur - 0.5:
            scored.append((t, float(item["stress"])))
    if not scored:
        return []

    # Strongest first, so when two beats are too close the louder one wins and
    # becomes the burst's anchor.
    scored.sort(key=lambda p: -p[1])

    bursts = []   # [[anchor_t, ...]] in selection order
    kept = []
    for t, _score in scored:
        if len(kept) >= PUNCH_MAX:
            break
        joined = False
        for burst in bursts:
            if len(burst) >= PUNCH_BURST:
                continue
            if any(abs(t - b) <= PUNCH_BURST_GAP for b in burst):
                # Close to this burst: it extends it rather than starting one.
                burst.append(t)
                kept.append(t)
                joined = True
                break
        if joined:
            continue
        # A new burst has to clear every existing beat by the long gap,
        # otherwise bursts smear into continuous shaking.
        if all(abs(t - k) >= PUNCH_MIN_GAP for k in kept):
            bursts.append([t])
            kept.append(t)
    return sorted(kept)


def _punch_expr(times, fps):
    """A zoom-factor term that adds a brief tighter crop at each time.

    Shaped as a sum of cosine bumps rather than a step: an instant scale jump
    on one frame reads as a glitch, while a ~PUNCH_HOLD ramp reads as a camera
    move. Each bump is zero outside its own window, so they add without
    interacting, and the expression stays valid for zoompan's single-pass
    evaluator (no state, no branches beyond between()).
    """
    half = max(1, int(PUNCH_HOLD * fps / 2))
    terms = []
    for t in times:
        c = int(t * fps)
        a, b = c - half, c + half
        # between() gates the bump; the cosine runs 0 -> 1 -> 0 across it.
        terms.append(f"{PUNCH_AMOUNT:.4f}*between(on,{a},{b})"
                     f"*(0.5-0.5*cos(2*PI*(on-{a})/{2 * half}))")
    return "+".join(terms)


def _zoompan(dur, fps=FPS, words=None, clip_start=0.0, frame_mode=None):
    """Centred push-in (no tracking), or None when zoom is off.

    The footage is normalised to `fps` first so the zoom spreads evenly across
    the full clip whatever the source's native rate: `on` then counts output
    frames at a known speed, and the target factor is reached exactly on the
    last frame. 1.0 is no zoom; a higher ZOOM pushes in that many percent.

    Punch-ins ride on top of the base zoom instead of replacing it, so the
    clip keeps its slow drift and gains a tighter crop on stressed words.

    In "pillar" framing the base zoom is skipped. Pillar exists to show the
    whole 16:9 frame that `cover` was cutting, and this pass runs AFTER the
    pillar composite — so CLIPPER_ZOOM=1.2 cropped the finished card and put
    the sliced banner and the cut-off face straight back. Measured on the
    first pillar render: the news chyron read "...RAL GIBRAN SARANKAN SISWA
    BAWA BEKAL DARI RUM..." with both ends gone. Punch-ins still apply; they
    are brief and intentional, not a standing crop.

    `frame_mode` must be passed by the caller. Reading the module-level
    FRAME_MODE here was wrong and silently so: that constant is the .env
    default ("cover"), while --frame-mode travels as a function argument, so
    `pillar` renders kept the base zoom and two consecutive "fixed" renders
    came out byte-identical. Defaults to the module constant only when the
    caller has nothing better.
    """
    if frame_mode is None:
        frame_mode = FRAME_MODE
    punch = _punch_expr(_punch_times(words, clip_start, dur), fps)
    if ZOOM <= 1.0 or frame_mode == "pillar":
        if not punch:
            return None
        # No base zoom, but punches still need a zoompan pass to live in.
        return (f"fps={fps},"
                f"zoompan=z='1+{punch}':"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d=1:fps={fps}:s={CANVAS_W}x{CANVAS_H}")
    _n, z = _zoom_parts(dur, fps)
    if punch:
        z = f"{z}+{punch}"
    return (f"fps={fps},"
            f"zoompan=z='{z}':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d=1:fps={fps}:s={CANVAS_W}x{CANVAS_H}")


def _cover_rect(W, H):
    """The source-pixel rectangle the 9:16 'cover' crop keeps."""
    s = max(CANVAS_W / W, CANVAS_H / H)
    return ((W * s - CANVAS_W) / (2 * s), (H * s - CANVAS_H) / (2 * s),
            CANVAS_W / s, CANVAS_H / s)


# How far the tracked face may move between pan samples, as a fraction of the
# source width. A real head crossing the frame takes seconds; a jump bigger
# than this is the detector swapping to a different person.
#
# MEASURED, not chosen. Mean error against hand-checked subject positions on
# the Gibran scrum (t=122/140/146):
#
#     0.12   0.216   too tight: rejects the subject's own re-entry after the
#                    gap where he is undetected, so the track sits at 0.73
#     0.20   0.110   best
#     0.25   0.110   same track, no extra samples accepted
#     0.30   0.147   loose enough to follow a bystander at t=140
#
# Tighter is not safer here: a rejected sample is not a centred frame, it is a
# stale position held over, which is how a 0.12 limit kept the crop on the
# escort for the whole clip.
PAN_JUMP = float(os.environ.get("CLIPPER_PAN_JUMP", "0.20"))


def _pan_anchor(video_path, start, end, step=1.0):
    """Deliberately unused: kept as a record of an approach that measured worse.

    The idea was to find the subject by position over the whole segment rather
    than trusting one frame. Both scorings — frames-present and area-weighted —
    picked bin 0.8, which is the escort, and panning from there put the subject
    off-frame for 0 of 49 samples against 55% before. Spatial voting cannot
    identify a person when the camera itself moves: the subject genuinely
    travels 0.75 -> 0.37 across this segment, so "where faces usually are" is
    the crowd, not him.

    What actually works is tracking continuity from the first clear detection
    (see _sample_pan_faces), because the subject is the face that PERSISTS
    between consecutive frames while the crowd churns.
    """
    return None


def _face_hist(img):
    """Coarse hue/saturation signature of a face crop, for re-identification.

    Not face recognition — just enough appearance to tell "the person I was
    following" from "a different person standing where he used to be". Shirt
    colour, skin tone and hair all land in here, which is what distinguishes a
    subject in a white shirt from an escort in camouflage.
    """
    import cv2
    h = cv2.calcHist([cv2.cvtColor(img, cv2.COLOR_BGR2HSV)], [0, 1], None,
                     [30, 32], [0, 180, 0, 256])
    return cv2.normalize(h, h).flatten()


def _sample_pan_faces(video_path, start, end, step=PAN_STEP, anchor=None):
    """[(t, cx)] the speaker's face centre as a fraction of the FULL source width.

    Detection runs on the whole frame rather than the centre crop, which is the
    point: on a 16:9 source the crop keeps only the middle third, so a wide
    two-shot has both speakers outside it and nothing to track.

    Picking the LARGEST face per frame is right on a framed shot and shaky in
    a press scrum: on the Gibran clip the detector saw up to 11 faces, and the
    biggest was sometimes whoever leaned nearest the lens.

    Measured against five hand-checked subject positions (t=122/132/140/146/
    150) — mean absolute error:

        largest face per frame                     0.094
        appearance match + position + area         0.079
        position tracking, no appearance           0.221  (drifts to 0.73)
        spatial voting over the segment            worse   (locks to escort)

    Appearance is what carries identity across the frames where the subject is
    undetected (t=134, t=140 here); position alone lets the track settle on
    whoever is nearest when detection resumes.

    Honest caveat: the first three checked points suggested 0.344 vs 0.110, and
    two further points cut that to 0.094 vs 0.079. The tracker is a small, real
    improvement — it was NOT the reason the operator got a clip of the wrong
    person. That was a centred crop window (see _pillar_pan_x).

    The template updates slowly (0.8/0.2) so lighting drift does not accumulate
    into a lost subject, and a frame whose best candidate moved more than
    PAN_JUMP is skipped rather than guessed — the caller's smoothing
    interpolates across it.
    """
    try:
        import cv2
    except ImportError:
        return []
    if not os.path.exists(FACE_MODEL):
        return []
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []
    try:
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if W <= 0 or H <= 0:
            return []
        # Detect on a downscaled copy: face centres are wanted, not pixels, and
        # a 2560-wide frame costs several times more for the same answer.
        scale = min(1.0, 960.0 / W)
        dw, dh = int(W * scale), int(H * scale)
        det = cv2.FaceDetectorYN_create(FACE_MODEL, "", (dw, dh), 0.6, 0.3, 5000)
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        every = max(1, int(round(src_fps * step)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(start * src_fps))
        pts = []
        track = anchor
        tpl = None
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = idx / src_fps
            if start + t >= end:
                break
            if idx % every == 0:
                small = cv2.resize(frame, (dw, dh)) if scale < 1.0 else frame
                _ok, faces = det.detect(small)
                cand = []
                if faces is not None:
                    for f in faces:
                        x, y = int(max(0, f[0])), int(max(0, f[1]))
                        w, h = int(max(0, f[2])), int(max(0, f[3]))
                        crop = small[y:y + h, x:x + w]
                        if crop.size == 0:
                            continue
                        cand.append(((x + w / 2.0) / dw, float(w * h),
                                     _face_hist(cv2.resize(crop, (48, 48)))))
                if cand:
                    big = max(a for _c, a, _h in cand) or 1.0
                    if track is None or tpl is None:
                        cx, _a, tpl = max(cand, key=lambda p: p[1])
                        track = cx
                        pts.append((t, cx))
                    else:
                        def score(p):
                            cx, area, hs = p
                            return (cv2.compareHist(tpl, hs, cv2.HISTCMP_CORREL)
                                    - abs(cx - track)
                                    + 0.3 * (area / big))

                        cx, _a, hs = max(cand, key=score)
                        if abs(cx - track) <= PAN_JUMP:
                            # Ease toward the detection instead of snapping to
                            # it, so one bad frame cannot drag the track.
                            track += (cx - track) * 0.6
                            tpl = 0.8 * tpl + 0.2 * hs
                            pts.append((t, track))
            idx += 1
        return pts
    except cv2.error:
        return []
    finally:
        cap.release()


def _pan_keys(pts, win_frac):
    """[(t, centre)] keyframes for the crop window, as source-width fractions.

    Turns raw per-sample face positions into camera moves. A face drifting
    inside PAN_DEADZONE of the window is ignored, so a speaker shifting in
    their chair does not drag the frame. A face outside it has to stay outside
    for PAN_HOLD seconds before the camera commits, which filters out a head
    turning or a one-sample false positive. The move itself is spread over
    PAN_SLIDE seconds, so it reads as a pan rather than a cut.
    """
    half = win_frac / 2.0
    lo, hi = half, 1.0 - half
    if lo >= hi:                      # window is the whole frame: nothing to pan
        return []
    clamp = lambda v: min(hi, max(lo, v))
    cur = clamp(pts[0][1])
    keys = [(0.0, cur)]
    pending_since = None
    for t, fx in pts:
        want = clamp(fx)
        if abs(want - cur) <= PAN_DEADZONE * win_frac:
            pending_since = None
            continue
        if pending_since is None:
            pending_since = t
            pending_to = want
            continue
        pending_to = want             # track the latest reading while waiting
        if t - pending_since < PAN_HOLD:
            continue
        if t <= keys[-1][0]:          # still mid-slide; let it land first
            continue
        keys.append((t, cur))
        cur = pending_to
        keys.append((t + PAN_SLIDE, cur))
        pending_since = None
    return keys


def _pan_expr(keys):
    """Piecewise-linear ffmpeg expression in `t` for the crop-window centre."""
    if len(keys) == 1:
        return f"{keys[0][1]:.4f}"
    expr = f"{keys[-1][1]:.4f}"
    for i in range(len(keys) - 2, -1, -1):
        t0, v0 = keys[i]
        t1, v1 = keys[i + 1]
        if abs(v1 - v0) < 1e-6:
            expr = f"if(lt(t,{t1:.3f}),{v0:.4f},{expr})"
        else:
            expr = (f"if(lt(t,{t1:.3f}),{v0:.4f}+({v1 - v0:.4f})"
                    f"*(t-{t0:.3f})/{t1 - t0:.4f},{expr})")
    return expr


def _pan_cover(video_path, start, end):
    """A 'cover' filter whose crop window follows the speaker, or None.

    Same scale and same 9:16 crop size as the static cover — only the window's
    x position varies with time. The aspect ratio is untouched; the clip just
    stops keeping the middle of the frame when the speaker is not in it.
    """
    if not PAN:
        return None
    try:
        import cv2
    except ImportError:
        return None
    cap = cv2.VideoCapture(video_path)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if cap.isOpened() else 0
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if cap.isOpened() else 0
    cap.release()
    if W <= 0 or H <= 0:
        return None
    s = max(CANVAS_W / W, CANVAS_H / H)
    win_frac = CANVAS_W / (W * s)
    if win_frac >= 0.999:             # already vertical: no room to pan
        return None
    pts = _sample_pan_faces(video_path, start, end)
    if not pts:
        return None
    keys = _pan_keys(pts, win_frac)
    if not keys:
        return None
    x = _pan_expr(keys)
    return (f"scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase,"
            f"crop={CANVAS_W}:{CANVAS_H}:x='iw*({x})-ow/2':y='(ih-oh)/2'")


def _static_window_x(pts, win_frac):
    """One fixed crop position that frames the subject in the most samples.

    Used when PAN is off: the camera must not move, but it also must not sit
    on the wrong half of a wide shot.

    Counting "subject inside the window" alone is not enough to place it. Any
    window that contains him at all scores identically, so a subject parked at
    0.74 accepted a window centred at 0.53 — technically inside, but he sits
    on the very edge of frame, which is the composition the operator rejected.
    The score is therefore how CENTRED he is: the mean squared distance from
    the subject to the window centre, minimised. Samples outside the window
    are clamped to its edge so a brief excursion costs something but does not
    dominate.

    Ties go to the centremost option, since nothing is gained by shifting off
    centre for an equal score.

    Returns an ffmpeg crop-x expression in source pixels.
    """
    cx = [c for _t, c in pts]
    if not cx:
        return "'(iw-ow)/2'"
    half = win_frac / 2.0
    best = None
    for i in range(0, 1001):
        c = i / 1000.0
        if c - half < 0 or c + half > 1:
            continue
        cost = 0.0
        for v in cx:
            d = abs(min(max(v, c - half), c + half) - c)
            miss = max(0.0, abs(v - c) - half)
            cost += d * d + 4.0 * miss * miss
        key = (cost, abs(c - 0.5))
        if best is None or key < best[0]:
            best = (key, c)
    if best is None:
        return "'(iw-ow)/2'"
    return f"'iw*{best[1]:.4f}-ow/2'"


def _pillar_pan_x(video_path, start, end, card_h):
    """x expression for the pillar card's crop window.

    Scaling a 16:9 source to 75% of a 1920 canvas makes it 2560 wide, so the
    1080 crop keeps 42% of the width and the choice of WHICH 42% decides
    whether the clip is about the right person at all.

    A CENTRED crop is not a neutral default. On the Gibran scrum the subject
    sat at cx 0.74 while the centre window covers 0.29-0.71, so he was outside
    the rendered frame for 55% of the clip and the operator got a shot of an
    escort officer and a bystander ("Salah muka woi harusnya kan gibran").

    When PAN is off the window is therefore PLACED but still does not move:
    one position for the whole clip, scored by how centred the tracked subject
    is across the segment. Measured on this clip, share of samples where the
    subject sits inside the middle 60% of the window:

        centred            36%
        placed (0.67)      38%
        PAN on             100%  (7 keyframes)

    Placement is only a marginal gain here because the subject travels 0.52 of
    the frame width while the window is 0.42 wide — no static position can hold
    him, and the honest ceiling is low. It is still the better floor when the
    operator has asked for no movement, and with PAN on the window tracks as
    before.
    """
    centre = "'(iw-ow)/2'"
    try:
        import cv2  # noqa: F401
    except ImportError:
        return centre
    cap = cv2.VideoCapture(video_path)
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if cap.isOpened() else 0
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if cap.isOpened() else 0
    cap.release()
    if W <= 0 or H <= 0:
        return centre
    # Width the source occupies once scaled to the card height.
    scaled_w = W * (card_h / H)
    if scaled_w <= CANVAS_W * 1.001:      # nothing to pan: it already fits
        return centre
    win_frac = CANVAS_W / scaled_w
    pts = _sample_pan_faces(video_path, start, end)
    if not pts:
        return centre
    if not PAN:
        return _static_window_x(pts, win_frac)
    keys = _pan_keys(pts, win_frac)
    if not keys:
        return centre
    return f"'iw*({_pan_expr(keys)})-ow/2'"


def _sample_face_centers(video_path, start, end, step=1.0):
    """[(t, cx, cy)] centres of the tracked face, in cropped-frame fractions.

    Reads the segment once in order (no per-sample seek), and on each sampled
    frame picks the face nearest the previous position, so a two-person shot
    follows one speaker instead of hopping between them. t is relative to
    `start`; cx,cy are fractions of the cropped 9:16 frame, lining up with what
    the zoompan sees. Empty means no face was found; the caller stays centred.
    """
    try:
        import cv2
    except ImportError:
        return []
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []
    try:
        if not os.path.exists(FACE_MODEL):
            return []
        det = cv2.FaceDetectorYN_create(FACE_MODEL, "", (640, 640), 0.6, 0.3, 5000)
        W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if W <= 0 or H <= 0:
            return []
        left, top, cw, ch = _cover_rect(W, H)
        x0, y0 = max(0, int(left)), max(0, int(top))
        x1, y1 = min(W, int(left + cw)), min(H, int(top + ch))
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        every = max(1, int(round(src_fps * step)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(start * src_fps))
        pts, prev = [], None
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = start + idx / src_fps
            if t >= end:
                break
            if idx % every == 0:
                crop = frame[y0:y1, x0:x1]
                det.setInputSize((crop.shape[1], crop.shape[0]))
                _ok, faces = det.detect(crop)
                if faces is not None and len(faces):
                    centers = [((float(f[0]) + float(f[2]) / 2) / crop.shape[1],
                                (float(f[1]) + float(f[3]) / 2) / crop.shape[0])
                               for f in faces]
                    target = prev or (0.5, 0.5)
                    c = min(centers, key=lambda p:
                            (p[0] - target[0]) ** 2 + (p[1] - target[1]) ** 2)
                    prev = c
                    pts.append((t - start, c[0], c[1]))
            idx += 1
        return pts
    except cv2.error:
        return []
    finally:
        cap.release()


def _track_expr(pts, dur, fps, axis):
    """Piecewise-linear ffmpeg expression for the face centre (axis 0=x, 1=y).

    Keypoints are thinned (a point that has not moved is dropped, so a static
    speaker yields a constant) then clamped so the crop never leaves the frame
    at full zoom. A gap before the first detection holds that first position.
    """
    key = []
    for i, (t, cx, cy) in enumerate(pts):
        v = cx if axis == 0 else cy
        if not key or i == len(pts) - 1 or abs(v - key[-1][1]) >= 0.015:
            key.append((max(0, int(t * fps)), v))
    lo, hi = 1.0 / (2.0 * ZOOM), 1.0 - 1.0 / (2.0 * ZOOM)
    key = [(k, min(hi, max(lo, v))) for k, v in key]
    if len(key) == 1:
        return f"{key[0][1]:.4f}"
    expr = f"{key[-1][1]:.4f}"
    for i in range(len(key) - 2, -1, -1):
        k0, v0 = key[i]
        k1, v1 = key[i + 1]
        expr = (f"if(lt(on,{k1}),{v0:.4f}+({v1:.4f}-{v0:.4f})"
                f"*(on-{k0})/{max(1, k1 - k0)},{expr})")
    k0, v0 = key[0]
    return f"if(lt(on,{k0}),{v0:.4f},{expr})"


def _face_zoompan(video_path, start, end, dur, fps=FPS):
    """Push-in that follows the speaker's face, or None to fall back centred."""
    if ZOOM <= 1.0:
        return None
    pts = _sample_face_centers(video_path, start, end)
    if len(pts) < 2:
        return None
    _n, z = _zoom_parts(dur, fps)
    fx = _track_expr(pts, dur, fps, 0)
    fy = _track_expr(pts, dur, fps, 1)
    off = f"1/(2*({z}))"
    return (f"fps={fps},"
            f"zoompan=z='{z}':"
            f"x='iw*(({fx})-({off}))':y='ih*(({fy})-({off}))':"
            f"d=1:fps={fps}:s={CANVAS_W}x{CANVAS_H}")


def render_clip(video_path, start, end, words, out_path, *,
                hook=None, split_screen=False, bgm=True, fps=FPS,
                bitrate=BITRATE, preset=PRESET, threads=THREADS,
                caption_style=CAPTION_STYLE, accent_words=(),
                frame_mode=FRAME_MODE, caption_place=CAPTION_PLACE,
                hook_style=HOOK_STYLE, intro=None, intro_seconds=None,
                inserts=(), mood=None):
    """Render one vertical clip [start, end) with burned-in captions.

    words: [{word,start,end}] with ABSOLUTE source timestamps; caller pre-slices
    to the segment. hook: headline text shown as a boxed overlay for the first
    seconds; **double asterisks** inside it render bold, the rest regular.

    caption_style="phrase" (default) draws whole phrases in one colour, left
    aligned inside the footage band — the reference look, and ~6x fewer overlay
    inputs. caption_style="karaoke" keeps the per-word highlight (PRD §3.6).
    accent_words tints the phrase carrying the punchline (see metadata.py).

    bgm accepts a track path (what pipeline.py passes, chosen by bgm.py from
    the clip's mood), True for a random pick, or False for none.

    hook_style="boxes" (default) is the pull-quote look — one white box per
    line with a teal quote mark above; "card" is a single continuous card.

    intro is an optional b-roll clip played before the segment, which is where
    the hook then lives: the reference clips open on a different shot and cut to
    the speaker when the card leaves. Without one the hook rides over the
    opening seconds of the segment instead, and captions are suppressed while it
    is up — a caption poking out from behind the hook boxes is the one thing
    that always looks wrong. That does mean those seconds carry no subtitle,
    which is the reason to pass an intro.

    caption_place="below" (default) sizes the footage like the reference clip
    (40% of the canvas, centred) so the captions fit in a clear strip beneath
    it, covering nothing; "inside" keeps the footage as large as frame_mode
    allows and lays the captions over it.

    frame_mode="fill" (default) crops the footage to canvas width at
    FILL_HEIGHT_FRAC of the canvas height; "fit" scales the whole frame in
    instead, losing nothing but showing the subject smaller. Either way the
    footage sits over a blurred copy of itself. split_screen=True keeps the
    legacy gameplay-bg layout (per-campaign toggle, PRD §3.6).

    mood is the clip's emotional register (bgm.py derives it from the
    transcript, and it already picks the music). It decides how the clip ends:
    an "emotional" clip drains to black and white over the last seconds, while
    anything else gets the bright stinger. Endings are the one place where the
    wrong default is actively offensive — a flash montage under an apology for
    people being killed reads as not having listened.
    Returns out_path.
    """
    dur = end - start
    tmp_dir = os.path.join(_BASE, f"temp_subs_{uuid.uuid4().hex[:8]}")
    os.makedirs(tmp_dir, exist_ok=True)
    try:
        # "cover" fills the frame, so there is no clear strip to put captions
        # in — they ride on the footage, which is what the reference does.
        below = (caption_place == "below" and not split_screen
                 and frame_mode != "cover")
        if caption_style == "editorial" and not split_screen:
            overlays = _editorial_layer(
                words, start, tmp_dir, accent_words=accent_words,
                y_frac=(EDIT_Y_FRAC_PILLAR if frame_mode == "pillar"
                        else EDIT_Y_FRAC))
        elif caption_style == "phrase" and not split_screen:
            overlays = _phrase_layer(
                words, start, tmp_dir, accent_words=accent_words,
                y_frac=BELOW_CAPTION_BOTTOM if below else PHRASE_Y_FRAC)
        else:
            sub_y = SUB_Y if split_screen else CLEAN_SUB_Y
            if below:
                sub_y = int(BELOW_CAPTION_BOTTOM * CANVAS_H) - FONT_SIZE * 2
            overlays = _karaoke_layer(words, start, tmp_dir, sub_y=sub_y)
        intro_dur = 0.0
        if intro:
            intro_dur = float(intro_seconds if intro_seconds else HOOK_DUR)
            # the segment's captions belong to the segment, which now starts
            # after the b-roll
            overlays = [o._replace(t_start=o.t_start + intro_dur,
                                   t_end=o.t_end + intro_dur) for o in overlays]

        if hook:
            hook_dur = intro_dur if intro else min(HOOK_DUR, dur)
            if not intro:
                # nothing may share the screen with the hook: a caption edge
                # sticking out from behind the boxes reads as a mistake
                overlays = [o for o in overlays if o.t_start >= hook_dur]
            if split_screen:
                hook_y, anchor_bottom = HOOK_Y, False
            elif below:
                hook_y, anchor_bottom = int(BELOW_HOOK_BOTTOM * CANVAS_H), True
            else:
                hook_y, anchor_bottom = int(CLEAN_HOOK_BOTTOM * CANVAS_H), True
            overlays += _hook_layer(censor.mask(hook), tmp_dir, hook_dur,
                                    y=hook_y, left=not split_screen,
                                    bottom=anchor_bottom, style=hook_style)

        bg_video = _random_asset(BG_DIR, (".mp4", ".mov", ".webm")) if split_screen else None
        # bgm: a path chosen by bgm.py (production), or True for a random pick
        # — the latter is for the smoke test only, it is not reproducible.
        if isinstance(bgm, str):
            bgm_path = bgm
        elif bgm:
            bgm_path = _random_asset(BGM_DIR, (".mp3", ".wav", ".m4a"))
        else:
            bgm_path = None

        inputs = ["-ss", f"{start}", "-t", f"{dur}", "-i", os.path.abspath(video_path)]
        intro_idx = None
        if intro:
            # loop a short b-roll rather than ending the intro early
            intro_idx = 1
            inputs += ["-stream_loop", "-1", "-t", f"{intro_dur}",
                       "-i", os.path.abspath(intro)]
        if bg_video:
            inputs += ["-stream_loop", "-1", "-t", f"{dur + intro_dur}",
                       "-i", os.path.abspath(bg_video)]
        base = 1 + (1 if intro else 0)
        bgm_idx = None
        if bgm_path:
            bgm_idx = base + (1 if bg_video else 0)
            inputs += ["-stream_loop", "-1", "-t", f"{dur + intro_dur}",
                       "-i", os.path.abspath(bgm_path)]
        first_overlay_idx = base + (1 if bg_video else 0) + (1 if bgm_path else 0)
        # B-roll cutaways are inputs too, placed before the caption PNGs so the
        # captions composite on top of them: an insert that covered the subtitle
        # would hide the line the viewer is reading.
        ins = [i for i in (inserts or ())
               if i and i.get("path") and os.path.exists(i["path"])]
        insert_base = first_overlay_idx
        for i in ins:
            inputs += ["-i", os.path.abspath(i["path"])]
        first_overlay_idx += len(ins)
        for ov in overlays:
            inputs += ["-i", os.path.basename(ov.path)]  # cwd is tmp_dir

        cover = (f"scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase,"
                 f"crop={CANVAS_W}:{CANVAS_H}")
        if frame_mode == "pillar":
            # A 16:9 source covered to 9:16 keeps only 32% of the frame width
            # (measured: 1920x1080 -> scale 1.778, so 1080 of 3413 px), and
            # CLIPPER_ZOOM=1.2 on top of that leaves 26%. On a press-conference
            # wide shot that crop is the operator's "anglenya ampas": the
            # subject is off to one side and the crop keeps the middle.
            #
            # pillar zooms OUT instead — the whole frame at PILLAR_FILL of the
            # canvas width, with the remainder filled by a blurred, scaled copy
            # of the same frame so there are no hard black bars. Output stays
            # exactly 1080x1920; nothing about the delivered resolution moves.
            # The background copy is pushed in hard and darkened. At plain
            # cover scale the duplicated news banner reappears in the lower
            # band as a half-readable ghost of the same headline — the caption
            # visibly twice, fighting the real one. Zooming the backdrop past
            # the banner and dropping its brightness leaves texture instead of
            # letterforms.
            # The background is cover-scaled FIRST (so it always fills the
            # canvas whatever the source aspect) and then pushed in further.
            # Scaling to a flat multiple of canvas WIDTH was wrong: a 16:9
            # source at 2.2x1080 is only 1336 tall, short of 1920, and crop
            # fails the pad with "Invalid too big or non positive size".
            # Measured on this source: the news banner sits at 88% of frame
            # height, and it only leaves the visible crop past ~1.6x cover.
            # The sharp card fills PILLAR_COVER of the canvas HEIGHT and the
            # full canvas width, so the subject is large enough to read on a
            # phone. Scaling by height means the source is cropped
            # horizontally; the window follows the speaker when a face track is
            # available, exactly like `cover` does, instead of keeping the
            # middle of the frame and hoping the subject is in it.
            card_h = int(CANVAS_H * PILLAR_COVER) // 2 * 2
            pan_x = _pillar_pan_x(video_path, start, end, card_h)
            fg = (f"scale=-2:{card_h},"
                  f"scale=w='max(iw,{CANVAS_W})':h=-2,"
                  f"crop={CANVAS_W}:{card_h}:x={pan_x}:y='(ih-oh)/2'")
            cover = (
                f"split=2[pbg][pfg];"
                f"[pbg]scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase,"
                f"scale=iw*{PILLAR_BG_ZOOM:.2f}:-2,"
                f"crop={CANVAS_W}:{CANVAS_H},"
                f"gblur=sigma={PILLAR_BLUR:.0f},"
                f"eq=brightness=-{PILLAR_BG_DIM:.2f}:saturation={PILLAR_BG_SAT:.2f}[pbgb];"
                f"[pfg]{fg}[pfgs];"
                f"[pbgb][pfgs]overlay=(W-w)/2:(H-h)/2"
            )
        chains = []
        base_label = "vmain" if intro else "v0"
        if frame_mode == "cover" and not split_screen:
            # nothing to composite: the footage is the frame
            # A panning crop window already keeps the speaker in shot, so the
            # push-in over it stays centred; tracking inside an already-tracked
            # window would just fight it.
            cover_v = _pan_cover(video_path, start, end) if FACE_TRACK else None
            punches = _punch_times(words, start, dur)
            zoom = None
            if ZOOM > 1.0:
                if cover_v is None and FACE_TRACK:
                    zoom = _face_zoompan(video_path, start, end, dur, fps)
                zoom = zoom or _zoompan(dur, fps, words, start)
            else:
                # Punch-ins are independent of the slow drift: a clip with zoom
                # off should still land a tighter crop on stressed words.
                zoom = _zoompan(dur, fps, words, start)
            # Flashes land on beats the punches already chose, so the clip never
            # gains emphasis the audio did not have.
            flash = _flash_expr(punches, dur)
            # The closing treatment joins the same brightness expression, and
            # may add filters of its own (the melancholy ending desaturates).
            #
            # Applied to [0:v], which is the speech segment BEFORE the intro is
            # concatenated in front of it, so its window is measured against
            # `dur` alone. Passing the combined length here would place the
            # ending `intro_dur` seconds early — the v17 render put a 5s outro
            # at t=84 of an 89s timeline whose own clock only reached 82, so
            # the treatment landed mid-speech and the last seconds shipped
            # untouched. Measured on the delivered file: SATAVG 7.0 -> 6.9
            # across the supposed ramp, i.e. nothing happened.
            outro, outro_filters = _outro_filters(dur, mood=mood)
            bright = "+".join(x for x in (flash, outro) if x)
            chains.append(f"[0:v]{cover_v or cover},setsar=1"
                          + (f",{zoom}" if zoom else "")
                          + (f",eq=brightness='{bright}':eval=frame" if bright else "")
                          + "".join(f",{f}" for f in outro_filters)
                          + f"[{base_label}]")
        elif split_screen and bg_video:
            chains.append(f"[1:v]{cover},eq=brightness=-0.25[bg]")
            chains.append(f"[0:v]scale=-2:980,crop=min(iw\\,1040):980[mn]")
        elif frame_mode == "pillar" and not split_screen:
            # pillar builds its own background and foreground inside `cover`
            # above, so it is already a finished 1080x1920 frame. Falling into
            # the "fill" branch below re-cropped that finished frame to canvas
            # width and undid the whole point: the first pillar render shipped
            # with the news banner sliced at both ends
            # ("...RAL GIBRAN SARANKAN SISWA BAWA BEKAL DARI RUM...") and the
            # speaker's face cut, which is the exact damage pillar exists to
            # prevent. Checked by reading a frame out of the delivered file;
            # the graph string and the 1080x1920 probe both looked correct.
            #
            # zoom and the outro are computed here rather than reused from the
            # cover branch above: that branch never runs in pillar mode, so
            # its locals do not exist. _zoompan skips the standing CLIPPER_ZOOM
            # in pillar mode and keeps only the punch-ins.
            p_zoom = _zoompan(dur, fps, words, start, frame_mode=frame_mode)
            p_bright, p_filters = _outro_filters(dur, mood=mood)
            chains.append(f"[0:v]{cover},setsar=1"
                          + (f",{p_zoom}" if p_zoom else "")
                          + (f",eq=brightness='{p_bright}':eval=frame"
                             if p_bright else "")
                          + "".join(f",{f}" for f in p_filters)
                          + f"[{base_label}]")
        else:
            # reference style: the footage itself, blurred, fills the frame
            chains.append(f"[0:v]split=2[bgsrc][mnsrc]")
            chains.append(f"[bgsrc]{cover},gblur=sigma={BLUR_SIGMA},"
                          f"eq=brightness={BG_DARKEN}[bg]")
            # captions below need the footage smaller, so it clears the lane
            box_h = int(CANVAS_H * (BELOW_HEIGHT_FRAC if below else FILL_HEIGHT_FRAC))
            if frame_mode == "fit":
                # never crop: the whole source frame lands as a band, its
                # height set by the source aspect (capped by box_h)
                chains.append(f"[mnsrc]scale=w={CANVAS_W}:h={box_h}:"
                              f"force_original_aspect_ratio=decrease:"
                              f"force_divisible_by=2[mn]")
            else:
                # fill: scale by height, then crop to canvas width. A source
                # narrower than the canvas is scaled up to it first, so the
                # crop never leaves a transparent edge.
                h = box_h // 2 * 2
                chains.append(f"[mnsrc]scale=-2:{h},"
                              f"scale=w='max(iw,{CANVAS_W})':h=-2,"
                              f"crop={CANVAS_W}:min(ih\\,{h})[mn]")
        if not (frame_mode in ("cover", "pillar") and not split_screen):
            # cover and pillar both finish their own chain above and never
            # create [bg]/[mn]; running this overlay for them would reference
            # labels that do not exist.
            chains.append(f"[bg][mn]overlay=(W-w)/2:(H-h)/2,setsar=1[{base_label}]")
        if intro:
            # b-roll cropped to the canvas like any other footage, then joined
            # in front; overlays build on the concatenated stream
            chains.insert(0, f"[{intro_idx}:v]{cover},setsar=1[intro]")
            chains.append("[intro][vmain]concat=n=2:v=1:a=0[v0]")

        # Cutaways go on before the captions, and their windows are shifted by
        # the intro: the times come from the transcript, which knows nothing
        # about the hook footage concatenated in front of it.
        ins_label = "[v0]"
        for n, item in enumerate(ins):
            nxt = f"[bi{n}]"
            chains.append(broll_place.overlay_chain(
                ins_label, insert_base + n,
                float(item["start"]) + intro_dur,
                float(item["end"]) + intro_dur, nxt,
                canvas_h=CANVAS_H))
            ins_label = nxt

        # Captions must not run on over the frozen ending. The freeze turns the
        # last frame into a still, but overlay windows come from the transcript
        # and know nothing about it, so 6 of 21 caption tiles kept animating on
        # top of a frozen picture — the operator's "kenapa subtitlenya masih
        # jalan?". Clamp every window to where the ending begins.
        outro_at = _outro_start(dur, mood=mood)
        for i, ov in enumerate(overlays):
            src_label = ins_label if i == 0 else f"[v{i}]"
            dst_label = f"[v{i + 1}]"
            t_end = ov.t_end
            if outro_at is not None:
                t_end = min(t_end, outro_at + intro_dur)
                if t_end <= ov.t_start:
                    # Entirely inside the ending: still emit the chain so the
                    # label sequence stays unbroken, but never enable it.
                    t_end = ov.t_start
            chains.append(
                f"{src_label}[{first_overlay_idx + i}:v]"
                f"overlay={ov.x}:{ov.y}:enable='between(t,{ov.t_start:.3f},{t_end:.3f})'"
                f"{dst_label}")
        # With no caption overlays the insert chain is the last video stage, so
        # the output label has to come from it or the cutaways are discarded.
        vlabel = f"[v{len(overlays)}]" if overlays else ins_label

        total = dur + intro_dur
        if intro:
            # The b-roll's own sound is dropped under the hook: the music bed
            # carries that moment, and the two together are mush. The gap is
            # filled with silence so the speech starts after the hook —
            # concatenating a missing stream would break the graph outright.
            ms = int(intro_dur * 1000)
            intro_audio = False
            if intro_idx is not None and not BGM_MUTE_BROLL_HOOK:
                try:
                    import fetch
                    intro_audio = fetch.probe_has_audio(os.path.abspath(intro))
                except Exception:
                    intro_audio = False
            if intro_audio:
                chains.append(f"[{intro_idx}:a]atrim=0:{intro_dur:.3f},"
                              f"asetpts=N/SR/TB,aformat=sample_rates=48000:"
                              f"channel_layouts=stereo[aintro]")
                chains.append(f"[0:a]aformat=sample_rates=48000:"
                              f"channel_layouts=stereo[aspeech]")
                chains.append("[aintro][aspeech]concat=n=2:v=0:a=1[amain]")
            else:
                chains.append(f"[0:a]adelay={ms}|{ms}[amain]")
            speech = "[amain]"
        else:
            speech = "[0:a]"
        # A looped BGM track hands amix packets with no timestamp once it wraps
        # past its own length, and the muxer rejects them (dts NOPTS). Stamping
        # the mixed result rebuilds a monotonic clock; without it a clip longer
        # than the music simply fails to write.
        restamp = "asetpts=N/SR/TB"
        if bgm_idx is not None:
            # Loud under the hook, ducked under the speaker. The step down is
            # ramped rather than cut: a hard level change lands as a click at
            # the exact second the clip is asking for attention.
            hook_end = intro_dur if intro_idx is not None else 0.0
            if hook_end > 0:
                duck_at = max(0.0, hook_end - BGM_FADE / 2)
                duck_end = duck_at + BGM_FADE
                # One per-frame expression: hook level, linear ramp, bed level.
                chains.append(
                    f"[{bgm_idx}:a]volume=eval=frame:volume="
                    f"'if(lt(t,{duck_at:.3f}),{BGM_HOOK_VOLUME},"
                    f"if(lt(t,{duck_end:.3f}),"
                    f"{BGM_HOOK_VOLUME}+({BGM_VOLUME}-{BGM_HOOK_VOLUME})"
                    f"*(t-{duck_at:.3f})/{BGM_FADE},"
                    f"{BGM_VOLUME}))'[bgm]")
            else:
                chains.append(f"[{bgm_idx}:a]volume={BGM_VOLUME}[bgm]")
            # normalize=0 is load-bearing. amix defaults to normalize=1, which
            # divides every input by the number of inputs, so adding music
            # silently halves the speech: the clip with BGM measured 5.7 dB
            # QUIETER overall than the same clip without it. The per-track
            # levels above already set the balance; amix must not re-scale it.
            chains.append(f"{speech}[bgm]amix=inputs=2:duration=first:"
                          f"normalize=0:dropout_transition=0,{restamp},"
                          f"afade=t=out:st={max(0, total - 1):.2f}:d=1[a]")
        else:
            chains.append(f"{speech}{restamp},"
                          f"afade=t=out:st={max(0, total - 1):.2f}:d=1[a]")

        # The graph can carry hundreds of overlay chains — pass it as a file so
        # the command never hits the OS argument-length limit.
        with open(os.path.join(tmp_dir, "graph.txt"), "w", encoding="utf-8") as f:
            f.write(";".join(chains))

        cmd = ([FFMPEG, "-y", "-v", "error"] + inputs +
               [_graph_flag(), "graph.txt",
                "-map", vlabel, "-map", "[a]",
                "-c:v", CODEC, "-preset", preset, "-b:v", bitrate,
                "-pix_fmt", "yuv420p", "-r", str(fps),
                "-c:a", "aac", "-b:a", "128k",
                "-threads", str(threads), "-movflags", "+faststart",
                os.path.abspath(out_path)])
        # A generous ceiling, not a performance target: a 90s clip renders in
        # ~220s on this box, so 40 minutes only ever trips on a stall. Without
        # it a wedged ffmpeg holds the job lock forever and every later request
        # is told the renderer is busy.
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_dir,
                              timeout=RENDER_TIMEOUT)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()[:600]}")
        return out_path
    finally:
        # CLIPPER_KEEP_TMP leaves the filter graph and overlay PNGs on disk.
        # The graph is the only honest record of what ffmpeg was actually asked
        # to do: a setting can read correctly in Python and still never reach
        # the render, which is exactly the bug this was added for.
        if os.environ.get("CLIPPER_KEEP_TMP") in ("1", "true", "yes"):
            print(f"edit: kept {tmp_dir}")
        else:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _preview_cli(argv):
    """Render one clip from a local file — no Clippo, no 9Router, no upload.

        python edit.py preview FOOTAGE [--start 0] [--end 45] [--hook "..."]
                               [--intro BROLL] [--out clip.mp4] [--words w.json]

    This is the local loop: drop a source in, look at the result. The transcript
    comes from faster-whisper (cached beside the video, so the second run is
    instant) unless --words points at one, and the hook is whatever you type
    rather than what the model would have written.
    """
    import argparse
    import json as _json

    p = argparse.ArgumentParser(prog="edit.py preview")
    p.add_argument("footage")
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--end", type=float, default=None)
    p.add_argument("--hook", default=None,
                   help="**double asterisks** render bold")
    p.add_argument("--intro", default=None, help="b-roll played before the clip")
    p.add_argument("--intro-seconds", type=float, default=None)
    p.add_argument("--out", default="preview.mp4")
    p.add_argument("--words", default=None, help="transcript JSON, skips whisper")
    p.add_argument("--bgm", default=None, help="path to a music track")
    p.add_argument("--frame-mode", default=FRAME_MODE, choices=("cover", "fill", "fit", "pillar"))
    p.add_argument("--caption-style", default=CAPTION_STYLE,
                   choices=("phrase", "karaoke"))
    p.add_argument("--hook-style", default=HOOK_STYLE, choices=("boxes", "card"))
    a = p.parse_args(argv)

    if a.words:
        with open(a.words, encoding="utf-8") as f:
            data = _json.load(f)
        words = data["words"] if isinstance(data, dict) else data
    else:
        import transcribe
        print("transcribing (cached next to the video after the first run)...")
        words, _info = transcribe.transcribe(a.footage)
    end = a.end
    if end is None:
        end = max((w["end"] for w in words), default=a.start + 30.0)
    seg = [w for w in words if a.start <= w["start"] < end]
    print(f"segment {a.start:.1f}-{end:.1f}s, {len(seg)} words")

    render_clip(a.footage, a.start, end, seg, a.out,
                hook=a.hook, bgm=a.bgm or False,
                intro=a.intro, intro_seconds=a.intro_seconds,
                frame_mode=a.frame_mode, caption_style=a.caption_style,
                hook_style=a.hook_style)
    print(f"wrote {a.out} ({os.path.getsize(a.out) // 1024} KB)")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "preview":
        _preview_cli(sys.argv[2:])
        sys.exit(0)

    # Logic self-check first (no ffmpeg, no footage), then an optional render.
    assert _parse_emphasis("**Nekat!! Berani** Ngomong Ke **Mantan**") == [
        ("Nekat!!", True), ("Berani", True), ("Ngomong", False), ("Ke", False),
        ("Mantan", True)], _parse_emphasis("**a** b")
    assert _parse_emphasis("tanpa penanda") == [("tanpa", False), ("penanda", False)]
    lines = _wrap_tokens([(w, False) for w in "satu dua tiga empat lima".split()],
                         max_chars=10)
    assert ["".join(w for w, _ in l) for l in lines] == ["satudua", "tigaempat", "lima"], lines

    # phrases break on a pause, and cap at max_words * max_lines
    ws = [{"word": f"w{i}", "start": i * 0.3, "end": i * 0.3 + 0.25} for i in range(4)]
    ws += [{"word": f"x{i}", "start": 3.0 + i * 0.3, "end": 3.0 + i * 0.3 + 0.25}
           for i in range(2)]
    ph = group_phrases(ws)
    assert len(ph) == 2, ph                       # the 2s pause splits them
    assert [w["word"] for l in ph[0]["lines"] for w in l] == ["w0", "w1", "w2", "w3"]
    assert len(ph[0]["lines"]) == 2, ph[0]["lines"]        # 3 words per line
    assert ph[1]["start"] == 3.0 and ph[0]["end"] == ws[3]["end"]
    dense = [{"word": f"d{i}", "start": i * 0.2, "end": i * 0.2 + 0.15} for i in range(20)]
    _ph = group_phrases(dense)
    assert all(sum(len(l) for l in p["lines"]) <= PHRASE_MAX_WORDS * PHRASE_MAX_LINES
               for p in _ph)
    # an over-long run is continued as the next caption, not truncated: every
    # word survives, in order
    _flat = [w["word"] for p in _ph for l in p["lines"] for w in l]
    assert _flat == [w["word"] for w in dense], _flat
    assert len(_ph) == 4, len(_ph)      # 20 words / 6 per caption

    # a pause inside the window wins over the raw word count, so a phrase is
    # not sliced in half; the remainder carries forward intact
    paced = []
    for i, w in enumerate("satu dua tiga empat lima enam tujuh delapan".split()):
        t = i * 0.25 + (0.30 if i >= 4 else 0.0)   # a clear breath before "lima"
        paced.append({"word": w, "start": round(t, 3), "end": round(t + 0.2, 3)})
    _pp = group_phrases(paced)
    assert [w["word"] for l in _pp[0]["lines"] for w in l] == \
        ["satu", "dua", "tiga", "empat"], _pp[0]["lines"]
    assert [w["word"] for p in _pp for l in p["lines"] for w in l] == \
        [w["word"] for w in paced]
    # a caption placed "below" must clear the footage by construction, for the
    # worst case (a full three-line phrase) — this is the whole point of the mode
    import tempfile as _tf
    _long = [{"word": f"KATAPANJANG{i}", "start": i * 0.2, "end": i * 0.2 + 0.15}
             for i in range(PHRASE_MAX_WORDS * PHRASE_MAX_LINES)]
    _ov = _phrase_layer(_long, 0, _tf.mkdtemp(), y_frac=BELOW_CAPTION_BOTTOM)
    _top = min(o.y for o in _ov)
    _bot = max(o.y + Image.open(o.path).height for o in _ov)
    _video_bottom = (0.5 + BELOW_HEIGHT_FRAC / 2) * CANVAS_H
    assert _top > _video_bottom, f"caption {_top} overlaps footage ending {_video_bottom}"
    assert _bot <= PLATFORM_SAFE_BOTTOM * CANVAS_H, (
        f"caption bottom {_bot} runs into the platform UI zone")
    # on a full frame the hook must never grow past the platform UI, whatever
    # the wrap produces — the failure this catches is a last line nobody sees
    for _n, _hook in ((1, "**Pendek**"), (3, "**Cara Paling Elegan** Nanya Nama "
                      "Orang Kalau **Kamu Terlanjur Lupa!**"),
                      (5, "**Ini Hook Yang Sangat Panjang Sekali** Sampai Harus "
                          "Dibungkus Ke Banyak Baris **Biar Ketahuan**")):
        _ov = _hook_layer(_hook, _tf.mkdtemp(), y=int(CLEAN_HOOK_BOTTOM * CANVAS_H),
                          left=True, bottom=True)
        _bot = max(o.y + Image.open(o.path).height for o in _ov)
        _top = min(o.y for o in _ov)
        assert _bot <= PLATFORM_SAFE_BOTTOM * CANVAS_H + 1, (
            f"hook of {_n} lines ends at {_bot}, past the platform UI line")
        assert _top >= 0, f"hook of {_n} lines starts off-frame at {_top}"

    _video_top = (0.5 - BELOW_HEIGHT_FRAC / 2) * CANVAS_H
    for _hook in ("**Pendek** aja", "**Nekat!! Densu Berani Banget** Ngajarin "
                  "Anak-Nya Seperti Ini Ke **Mama Nya Biel**"):
        _h = _hook_layer(_hook, _tf.mkdtemp(), y=int(BELOW_HOOK_BOTTOM * CANVAS_H),
                         left=True, bottom=True)[0]
        _hh = Image.open(_h.path).height
        assert _h.y >= _video_top, f"hook starts at {_h.y}, above footage {_video_top}"
        assert _h.y + _hh <= _video_bottom, (
            f"hook ends at {_h.y + _hh}, past footage {_video_bottom}")
    print("edit.py logic self-check OK")

    # Smoke: actually render, so the box proves it can. Uses a fetched video
    # when one is around, and otherwise builds its own footage with ffmpeg, so
    # this runs on a machine with nothing downloaded and no network.
    import json
    vid = os.path.join(_BASE, "media", "3", "IJE50gujMTg.mp4")
    sidecar = os.path.join(_BASE, "media", "3", "IJE50gujMTg.words.json")
    synthetic = _tf.mkdtemp(prefix="clipper_smoke_")
    try:
        if os.path.exists(vid) and os.path.exists(sidecar):
            with open(sidecar, encoding="utf-8") as f:
                all_words = json.load(f)["words"]
            seg = [w for w in all_words if 60 <= w["start"] < 65]
            base = 60.0
        else:
            print("no footage on disk, generating some with ffmpeg")
            vid = os.path.join(synthetic, "source.mp4")
            # 1920x1080 so the 9:16 crop has to do real work, with an audio
            # track so the amix and restamp path is exercised too.
            gen = subprocess.run(
                [FFMPEG, "-y", "-v", "error",
                 "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=8",
                 "-f", "lavfi", "-i", "sine=frequency=180:duration=8",
                 "-c:v", CODEC, "-pix_fmt", "yuv420p", "-c:a", "aac",
                 "-shortest", vid], capture_output=True, text=True,
                timeout=600)
            if gen.returncode != 0:
                print(f"smoke skipped: ffmpeg cannot generate footage "
                      f"({gen.stderr.strip()[:120]})")
                sys.exit(0)
            seg = [{"word": w, "start": 0.4 + i * 0.42, "end": 0.78 + i * 0.42}
                   for i, w in enumerate(
                       "jadi gue dulu mikir bikin konten itu susah "
                       "banget padahal bukan idenya".split())]
            base = 0.0

        hook = "Anak Muda Ini Sukses Jadi Clipper 😱 25 Juta Per Bulan !! 💰🔥"
        seg = list(seg)
        if len(seg) > 2:
            seg[2] = dict(seg[2], word=seg[2]["word"] + " 🔥")  # karaoke emoji path
        for mode, ss in (("split", True), ("clean", False)):
            out = os.path.join(_BASE, f"smoke_{mode}.mp4")
            render_clip(vid, base, base + 5, seg, out, hook=hook,
                        split_screen=ss, bgm=ss)
            assert os.path.exists(out) and os.path.getsize(out) > 100_000, mode
            print(f"smoke {mode}: OK ({os.path.getsize(out)//1000} KB)")
    finally:
        shutil.rmtree(synthetic, ignore_errors=True)
