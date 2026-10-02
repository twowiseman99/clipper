"""Find b-roll on YouTube for a clip's own topic.

The user's rule: never generate footage, always source real video from YouTube
on the same subject. So this searches rather than creates, and it never invents
a query — the terms come from the transcript the clip was cut from.

Results are filtered before anything is downloaded. A search hit is useless as
b-roll if it is the source video itself (we would cut back to the same shot),
if it is a Short (vertical, already cropped, usually captioned), or if it is a
multi-hour stream whose download would dwarf the clip we are making.
"""

import os
import re
import subprocess
import sys

import fetch

# Hits shorter than this are usually Shorts or clipped re-uploads with burned-in
# captions; longer than this is a stream we do not want to pull down.
MIN_SECONDS = int(os.environ.get("CLIPPER_BROLL_MIN_SECONDS", "45"))
MAX_SECONDS = int(os.environ.get("CLIPPER_BROLL_MAX_SECONDS", "1800"))
RESULTS = int(os.environ.get("CLIPPER_BROLL_RESULTS", "8"))

# YouTube ids are 11 chars of [A-Za-z0-9_-]. Matched strictly because the id is
# interpolated into a URL and later handed to the downloader.
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")

# Words that say nothing about the subject, so they only dilute the query.
_NOISE = {
    "yang", "dan", "di", "ke", "dari", "untuk", "dengan", "itu", "ini", "ada",
    "saya", "kita", "mereka", "kami", "akan", "sudah", "telah", "juga", "pada",
    "adalah", "tidak", "bukan", "atau", "karena", "kalau", "jadi", "bisa",
    "harus", "lebih", "seperti", "tadi", "terus", "semua", "satu", "kira",
    "the", "and", "for", "that", "this", "with",
}

# Common openers that sentence-case capitalises. A first word in this set is
# not treated as a name; anything else at position 0 is.
_SENTENCE_CASE = {
    "saya", "kita", "mereka", "kami", "para", "momen", "ini", "itu", "dia",
    "sebuah", "setelah", "ketika", "karena", "bahwa", "namun", "tapi", "dan",
    "video", "klip", "pidato", "mengapa", "kenapa", "bagaimana", "ribuan",
}


def proper_nouns(*texts):
    """Capitalised words that are not sentence-openers — people and places.

    The speaker's name is the anchor for hook footage: the user's flow keeps one
    main video and allows any hook clip "asal orangnya masih sama". Frequency
    alone picked filler like "banyak"/"depan", which searched the grammar of the
    sentence instead of its subject.
    """
    counts = {}
    for text in texts:
        if not text:
            continue
        for sentence in re.split(r"[.!?\n]", text):
            tokens = re.findall(r"[A-Za-z\u00c0-\u024f][\w\u00c0-\u024f'-]*",
                                sentence)
            for pos, raw in enumerate(tokens):
                # Skipping position 0 outright drops the subject when the text
                # opens with it — "Prabowo membela Palestina" lost "Prabowo".
                # A first word only counts if it is not also a common word,
                # which is what sentence-case would make it.
                if not raw[0].isupper():
                    continue
                if pos == 0 and raw.lower() in _SENTENCE_CASE:
                    continue
                word = raw.strip("-'")
                if len(word) < 4 or word.lower() in _NOISE:
                    continue
                counts[word] = counts.get(word, 0) + 1
    return sorted(counts, key=lambda w: (-counts[w], w))


def hook_terms(transcript, context="", speaker=""):
    """Search terms for HOOK footage: the person, not the sentence.

    Hook b-roll only has to show the same speaker, so the query is their name
    plus one subject word — broad enough to find other footage of them.
    """
    names = [speaker] if speaker else proper_nouns(context, transcript)[:2]
    subject = [t for t in query_terms(transcript, context, limit=2)
               if t not in {n.lower() for n in names}]
    return [n for n in names if n] + subject[:1]


def insert_terms(phrase, context="", limit=3):
    """Search terms for an INSERT at one phrase — what is being said right now.

    The phrase drives the query; context contributes only its proper nouns, not
    its wording. Letting context words compete on frequency pulled in "banyak"
    and "depan" from the operator's framing line, which searched the framing
    instead of the moment.
    """
    names = proper_nouns(context, phrase)[:1]
    taken = {n.lower() for n in names}
    words = [w for w in query_terms(phrase, limit=limit + 2)
             if w not in taken]
    return names + words[:limit]


