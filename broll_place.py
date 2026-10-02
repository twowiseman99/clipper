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
MAX_INSERTS = int(os.environ.get("CLIPPER_BROLL_MAX", "5"))
# Keep inserts out of the first and last stretch: the opening belongs to the
# hook, and cutting away from the closing line throws away the payoff.
EDGE_PAD = float(os.environ.get("CLIPPER_BROLL_EDGE", "6"))
FFMPEG = os.environ.get("CLIPPER_FFMPEG", "ffmpeg")


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
    for w in items:
        t = float(w["start"]) - clip_start
        if t < EDGE_PAD or t + HOLD > dur - EDGE_PAD:
            continue
        if t - last < MIN_GAP:
            continue
        word = str(w.get("word", "")).strip()
        if len(word) < 4:
            continue
        # A proper noun is the strongest signal that footage of a specific
        # thing exists: "Palestina" is searchable, "mereka" is not.
        if terms_fn is not None and not terms_fn(word):
            continue
        out.append((round(t, 3), round(min(t + HOLD, dur), 3), word))
        last = t
        if len(out) >= MAX_INSERTS:
            break
    return out


def prepare(src, out_path, seconds=HOLD, canvas=(1080, 1920), fps=30):
    """Cut `seconds` from `src` and normalise it to the canvas. True on success.

    Taken from the middle of the source: the first seconds of a YouTube video
    are usually a title card or an intro, which is not footage of anything.
    """
    if not src or not os.path.exists(src):
        return False
    try:
        dur = _duration(src)
        # Start a third in, so a long video does not contribute its intro.
        at = max(0.0, min(dur / 3.0, max(0.0, dur - seconds - 0.5)))
        w, h = canvas
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


def overlay_chain(src_label, insert_idx, t_start, t_end, dst_label):
    """One ffmpeg overlay chain putting an insert on screen for its window.

    `shortest=0` matters: the insert is a couple of seconds and the main stream
    is the whole clip, so without it the output would end at the insert.
    """
    return (f"{src_label}[{insert_idx}:v]overlay=0:0:shortest=0:"
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
