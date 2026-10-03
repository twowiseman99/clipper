"""Place found b-roll onto the timeline as brief cutaways.

`broll.py` finds footage; this decides where it goes and how long it stays.
Separate file because they fail differently: search fails on the network, this
fails on ffmpeg, and a clip should still render when either one does.

Two rules shape the result. The speaker's audio never stops — a cutaway swaps
the picture, not the sentence, so a viewer keeps the thread. And an insert sits
on the phrase that names the thing being shown, which is why the window comes
from word timings rather than a fixed interval.

The insert is composited as a timed overlay covering the full canvas, not a
concat. Concatenating would mean re-encoding the main video in segments and
rebuilding the audio graph around each cut, and every caption after the first
insert would need its timestamps shifted. An overlay leaves captions, BGM and
speech untouched, which keeps this additive rather than a rewrite of the render.
"""
import os
import re
import subprocess
import sys

# How long one cutaway holds. 2.2s read as a glitch in a delivered clip — the
# operator could not find it on playback — so a cutaway now holds long enough to
# register as a shot while the speaker is still never gone for long.
HOLD = float(os.environ.get("CLIPPER_BROLL_HOLD", "3.5"))
# Minimum gap between inserts. Same reasoning as punch spacing: an effect every
# few seconds stops being emphasis and becomes the texture of the clip. The
# editing-grammar skill puts the floor at one effect per 8-12s, so 9 is the
# shortest gap that still respects it.
MIN_GAP = float(os.environ.get("CLIPPER_BROLL_GAP", "9"))
# How much a candidate window has to move to count as footage. Measured as the
# mean frame-to-frame luma difference of a downscaled probe, so the numbers are
# small: a shipped clip's three dud cutaways scored 0.31, 0.37 and 0.45 while
# the one that read as video scored 16.3. 1.5 sits well clear of the stills
# without demanding action — a slow pan over rubble passes.
MOTION_MIN = float(os.environ.get("CLIPPER_BROLL_MOTION_MIN", "1.5"))
# Stop probing once a window scores this well; no point measuring the rest.
MOTION_GOOD = float(os.environ.get("CLIPPER_BROLL_MOTION_GOOD", "6"))
# Exception to the gap, for one case only: consecutive action words inside the
# same sentence. "mereka dibantai, dibom, diserang terus-menerus" is one
# escalating line, and three cutaways across it read as a montage of the same
# event rather than three separate effects. Spacing them 9s apart instead let
# the first word through and dropped the other two, which is why a clip about
# bombing showed one insert and then nothing.
#
# Only applies while the words keep coming this fast: a 2.5s floor is still
# wide enough that each shot registers, and the burst ends the moment the
# sentence does.
BURST_GAP = float(os.environ.get("CLIPPER_BROLL_BURST_GAP", "2.5"))
# Inside a burst each shot holds a little shorter. The speaker lists these
# words about 3.4s apart, so a full 3.5s hold leaves no room for the third one
# and the triplet ships as a pair. 3.0s still registers as a shot and keeps
# "dibantai / dibom / diserang" intact.
BURST_HOLD = float(os.environ.get("CLIPPER_BROLL_BURST_HOLD", "3.0"))
# How many may chain before the normal gap applies again. Three covers the
# escalating triplet Indonesian political speech leans on; more than that and
# the speaker is gone long enough for the viewer to lose the thread.
BURST_MAX = int(os.environ.get("CLIPPER_BROLL_BURST", "3"))
MAX_INSERTS = int(os.environ.get("CLIPPER_BROLL_MAX", "6"))
# Keep inserts out of the first and last stretch: the opening belongs to the
# hook, and cutting away from the closing line throws away the payoff.
EDGE_PAD = float(os.environ.get("CLIPPER_BROLL_EDGE", "6"))
FFMPEG = os.environ.get("CLIPPER_FFMPEG", "ffmpeg")


def _ends_sentence(word):
    """True when this token closed a sentence.

    Whisper keeps the punctuation attached to the word, so "dibantai." ends a
    sentence while "dibantai," is mid-list. Used to stop a burst at a sentence
    boundary: three cutaways across one escalating line is a montage, three
    across three separate thoughts is just a busy clip.
    """
    return str(word or "").strip().endswith((".", "?", "!"))


