"""Pick the frame to FREEZE by what is in it, not by where the clip stops.

The jamet ending freezes at the end of the clip's own speech, which is right —
the operator asked for exactly that ("dia selesai dimana langsung freeze").
What was wrong is that `loop` clones whatever frame happens to sit at that
timestamp. Nothing checked who was in it. Moving the stop point to the end of
"...yang dimasak ibu" therefore moved the frozen frame onto a bystander, and
the operator got a 5-second still of a woman nobody can name.

The previous render froze on the right person by luck, not by rule. This module
is the rule.

It is deliberately separate from `edit.py`: choosing a frame needs a vision
call, and the renderer must stay runnable with no network and no key. When no
frame qualifies the caller gets None and the mechanical freeze stands, with a
warning — the house rule is that a veto has no fallback, so over-strictness has
to show up as a warning rather than as a wrong still.
"""
import concurrent.futures as cf
import os
import subprocess
import tempfile

# Judge this many frames per second of search window. The freeze needs ONE
# frame, so density beats breadth: a 1s grid called 149.0s a hit and the 0.2s
# grid around it found the face was turned in 4 of the 5 neighbouring frames.
# 0.4s melewatkan frame yang benar. Grid ini TERIKAT ke titik freeze, bukan ke
# jam absolut, jadi menggeser stop point 0.2s menggeser seluruh grid: dengan
# --seconds 28.4 kandidatnya jadi 149.0 dan 149.4, sementara frame Gibran yang
# sudah diverifikasi ada di 149.2 — tidak pernah dicoba, dan gate melaporkan
# "tidak ada frame yang jelas menampilkan subjek" seolah footagenya yang kosong.
# Di kerumunan yang bergerak, 0.2s sudah cukup untuk berganti orang.
STEP = float(os.environ.get("CLIPPER_FREEZE_STEP", "0.2"))
# How far before the freeze point to look. Kept narrow on purpose: a still from
# far away is a different shot, and cutting to it reads as a mistake rather
# than an edit.
LOOKBACK = float(os.environ.get("CLIPPER_FREEZE_LOOKBACK", "6.0"))
MIN_CONF = float(os.environ.get("CLIPPER_FREEZE_MIN_CONF", "0.55"))

_SYS = ("You identify people in frames from Indonesian news footage. "
        "Answer with JSON only, no prose.")


def _question(subject):
    return (
        "Frame from Indonesian news footage, about to be FROZEN on screen for "
        "five seconds as a clip's closing portrait.\n\n"
        "Rank the faces in this frame by HOW READABLE each one is — how well "
        "a viewer can see and identify that person's face. Readability is "
        "decided ONLY by: how much of the face is turned toward the camera, "
        "how sharp it is, and how well it is lit.\n\n"
        "Being nearest the camera, biggest in frame, or in front of the "
        "others does NOT make a face readable. A big foreground head seen in "
        "profile or in shadow is LESS readable than a smaller face further "
        "back that is lit and turned toward the lens. Judge the face, not the "
        "body or the position.\n\n"
        "Is the MOST READABLE face in this frame %s?\n\n"
        'JSON only: {"ok": true|false, "confidence": 0.0-1.0, '
        '"most_readable": "whose face is most readable", '
        '"why": "turned toward camera / profile / shadow / blurred", '
        '"blurred": true|false}' % subject)


# A bare name is a weak brief for a vision model: it has to both know the face
# and judge the frame. Pairing the name with a physical description lets it
# fall back on appearance, which is what actually decides whether the still
# reads as a portrait of that person. Gate questions get the FOOTAGE's subject,
# not the clip's.
KNOWN = {
    "gibran": "GIBRAN RAKABUMING RAKA (Indonesian vice president: man, "
              "early-to-mid 30s, slim build, short neat dark hair, usually in "
              "a dark jacket or white shirt)",
    "prabowo": "PRABOWO SUBIANTO (Indonesian president: heavy-set man in his "
               "70s, grey hair, often in a safari jacket or batik)",
    "megawati": "MEGAWATI SOEKARNOPUTRI (woman in her late 70s, short dark "
                "hair, often in a red or batik jacket)",
    "jokowi": "JOKO WIDODO (thin man in his 60s, hollow cheeks, short dark "
              "hair, usually a white shirt)",
}


def describe(name):
    """Turn a bare proper noun into a brief a vision model can act on."""
    key = str(name or "").strip().lower()
    for k, v in KNOWN.items():
        if k in key:
            return v
    return str(name or "").strip()