def query_terms(transcript, context="", limit=4):
    """Subject words for a search query, most frequent first.

    Context (the operator's one-line framing) is weighted above the transcript:
    it is the only part written by a human who knows what the clip is about.
    """
    counts = {}
    for weight, text in ((3, context or ""), (1, transcript or "")):
        for raw in re.findall(r"[A-Za-z\u00c0-\u024f]+", text):
            word = raw.lower()
            if len(word) < 4 or word in _NOISE:
                continue
            counts[word] = counts.get(word, 0) + weight
    ranked = sorted(counts, key=lambda w: (-counts[w], w))
    return ranked[:limit]


def search(terms, exclude_ids=(), results=RESULTS):
    """YouTube hits for `terms`, minus the source video, Shorts and streams.

    Returns a list of {id, title, duration, url}. An empty list means no usable
    b-roll was found, which is a valid outcome: the caller renders without it
    rather than substituting something off-topic.
    """
    if not terms:
        return []
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": True,
        "extractor_args": {"youtube": {"player_client": ["web_embedded"]}},
    }
    if fetch.YTDLP_COOKIES:
        opts["cookiefile"] = fetch.YTDLP_COOKIES

    # Terms reach this from a transcript, so they are scrubbed to word
    # characters before going into the query. yt-dlp reads "ytsearchN:" up to
    # the first colon, so a term containing one would change what is requested.
    safe = [re.sub(r"[^\w\u00c0-\u024f -]", "", str(t)).strip()
            for t in terms]
    safe = [t for t in safe if t]
    if not safe:
        return []
    query = "ytsearch%d:%s" % (int(results), " ".join(safe))
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(query, download=False)
    except Exception as exc:
        # Never fatal: a clip without b-roll is still a clip. Printed rather
        # than swallowed, because a silent empty list looked like "no results"
        # when the real cause was an extractor break.
        print("broll: search failed (%s: %s)" % (type(exc).__name__, exc),
              file=sys.stderr)
        return []

    out = []
    skipped = {"source": 0, "short": 0, "long": 0, "bad": 0}
    for entry in (info or {}).get("entries") or []:
        vid = entry.get("id")
        # Everything in `entry` comes off the network, so nothing is trusted on
        # shape. A non-string id would be formatted straight into a URL and a
        # non-numeric duration would raise inside the comparison below.
        if not isinstance(vid, str) or not _VIDEO_ID.fullmatch(vid):
            skipped["bad"] += 1
            continue
        try:
            secs = float(entry.get("duration") or 0)
        except (TypeError, ValueError):
            skipped["bad"] += 1
            continue
        if vid in exclude_ids:
            skipped["source"] += 1
            continue
        if secs < MIN_SECONDS:
            skipped["short"] += 1
            continue
        if secs > MAX_SECONDS:
            skipped["long"] += 1
            continue
        out.append({
            "id": vid,
            "title": str(entry.get("title") or "")[:200],
            "duration": int(secs),
            "url": "https://youtu.be/%s" % vid,
        })
    print("broll: %d usable (skipped %d source, %d short, %d long, %d malformed)"
          % (len(out), skipped["source"], skipped["short"], skipped["long"],
             skipped["bad"]),
          file=sys.stderr)
    return out


def probe_playable(path):
    """True if ffmpeg can decode a frame — guards against truncated downloads."""
    try:
        res = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", path, "-frames:v", "1",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=60)
    except Exception:
        return False
    return res.returncode == 0


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else ""
    ctx = sys.argv[2] if len(sys.argv) > 2 else ""
    print("HOOK terms  :", hook_terms(text, ctx))
    for hit in search(hook_terms(text, ctx), results=4):
        print("   %-13s %5ss  %s" % (hit["id"], hit["duration"], hit["title"][:55]))
    phrase = "mereka dibantai mereka dibom mereka diserang terus menerus"
    print("INSERT terms:", insert_terms(phrase, ctx))
    for hit in search(insert_terms(phrase, ctx), results=4):
        print("   %-13s %5ss  %s" % (hit["id"], hit["duration"], hit["title"][:55]))