def phrase_windows(words, clip_start, dur, terms_fn=None):
    """Candidate (t_start, t_end, phrase) windows for inserts, clip-relative.

    Walks the transcript and proposes a window wherever a phrase mentions
    something concrete. Spacing and the edge pad are enforced here so callers
    cannot accidentally stack cutaways.

    `terms_fn` decides what counts as concrete and is effectively required: the
    unfiltered run on the Gontor transcript proposed `inget`, `terus` and
    `mendorong`, none of which have footage. Callers pass a proper-noun test,
    and with no filter at all this returns nothing rather than inserts chosen by
    position.
    """
    items = [w for w in (words or ()) if w.get("start") is not None]
    if not items or dur <= 2 * EDGE_PAD or terms_fn is None:
        return []

    out = []
    last = -1e9
    burst = 0
    prev_word = ""
    for w in items:
        t = float(w["start"]) - clip_start
        if t < EDGE_PAD or t + HOLD > dur - EDGE_PAD:
            continue
        # Inside a burst the next cutaway may follow quickly, but never before
        # the previous one has finished holding, or the two inserts overlap and
        # ffmpeg draws the second over the first.
        in_burst = bool(burst) and burst < BURST_MAX
        hold = BURST_HOLD if in_burst else HOLD
        gap = max(BURST_GAP, hold) if in_burst else MIN_GAP
        if t - last < gap:
            continue
        word = str(w.get("word", "")).strip()
        if len(word) < 4:
            continue
        # A proper noun is the strongest signal that footage of a specific
        # thing exists: "Palestina" is searchable, "mereka" is not.
        if terms_fn is not None and not terms_fn(word):
            continue
        out.append((round(t, 3), round(min(t + hold, dur), 3), word))
        # A burst continues while the speaker is still listing: the previous
        # accepted word was close by and the sentence has not ended. A terminal
        # "." or "?" on the PREVIOUS word would mean a new sentence started, so
        # the chain is broken and the normal gap applies again.
        if out[:-1] and t - last <= MIN_GAP and not _ends_sentence(prev_word):
            burst += 1
        else:
            burst = 1
        prev_word = word
        last = t
        if len(out) >= MAX_INSERTS:
            break
    return out


