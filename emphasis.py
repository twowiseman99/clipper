"""Which words the speaker actually leaned on.

The model's punchline_words is a guess about what matters in the sentence. This
measures what the speaker did with their voice: the words they pushed louder
and slower than the ones around them. In "mereka DISERANG terus MENERUS" the
stress is audible, and a caption that ignores it loses the delivery.

Two signals, both relative to a local window rather than the whole clip, so a
quiet passage still gets its own emphasis rather than being flattened by a loud
one elsewhere:

  loudness  RMS of the word against the median RMS of its neighbours
  stretch   how slowly the word was said, per syllable

A word needs to clear the bar on the combined score to count. Returning
everything would be the same as returning nothing.
"""

import array
import math
import os
import re
import subprocess
import sys

SR = 16000
# A stalled ffmpeg must not outlive the clip it is scoring.
PCM_TIMEOUT = int(os.environ.get("CLIPPER_EMPH_TIMEOUT", "120"))
# How many words on each side form the local baseline.
WINDOW = int(os.environ.get("CLIPPER_EMPH_WINDOW", "8"))
# Score above which a word counts as stressed. Raise it for fewer words.
THRESHOLD = float(os.environ.get("CLIPPER_EMPH_THRESHOLD", "1.15"))
# Never mark more than this share of a phrase, whatever the scores say.
MAX_SHARE = float(os.environ.get("CLIPPER_EMPH_MAX_SHARE", "0.4"))
# Function words carry stress rarely and read as noise when marked.
STOPWORDS = {
    "yang", "dan", "di", "ke", "dari", "itu", "ini", "untuk", "dengan", "pada",
    "adalah", "akan", "sudah", "telah", "juga", "saja", "ada", "atau", "tapi",
    "tetapi", "karena", "kalau", "jika", "agar", "supaya", "oleh", "dalam",
    "para", "kita", "saya", "kami", "mereka", "dia", "nya", "se", "the", "a",
    "an", "of", "to", "in", "is", "are", "was", "were", "and", "or", "but",
}


def _pcm(path, start, end):
    """Mono 16k samples for [start, end) as an int16 array, empty on failure.

    Kept as array('h') rather than a list of floats: a list costs ~8x the
    memory (24+ bytes per Python float object vs 2 bytes per sample), which is
    47 MB for an 82s clip and grows linearly with the segment. The /32768
    scaling is folded into _rms instead, where it is one divide on the result
    rather than one allocation per sample.
    """
    dur = max(0.05, end - start)
    try:
        out = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
             "-i", path, "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
            capture_output=True, timeout=PCM_TIMEOUT).stdout
    except subprocess.TimeoutExpired:
        # Without a timeout a stalled decode hangs the whole render. Scoring
        # nothing costs plain captions; hanging costs the job.
        print("emphasis: pcm read timed out after %ss" % PCM_TIMEOUT,
              file=sys.stderr)
        return array.array("h")
    except Exception as exc:
        print("emphasis: pcm read failed (%s: %s)" % (type(exc).__name__, exc),
              file=sys.stderr)
        return array.array("h")
    if not out:
        return array.array("h")
    a = array.array("h")
    a.frombytes(out[:len(out) // 2 * 2])
    return a


def _rms(samples):
    """RMS of int16 samples, normalised to 0..1."""
    if not samples:
        return 0.0
    total = 0
    for v in samples:
        total += v * v
    return math.sqrt(total / len(samples)) / 32768.0


def _syllables(word):
    """Rough syllable count: Indonesian is close to one per vowel group."""
    groups = re.findall(r"[aeiouAEIOU]+", word)
    return max(1, len(groups))


def _median(values):
    vals = sorted(v for v in values if v > 0)
    if not vals:
        return 0.0
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def score_words(video_path, words, clip_start=None, clip_end=None):
    """Attach a `stress` score to each word. Higher means more emphasis.

    Words are scored in place on a copy; the input list is not modified. On any
    audio failure every score is 0.0, which downstream reads as "no emphasis
    detected" and falls back to the model's punchline words.
    """
    picked = [w for w in words
              if (clip_start is None or w["end"] > clip_start)
              and (clip_end is None or w["start"] < clip_end)]
    out = [dict(w, stress=0.0) for w in picked]
    if not out:
        return out

    lo = min(w["start"] for w in out)
    hi = max(w["end"] for w in out)
    samples = _pcm(video_path, lo, hi)
    if not samples:
        return out

    for w in out:
        s = int((w["start"] - lo) * SR)
        e = int((w["end"] - lo) * SR)
        chunk = samples[max(0, s):max(0, e)]
        w["_rms"] = _rms(chunk)
        # Duration alone is misleading: a word followed by a pause looks long.
        # Per-syllable time is what makes a drawn-out word measurable.
        syl = _syllables(w["word"])
        w["_pace"] = (w["end"] - w["start"]) / syl

    for i, w in enumerate(out):
        lo_i, hi_i = max(0, i - WINDOW), min(len(out), i + WINDOW + 1)
        near = out[lo_i:hi_i]
        med_r = _median([x["_rms"] for x in near])
        med_p = _median([x["_pace"] for x in near])
        loud = (w["_rms"] / med_r) if med_r else 1.0
        slow = (w["_pace"] / med_p) if med_p else 1.0
        # Loudness leads: a stressed word is pushed harder more reliably than
        # it is stretched, and pace alone flags every word before a pause.
        w["stress"] = round(loud * 0.7 + slow * 0.3, 3)

    for w in out:
        w.pop("_rms", None)
        w.pop("_pace", None)
    return out


def emphatic(scored, threshold=THRESHOLD, max_share=MAX_SHARE):
    """The subset of `scored` the speaker leaned on, as a set of lower words."""
    real = [w for w in scored
            if re.sub(r"[^\w]", "", w["word"]).lower() not in STOPWORDS
            and len(re.sub(r"[^\w]", "", w["word"])) > 2]
    hits = [w for w in real if w.get("stress", 0) >= threshold]
    cap = max(1, int(len(scored) * max_share))
    hits.sort(key=lambda w: -w.get("stress", 0))
    return {re.sub(r"[^\w]", "", w["word"]).lower() for w in hits[:cap]}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: emphasis.py VIDEO [start end]")
        raise SystemExit(2)
    import transcribe
    words, _ = transcribe.transcribe(sys.argv[1])
    t0 = float(sys.argv[2]) if len(sys.argv) > 2 else None
    t1 = float(sys.argv[3]) if len(sys.argv) > 3 else None
    sc = score_words(sys.argv[1], words, t0, t1)
    hot = emphatic(sc)
    for item in sc[:40]:
        key = re.sub(r"[^\w]", "", item["word"]).lower()
        print("  %-14s %.2f%s" % (item["word"], item["stress"],
                                  "  <<<" if key in hot else ""))
    print("\nstressed:", sorted(hot))