# The gate must judge the pixels the VIEWER gets, not the pixels handed in.
# This repo has already paid for that lesson twice: a hook verified 5/5 on a
# 1280x720 cut shipped as a different person because the renderer keeps the
# middle of the frame (references/verify-after-the-crop.md), and then a freeze
# verified at source 149.2s delivered a still of a bystander because pillar
# composition and the pan move the window.
#
# So the frame is composed here with the SAME geometry as the pillar branch of
# edit.py before it is judged: blurred cover background, sharp card at
# PILLAR_COVER of canvas height, overlaid centred. The pan offset is the one
# part that is not reproduced — it is computed from a face track across the
# whole clip — so the card is centred, which is the pan's resting position.
#
# Gate and viewer therefore look at the same composition. If this drifts from
# edit.py the mismatch comes back, so it reads the real constants rather than
# copying their values.
def _compose_filter():
    try:
        import edit
        cw, ch = edit.CANVAS_W, edit.CANVAS_H
        cover, zoom = edit.PILLAR_COVER, edit.PILLAR_BG_ZOOM
        blur, dim, sat = edit.PILLAR_BLUR, edit.PILLAR_BG_DIM, edit.PILLAR_BG_SAT
    except Exception:
        cw, ch, cover, zoom, blur, dim, sat = 1080, 1920, 0.62, 1.35, 18, 0.35, 0.6
    card_h = int(ch * cover) // 2 * 2
    return (
        "split=2[bg][fg];"
        "[bg]scale=%d:%d:force_original_aspect_ratio=increase,"
        "scale=iw*%.2f:-2,crop=%d:%d,gblur=sigma=%.0f,"
        "eq=brightness=-%.2f:saturation=%.2f[bgb];"
        "[fg]scale=-2:%d,scale=w='max(iw,%d)':h=-2,"
        "crop=%d:%d:x='(iw-ow)/2':y='(ih-oh)/2'[fgs];"
        "[bgb][fgs]overlay=(W-w)/2:(H-h)/2"
        % (cw, ch, zoom, cw, ch, blur, dim, sat,
           card_h, cw, cw, card_h))


def _grab(video, t, composed=True):
    """One JPEG at t, composed to the delivered 1080x1920 frame by default.

    `composed=False` returns the raw source frame and exists only for probes;
    a gate that uses it is judging something the viewer never sees.
    """
    fd, path = tempfile.mkstemp(suffix=".jpg")
    os.close(fd)
    try:
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", "%.3f" % t, "-i", video,
               "-frames:v", "1", "-q:v", "3"]
        if composed:
            cmd += ["-vf", _compose_filter()]
        cmd.append(path)
        subprocess.run(cmd, capture_output=True, timeout=120)
        if os.path.getsize(path) > 1000:
            return open(path, "rb").read()
        return None
    except Exception:
        return None
    finally:
        if os.path.exists(path):
            os.unlink(path)


def render_still(video, t, out_path):
    """Write the composed 1080x1920 still the gate judged, as a PNG.

    The renderer overlays this file instead of recomposing the timestamp, so
    the pixels that passed the gate are the pixels the viewer gets. Returns
    True when the file exists and is non-trivial.
    """
    try:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", "%.3f" % t, "-i", video,
             "-frames:v", "1", "-vf", _compose_filter(), out_path],
            capture_output=True, timeout=180)
        return os.path.exists(out_path) and os.path.getsize(out_path) > 10000
    except Exception:
        return False


def pick(video, freeze_at, subject, audit=None, clip_end=None):
    """Source timestamp of the best frame to freeze, or None.

    `freeze_at` is the absolute position in `video` where the ending begins.
    Candidates run BOTH WAYS from it, because `loop` inserts its clones and the
    encoder's -t drops the real tail — so a frame from after the freeze point
    is still a frame the viewer never otherwise sees, and it is just as valid a
    still. Looking only backwards is what rejected this clip the first time:
    the six seconds before the freeze were a row of uniformed officers, while
    the subject was clearly in frame two seconds AFTER it, inside the clip.

    The frame nearest the freeze point wins among qualifiers, not the most
    confident one — the still should look like the picture stopping, not like a
    cut to somewhere else.
    """
    import ai

    if not subject or freeze_at is None:
        return None
    n = max(1, int(round(LOOKBACK / STEP)))
    spots = [freeze_at - i * STEP for i in range(n + 1)]
    if clip_end is not None:
        spots += [freeze_at + i * STEP for i in range(1, n + 1)
                  if freeze_at + i * STEP <= clip_end]
    spots = sorted({round(t, 2) for t in spots if t >= 0})
    q = _question(describe(subject))

    def judge(t):
        jpg = _grab(video, t)
        if not jpg:
            return t, False, 0.0, "no frame"
        try:
            r = ai.vision_json(_SYS, q, [jpg], temperature=0.0)
            # Every condition is enforced here as well as in the prompt. A
            # model that answers ok=true while also reporting frontal=false or
            # naming a competing face has contradicted itself, and the judgment
            # that matters is the structured one. Prompt rules alone are not
            # enough for this class of error — the same lesson as the flag
            # emoji on the Palestine clip.
            ok = bool(r.get("ok")) and not bool(r.get("blurred"))
            who = "%s (%s)" % (str(r.get("most_readable") or "")[:40],
                               str(r.get("why") or "")[:26])
            return (t, ok, float(r.get("confidence") or 0.0), who)
        except Exception as e:
            # One frame failing must not abandon the rest: a `break` on a
            # router error once discarded a whole b-roll source.
            return t, False, 0.0, "error %s" % str(e)[:40]

    rows = []
    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(judge, spots))

    good = [r for r in rows if r[1] and r[2] >= MIN_CONF]
    if audit is not None:
        for t, ok, conf, who in sorted(rows):
            audit("freeze-pick", "%.2fs %s conf %.2f — %s"
                  % (t, "OK" if ok else "no", conf, who))
    if not good:
        return None
    # Nearest to the freeze point, not the most confident and not the latest.
    return min(good, key=lambda r: abs(r[0] - freeze_at))[0]