def _grab_jpeg(src, at, width=640):
    """One frame as JPEG bytes, for asking a model what is in it."""
    try:
        res = subprocess.run(
            [FFMPEG, "-v", "error", "-ss", f"{at:.2f}", "-i", src,
             "-frames:v", "1", "-vf", f"scale={width}:-2", "-q:v", "4",
             "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
            capture_output=True, timeout=60)
    except Exception:
        return None
    return res.stdout or None


def _frame_substance(src, at):
    """How much is actually IN the frame: (colour spread, edge density).

    A probe that only asks "does it move" picked a defocused brown transition
    frame as the best window in a Kompas news package — it had zero faces and
    respectable motion, and showed nothing at all. Both numbers here are low on
    that kind of frame and high on real footage. Returns (None, None) when the
    frame cannot be read, so callers treat it as unknown rather than bad.
    """
    jpg = _grab_jpeg(src, at, width=240)
    if not jpg:
        return None, None
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None, None
    try:
        img = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None, None
        grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        spread = float(grey.std())
        edges = cv2.Canny(grey, 80, 200)
        density = float(np.count_nonzero(edges)) / edges.size
        return spread, density
    except Exception:
        return None, None


# A frame below BOTH floors is a transition or a near-empty wash. Measured on
# this box: the defocused brown frame scored spread 18 / density 0.004, while
# real footage ran spread 40-70 / density 0.03-0.09. The floors sit well under
# the real footage so an unusual-but-real shot is not thrown away.
SUBSTANCE_SPREAD = float(os.environ.get("CLIPPER_BROLL_MIN_SPREAD", "25"))
SUBSTANCE_EDGES = float(os.environ.get("CLIPPER_BROLL_MIN_EDGES", "0.012"))
# How many finalists get shown to the model. Three is enough to recover from a
# bad top pick without turning the render into a slideshow of API calls.
# How many surviving windows to show the model. Measured on a Kompas package
# that genuinely contained an airstrike: only 2 of 14 windows showed the strike
# itself, and both sat outside the three liveliest. Three finalists threw away
# usable footage and reported "no window shows the subject" — the number was
# tuned when the question was merely "is this readable", which almost any live
# frame answers yes to. Asking for a specific moment needs a wider net.
VISION_FINALISTS = int(os.environ.get("CLIPPER_BROLL_VISION_N", "8"))
# Frames judged at once. The calls are independent network round-trips of about
# three seconds each, so eight in sequence would add half a minute per source.
VISION_PARALLEL = int(os.environ.get("CLIPPER_BROLL_VISION_PARALLEL", "4"))
VISION = os.environ.get("CLIPPER_BROLL_VISION", "1").lower() not in (
    "0", "false", "no", "off")

_VISION_SYS = ("You judge single frames pulled from news footage for use as "
               "b-roll in a short vertical clip. Reply with JSON only.")

# Three separate questions, because a frame can fail any one on its own:
#
#   usable   — can a viewer read this in under a second? (rejects cross-fade
#              frames, near-empty washes, studio anchors, full-screen graphics)
#   on_topic — is this the event being talked about, not a visual metaphor for
#              it? The operator's rule: footage has to be from the place and
#              event under discussion, and "a general impression from some
#              other footage" is a reject, not a near-miss.
#   shows_action — is it the MOMENT the sentence named? This one exists because
#              a clip said "mereka dibom" over footage of people picking
#              through rubble. Same war, same country, correct source video —
#              but rubble is the aftermath of a bombing, not a bombing. The
#              aftermath of X is explicitly not X, or the gate is decorative.
_VISION_ASK = (
    "Two questions about this frame.\n"
    "1. usable: is it a clear, identifiable real-world scene a viewer can read "
    "in under a second? Reject blurred or cross-fade transition frames, "
    "near-empty washes, studio anchors behind a desk, and full-screen graphics "
    "or title cards.\n"
    "2. on_topic: was this frame SHOT ON LOCATION at __SUBJECT__, showing what "
    "is happening there? Judge the place in the frame, not the cause people "
    "there support. Destruction, casualties, responders, residents, forces and "
    "streets AT that place count.\n"
    "   Answer false for: a solidarity march, protest, rally or vigil held in "
    "another country (banners and flags about a place are not that place); a "
    "different country's streets, buildings, traffic or skyline; an official, "
    "politician or spokesperson at a podium anywhere; a studio, map, graphic "
    "or stock imagery. Intact modern high-rises, palm trees and normal traffic "
    "are not a war zone.\n"
    "   If you cannot tell from the frame alone where it was shot, answer "
    "false.\n"
    "__ACTION_Q__"
    'Reply {"usable": true|false, "on_topic": true|false, '
    '__ACTION_FIELD__"shows": "<up to 6 words, name the place if you can>"}.')

_ACTION_Q = (
    "3. shows_action: is this frame the moment itself — __ACTION__? Be strict. "
    "The AFTERMATH of that moment is not that moment: rubble, ruins, mourning, "
    "a funeral or a rescue dig are not an explosion. People reacting, "
    "officials speaking, maps and crowds are not it either. Answer true only "
    "if the moment named is visibly happening in this frame.\n")
_ACTION_FIELD = '"shows_action": true|false, '

# What the footage has to be of. Written by the caller from the phrase that
# triggered the cutaway plus the operator's --context, so the gate asks about
# Gaza on a Gaza clip rather than about "news footage" in general.
VISION_SUBJECT = os.environ.get("CLIPPER_BROLL_SUBJECT", "").strip()


def _vision_check(src, at, subject, action=None):
    """Judge the frame at `at`. Returns (usable, on_topic, shows_action, shows).

    Verdicts are None when no answer came back: a router hiccup must not fail a
    render that would otherwise produce a clip, so the caller falls back to the
    measured numbers. shows_action is None when no action was asked about.
    """
    jpg = _grab_jpeg(src, at)
    if not jpg:
        return None, None, None, ""
    ask = _VISION_ASK.replace("__SUBJECT__",
                              subject or "the event under discussion")
    if action:
        ask = (ask.replace("__ACTION_Q__", _ACTION_Q.replace("__ACTION__",
                                                             action))
                  .replace("__ACTION_FIELD__", _ACTION_FIELD))
    else:
        ask = ask.replace("__ACTION_Q__", "").replace("__ACTION_FIELD__", "")
    try:
        import ai
        out = ai.vision_json(_VISION_SYS, ask, [jpg])
    except Exception as e:
        print(f"  broll: vision check unavailable ({type(e).__name__}), "
              f"falling back to measured motion", file=sys.stderr)
        return None, None, None, ""
    if not isinstance(out, dict) or "usable" not in out:
        return None, None, None, ""

    def tri(key):
        v = out.get(key)
        return None if v is None else bool(v)

    return (bool(out.get("usable")), tri("on_topic"), tri("shows_action"),
            str(out.get("shows") or "").strip())


def _vision_ok(src, at, subject=None, action=None):
    """Back-compat wrapper: all three verdicts collapsed into one."""
    usable, on_topic, shows_action, shows = _vision_check(
        src, at, subject, action)
    if usable is None:
        return None, shows
    return (bool(usable and on_topic is not False
                 and shows_action is not False), shows)


def _motion_at(src, at, seconds, scale=96):
    """Mean frame-to-frame difference over [at, at+seconds). Higher = moves more.

    News packages open and close on near-static cards: a presenter still, a
    logo, a caption over a frozen frame. Cutting blind lands on those often
    enough that three of four cutaways in one clip read as photographs, which
    is what the operator saw.
    """
    try:
        res = subprocess.run(
            [FFMPEG, "-v", "error", "-ss", f"{at:.2f}", "-t", f"{seconds:.2f}",
             "-i", src, "-vf",
             (f"fps=8,scale={scale}:-1,tblend=all_mode=difference,"
              "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-"),
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=120)
    except Exception:
        return None
    vals = [float(m) for m in re.findall(r"YAVG=([0-9.]+)", res.stdout)]
    # The first difference frame compares against nothing useful.
    vals = vals[1:] or vals
    return sum(vals) / len(vals) if vals else None


def _pick_window(src, dur, latest, seconds, subject=None, action=None):
    """Choose which moment of `src` becomes the cutaway. Returns (at, why).

    Three filters, cheapest first, because the expensive one is a network call:

    1. Motion, on 14 candidates rather than 5. The insert is about three seconds
       out of a two-minute news package, so five probes barely sample it.
    2. Substance — colour spread and edge density. This is what a motion-only
       probe missed: it ranked a defocused brown cross-fade frame top, because a
       dissolve moves plenty while showing nothing.
    3. The model, on the best few survivors. It answers three things: can a
       viewer read the frame, is it OF the event being discussed, and is it the
       MOMENT the sentence named. The last two are hard rules from the operator
       — footage that merely evokes the subject is a reject, and so is the
       aftermath of the action instead of the action ("mereka di bom tapi
       footagenya bukan bom"). A source with no passing window is dropped
       rather than downgraded, because a wrong cutaway is worse than none.

    Face size was in the plan and was dropped after measuring: ground crew and
    a body-cam soldier both filled 15-27% of frame height and were exactly the
    footage worth keeping, while the empty transition frame had no face at all.
    """
    fracs = (0.12, 0.2, 0.28, 0.35, 0.42, 0.48, 0.55, 0.62,
             0.68, 0.74, 0.8, 0.86, 0.91, 0.95)
    cands = sorted({round(min(dur * f, latest), 2) for f in fracs})
    if not cands:
        return 0.0, "no candidates"

    scored = []
    for c in cands:
        m = _motion_at(src, c, min(seconds, 2.0))
        if m is None or m < MOTION_MIN:
            continue
        spread, edges = _frame_substance(src, c)
        if spread is not None and edges is not None:
            # Both floors must fail before a window is discarded: a legitimately
            # plain shot (sky, smoke, a wall) should survive on one of them.
            if spread < SUBSTANCE_SPREAD and edges < SUBSTANCE_EDGES:
                continue
        scored.append((m, c, spread, edges))

    if not scored:
        return None, "every window is static or empty"

    # Liveliest first, then let the model veto from the top down.
    scored.sort(reverse=True)
    name = os.path.basename(src)
    if VISION:
        finalists = scored[:VISION_FINALISTS]
        # Judged in parallel batches. Sequential calls were fine at three
        # finalists; at eight they would add half a minute per source, and a
        # render already waits on downloads and ffmpeg.
        verdicts = {}
        import concurrent.futures as cf
        with cf.ThreadPoolExecutor(max_workers=VISION_PARALLEL) as pool:
            futures = {pool.submit(_vision_check, src, c, subject, action): c
                       for _m, c, _s, _e in finalists}
            for fut in cf.as_completed(futures):
                try:
                    verdicts[futures[fut]] = fut.result()
                except Exception:
                    verdicts[futures[fut]] = (None, None, None, "")

        asked = False
        for m, c, _s, _e in finalists:
            usable, on_topic, shows_action, shows = verdicts.get(
                c, (None, None, None, ""))
            if usable is None:
                continue       # this frame went unjudged; try the next
            asked = True
            if usable and on_topic is not False and shows_action is not False:
                return c, f"motion {m:.1f}, shows {shows or 'usable footage'}"
            if usable and on_topic is False:
                why = "off topic"
            elif usable and shows_action is False:
                why = "not the action"
            else:
                why = "unusable frame"
            detail = f": {shows}" if shows else ""
            print(f"  broll: {name} @{c:.0f}s rejected by vision "
                  f"({why}{detail})")
        if asked:
            # Every finalist was rejected. Falling back to the top window here
            # would ship exactly the frame the model just refused, which is how
            # a generic crowd shot ended up on a clip about people being killed.
            return None, "no window shows the subject"
    m, c, _s, _e = scored[0]
    return c, f"motion {m:.1f}"


def prepare(src, out_path, seconds=HOLD, canvas=(1080, 1920), fps=30,
            subject=None, action=None):
    """Cut `seconds` from `src` and normalise it to the canvas. True on success.

    Picks the liveliest candidate window rather than a fixed offset. A cutaway
    exists to show something happening; a still frame held for three seconds
    looks like a stock photo dropped into the edit, and three of the four
    cutaways in one shipped clip were exactly that — measured mean motion 0.31
    and 0.37 against 16.3 for the one that worked.

    `subject` is what the footage has to be OF. Without it the gate can only
    ask whether a frame is readable, which let a calm unrelated crowd through
    onto a clip about people being killed.

    Probing costs a few seconds of ffmpeg per candidate, which is cheap next to
    the download that already happened.
    """
    if not src or not os.path.exists(src):
        return False
    try:
        dur = _duration(src)
        w, h = canvas
        latest = max(0.0, dur - seconds - 0.5)
        at, why = _pick_window(src, dur, latest, seconds,
                               subject or VISION_SUBJECT, action)
        if at is None:
            print(f"  broll: {os.path.basename(src)} has no usable window "
                  f"({why}), skipping")
            return False
        print(f"  broll: {os.path.basename(src)} @{at:.0f}s — {why}")
        res = subprocess.run(
            [FFMPEG, "-v", "error", "-y", "-ss", f"{at:.2f}", "-t",
             f"{seconds:.2f}", "-i", src,
             "-vf", (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                     f"crop={w}:{h},setsar=1,fps={fps}"),
             "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             out_path],
            capture_output=True, text=True, timeout=600)
    except Exception as exc:
        print("broll_place: prepare failed (%s: %s)"
              % (type(exc).__name__, exc), file=sys.stderr)
        return False
    if res.returncode != 0:
        print("broll_place: ffmpeg rejected %s — %s"
              % (os.path.basename(src), res.stderr.strip()[:200]),
              file=sys.stderr)
        return False
    return os.path.exists(out_path) and os.path.getsize(out_path) > 1000


def _duration(path):
    """Seconds, from ffmpeg's own banner. 0.0 when unreadable."""
    try:
        res = subprocess.run([FFMPEG, "-i", path], capture_output=True,
                             text=True, timeout=120)
    except Exception:
        return 0.0
    for line in res.stderr.splitlines():
        if "Duration:" in line:
            try:
                hms = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = hms.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
            except Exception:
                return 0.0
    return 0.0


# How solid a cutaway sits over the speaker. Fully opaque reads as a cut to a
# different event, which is wrong for context footage: this clip is Prabowo
# talking ABOUT Gaza, not a report from Gaza. The layer reads as reference
# rather than as a claim about where the camera is.
#
# 0.55 across the whole frame was the wrong middle. Reviewing a delivered clip:
# "too high in opacity for a background and too low for a statement, so it
# neither reads cleanly as Gaza footage nor leaves the speaker crisp" — the
# rubble landed on the lectern, his hands and the state emblem, and both
# pictures lost. Hence BAND below: the footage lives in the upper band where
# there is only backdrop, and the speaker's face and lectern stay clean. Within
# that band it can afford to be more solid than 0.55.
INSERT_OPACITY = float(os.environ.get("CLIPPER_BROLL_OPACITY", "0.78"))
# Fraction of frame height the cutaway occupies, measured from the top. 0.46
# clears the head of a podium speaker framed at this distance; the feather
# below keeps the lower edge from reading as a hard-cut window.
BAND_FRAC = float(os.environ.get("CLIPPER_BROLL_BAND", "0.46"))
# Height of the fade at the bottom edge of the band, as a fraction of the band.
BAND_FEATHER = float(os.environ.get("CLIPPER_BROLL_FEATHER", "0.22"))


def _band_filters(canvas_h, alpha, band_frac=None, feather=None):
    """Filters that confine an insert to a feathered band along the top.

    Returns a filter string to append to the insert's chain, or "" when the
    band is disabled (band_frac >= 1).

    The mask is built with `geq` on the alpha plane rather than by cropping,
    because the insert has already been scaled to the full canvas: cropping it
    would change the framing of the footage, and the house rule is that the
    canvas and the aspect never move to achieve a look.
    """
    frac = BAND_FRAC if band_frac is None else float(band_frac)
    feath = BAND_FEATHER if feather is None else float(feather)
    if frac >= 1.0:
        return ""
    band_px = max(1.0, canvas_h * frac)
    fade_px = max(1.0, band_px * feath)
    solid_px = max(0.0, band_px - fade_px)
    # alpha = full above solid_px, ramps to 0 across fade_px, 0 below the band.
    return (
        ",format=yuva420p,"
        f"geq=lum='p(X,Y)':cb='p(X,Y)':cr='p(X,Y)':"
        f"a='if(lt(Y,{solid_px:.1f}),{alpha * 255:.1f},"
        f"if(lt(Y,{band_px:.1f}),"
        f"{alpha * 255:.1f}*(1-(Y-{solid_px:.1f})/{fade_px:.1f}),0))'")


def overlay_chain(src_label, insert_idx, t_start, t_end, dst_label,
                  opacity=None, canvas_h=None, band_frac=None):
    """One ffmpeg overlay chain putting an insert on screen for its window.

    The `setpts` shift is the whole reason cutaways looked like photographs.
    An overlay input starts at timeline t=0 regardless of when `enable` opens,
    so a 3s insert placed at 11.3s had already run out of frames by the time
    the window opened, and ffmpeg held its final frame for the full hold. The
    source footage measured 11-16 motion while the same insert measured 0.22
    once composited: not a still source, a still caused by the compositor.
    Shifting the insert's PTS so its first frame lands at `t_start` is what
    makes it play.

    opacity < 1 keeps the speaker visible through the cutaway, which is the
    honest way to show context footage: the viewer can see it is a reference
    layer over the speech rather than a cut to a different event.

    Pass `canvas_h` to confine the footage to a band along the top instead of
    washing the whole frame. See _band_filters for why that is the default.

    `shortest=0` matters: the insert is a couple of seconds and the main stream
    is the whole clip, so without it the output would end at the insert.
    """
    alpha = INSERT_OPACITY if opacity is None else float(opacity)
    label = f"[bsrc{insert_idx}]"
    pre = f"[{insert_idx}:v]setpts=PTS-STARTPTS+{t_start:.3f}/TB"
    band = _band_filters(canvas_h, alpha, band_frac) if canvas_h else ""
    if band:
        # The band mask writes the alpha plane itself, so the flat alpha scale
        # below would undo it. One or the other, never both.
        pre += band
    elif alpha < 1.0:
        # format first: the source may have no alpha plane to scale.
        pre += f",format=yuva420p,colorchannelmixer=aa={alpha:.3f}"
    pre += label
    return (f"{pre};{src_label}{label}overlay=0:0:shortest=0:"
            f"enable='between(t,{t_start:.3f},{t_end:.3f})'{dst_label}")


if __name__ == "__main__":
    base = 100.0
    words = [{"word": w, "start": base + i * 1.3, "end": base + i * 1.3 + 0.5}
             for i, w in enumerate(
                 ("saya minta maaf tadi saya inget saudara kita di Palestina "
                  "mereka dibantai mereka dibom mereka diserang terus menerus "
                  "dan kita seolah kurang berdaya untuk membantu mereka semua "
                  "ini mendorong kita para kiai para ulama para pendidik di "
                  "institusi seperti Gontor ini harus memicu kehendak besar"
                  ).split())]
    dur = 60.0

    # No filter means no inserts: position alone is not a reason to cut away.
    assert phrase_windows(words, base, dur) == []

    import broll
    names = {n.lower() for n in broll.proper_nouns(" ".join(
        w["word"] for w in words))}
    assert names, "expected proper nouns in the fixture"
    is_name = (lambda w: w.lower() in names)

    wins = phrase_windows(words, base, dur, terms_fn=is_name)
    assert wins, "no windows proposed"
    assert all(w.lower() in names for _t, _e, w in wins), wins
    assert all(t >= EDGE_PAD for t, _e, _w in wins), wins
    assert all(e <= dur - EDGE_PAD + 0.001 for _t, e, _w in wins), wins
    gaps = [b[0] - a[0] for a, b in zip(wins, wins[1:])]
    assert all(g >= MIN_GAP for g in gaps), gaps
    assert len(wins) <= MAX_INSERTS

    # Burst: consecutive action words in one sentence may chain closer than
    # MIN_GAP, because "dibantai, dibom, diserang" is one escalating line and
    # spacing them 9s apart dropped two of the three in a delivered clip.
    import broll as _b
    action_or_name = (lambda w: w.lower() in names or bool(_b.action_terms(w)))
    bw = phrase_windows(words, base, dur, terms_fn=action_or_name)
    bgaps = [b[0] - a[0] for a, b in zip(bw, bw[1:])]
    assert len(bw) > len(wins), (bw, wins)
    assert any(g < MIN_GAP for g in bgaps), bgaps
    # but never closer than one burst hold, or two inserts overlap
    assert all(g >= BURST_HOLD - 0.001 for g in bgaps), bgaps
    assert len(bw) <= MAX_INSERTS, bw

    # A sentence boundary ends the chain even when the words are close.
    assert _ends_sentence("dibantai.") and not _ends_sentence("dibantai,")

    # a clip too short to hold an insert gets none, rather than a cramped one
    assert phrase_windows(words, base, 8.0, terms_fn=is_name) == []
    assert phrase_windows([], base, dur, terms_fn=is_name) == []
    assert phrase_windows(None, base, dur, terms_fn=is_name) == []
    # a filter nothing satisfies yields nothing, not a fallback pick
    assert phrase_windows(words, base, dur, terms_fn=lambda w: False) == []

    chain = overlay_chain("[v3]", 7, 12.0, 14.2, "[v4]")
    assert "shortest=0" in chain and "between(t,12.000,14.200)" in chain, chain

    assert prepare(None, "/tmp/x.mp4") is False
    assert prepare("/does/not/exist.mp4", "/tmp/x.mp4") is False

    print("broll_place.py self-check OK — windows:",
          [(t, w) for t, _e, w in wins])
