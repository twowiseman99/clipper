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
import datetime
import difflib

import audit
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
#
# This list is a filter, not a guarantee: `Apalagi` at the start of a sentence
# got through an earlier version and sent a cutaway search after a word that
# names nothing, which returned cartoon game art. Callers that act on the result
# should also require the name to recur — see `repeated_names`.
_SENTENCE_CASE = {
    "saya", "kita", "mereka", "kami", "para", "momen", "ini", "itu", "dia",
    "sebuah", "setelah", "ketika", "karena", "bahwa", "namun", "tapi", "dan",
    "video", "klip", "pidato", "mengapa", "kenapa", "bagaimana", "ribuan",
    # Sentence openers and conjunctions that are not subjects.
    "apalagi", "jangan", "kalau", "tetapi", "sebab", "sehingga", "maka",
    "selain", "bahkan", "memang", "sebagai", "sementara", "meski", "meskipun",
    "walaupun", "sedangkan", "supaya", "agar", "hingga", "sampai", "ketika",
    "sekarang", "nanti", "kemudian", "akhirnya", "pertama", "kedua", "banyak",
    "semoga", "mudah", "harus", "bisa", "akan", "sudah", "belum", "pernah",
    "setiap", "seluruh", "segala", "beberapa", "sebagian", "masing",
    # Verbs and adjectives that sentence-case turns into fake names.
    "mendorong", "membela", "membantu", "melihat", "mengatakan", "berbicara",
    "terima", "tolong", "mari", "ayo", "demi", "lewat", "tanpa", "dalam",
}


# Actions that carry their own footage. A name alone searches badly: "Palestina"
# returns more speeches, which is what the clip already shows. "Palestina dibom"
# returns news coverage of the event being described, which is the shot the
# viewer is picturing while the speaker talks. Values are the search wording,
# keyed by what the transcript might say.
#
# Deliberately a small hand-written list, not a model call. These are the words
# a political clip actually stresses, and a wrong guess here spends a download
# and puts unrelated footage on screen.
_ACTION_TERMS = {
    "dibom": "dibom serangan",
    "bom": "dibom serangan",
    "pemboman": "dibom serangan",
    "diserang": "diserang serangan",
    "serang": "diserang serangan",
    "serangan": "diserang serangan",
    "dibantai": "korban serangan",
    "bantai": "korban serangan",
    "dibunuh": "korban serangan",
    "korban": "korban",
    "mengungsi": "pengungsi",
    "pengungsi": "pengungsi",
    "kelaparan": "kelaparan krisis",
    "hancur": "kehancuran reruntuhan",
    "reruntuhan": "kehancuran reruntuhan",
    "demonstrasi": "demonstrasi aksi",
    "aksi": "demonstrasi aksi",
    "bantuan": "bantuan kemanusiaan",
    "kemanusiaan": "bantuan kemanusiaan",
}


def action_terms(phrase):
    """Footage-bearing actions mentioned in `phrase`, as search wording.

    Returns the search phrasing rather than the word that was said: the
    transcript may carry any of several forms ("bom", "dibom", "pemboman") and
    they all want the same footage.
    """
    out = []
    for raw in re.findall(r"\w+", str(phrase or "").lower()):
        term = _ACTION_TERMS.get(raw)
        if term and term not in out:
            out.append(term)
    return out


# What each action has to LOOK like, for the frame gate. The search wording
# above gets the right video; this gets the right second of it.
#
# The gap these close: a clip said "mereka dibom" over footage of people
# picking through rubble. Rubble is the aftermath of a bombing, and the source
# video was correct, but the word was "bombed" and the frame showed no bombing.
# The operator's verdict was blunt: "mereka di bom tapi footagenya bukan bom."
# A subject-only gate cannot catch that — it asked "is this Gaza?", never "is
# this the thing the sentence just said?".
_ACTION_LOOKS = {
    "dibom serangan": ("an explosion, airstrike impact, blast fireball, or the "
                       "smoke plume rising from a strike"),
    "diserang serangan": ("an attack in progress — explosions, strikes, armed "
                          "assault, firing, or impacts"),
    "korban serangan": ("casualties — wounded or dead people, bodies, "
                        "stretchers, funerals, medics carrying victims"),
    "korban": ("casualties — wounded or dead people, bodies, stretchers, "
               "medics carrying victims"),
    "pengungsi": ("people displaced — families fleeing, carrying belongings, "
                  "refugee tents or camps"),
    "kelaparan krisis": ("hunger — food queues, aid distribution, emaciated "
                         "people, empty markets"),
    "kehancuran reruntuhan": ("destruction — collapsed or flattened buildings, "
                              "rubble, ruined streets"),
    "demonstrasi aksi": ("a protest — crowds marching, banners, placards, "
                         "flags raised"),
    "bantuan kemanusiaan": ("aid — trucks, supply convoys, distribution of "
                            "food or medical help"),
}


def action_look(term):
    """How footage for `term` has to look on screen. "" when unknown.

    Unknown actions return "" on purpose: the frame gate then falls back to
    judging the subject alone, which is weaker but never blocks a cutaway for
    a word this table has not learned yet.
    """
    return _ACTION_LOOKS.get(str(term or "").strip().lower(), "")


def repeated_names(*texts, minimum=2):
    """Proper nouns that appear at least `minimum` times.

    A cutaway is only worth searching for when the clip keeps returning to the
    subject. A name mentioned once is usually sentence-case noise, and acting on
    it is how a Palestine clip ended up cutting to cartoon game art.
    """
    counts = {}
    for text in texts:
        if not text:
            continue
        for name in proper_nouns(text):
            counts[name] = counts.get(name, 0) + text.count(name)
    return sorted((n for n, c in counts.items() if c >= minimum),
                  key=lambda n: (-counts[n], n))


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


def anchor_names(context, transcript, max_distance=0.2):
    """Trusted spellings for search terms: context wins, transcript snaps to it.

    Two sources disagree about how a name is spelled and they are not equal.
    The context line is typed by the operator, so it is correct by definition.
    The transcript is what Whisper heard, and it rewrites names it does not know
    ("Gontor" into "Gontar", "Prabowo" into "Prabowa"). Searching the heard
    spelling returns footage of something else entirely.

    So: every context name is trusted as-is. A transcript name is kept only if
    it is already close to a context name, in which case the CONTEXT spelling is
    returned in its place. Transcript names with no anchor are dropped, because
    an unanchored name cannot be checked against anything.

    Returns {heard_or_typed: trusted_spelling}. Lowercase keys, original case
    values, so a caller can map either direction.

    This is deliberately narrow. It does not correct names the operator never
    mentioned — there is nothing to correct them against, and guessing is how a
    wrong name becomes a wrong cutaway.
    """
    trusted = proper_nouns(context or "")
    out = {n.lower(): n for n in trusted}
    if not trusted:
        return out
    for heard in proper_nouns(transcript or ""):
        key = heard.lower()
        if key in out:
            continue
        best, best_d = None, 1.0
        for name in trusted:
            d = 1.0 - difflib.SequenceMatcher(None, key, name.lower()).ratio()
            if d < best_d:
                best, best_d = name, d
        if best is not None and best_d <= max_distance:
            out[key] = best
    return out


def hook_terms(transcript, context="", speaker=""):
    """Search terms for HOOK footage: the person, not the sentence.

    Hook b-roll only has to show the same speaker, so the query is their name
    plus one subject word — broad enough to find other footage of them.
    """
    names = [speaker] if speaker else proper_nouns(context, transcript)[:2]
    subject = [t for t in query_terms(transcript, context, limit=2)
               if t not in {n.lower() for n in names}]
    return [n for n in names if n] + subject[:1]


def insert_terms(phrase, context="", limit=3, topic=""):
    """Search terms for an INSERT at one phrase — what is being said right now.

    The phrase drives the query; context contributes only its proper nouns, not
    its wording. Letting context words compete on frequency pulled in "banyak"
    and "depan" from the operator's framing line, which searched the framing
    instead of the moment.

    `topic` is the clip's event, and it is needed because a cutaway is usually
    triggered by a bare proper noun. On a clip about a school-meal poisoning
    the trigger was "Gibran", so the query was literally ["Gibran"] and YouTube
    returned seven videos about his diploma case at the Constitutional Court —
    all correctly rejected as off topic, 37 frames, zero cutaways. Measured on
    the same search backend:

        ["Gibran"]                -> Sidang Sengketa Ijazah Gibran ...
        ["Gibran", "keracunan"]   -> Wapres Gibran Minta Maaf ke Orang Tua
                                     Murid Keracunan MBG

    The footage existed the whole time; the query never asked for it. A name
    alone identifies a person, not an event, and news channels cover one person
    across unrelated stories.
    """
    names = proper_nouns(context, phrase)[:1]
    taken = {n.lower() for n in names}
    words = [w for w in query_terms(phrase, limit=limit + 2)
             if w not in taken]
    # Event words go in front of whatever the phrase contributed: they are what
    # distinguishes this story from every other story about the same person.
    event = [w for w in query_terms(topic, limit=limit)
             if w not in taken and w not in words] if topic else []
    out = names + event + words
    # Dedupe while keeping order; query_terms can repeat a word that also
    # appears in the topic.
    seen, uniq = set(), []
    for w in out:
        k = w.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(w)
    return uniq[:limit + 1]


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


def relevant(hits, terms, require=1):
    """Keep only hits whose TITLE carries at least `require` of the terms.

    yt-dlp returns whatever the search ranks, and the ranking does not care what
    the clip is about: a query built from a bad term returned cartoon game art
    for a speech about Palestine, and nothing downstream noticed. Checking the
    title is a weak signal, but it is the only one available before downloading,
    and it rejects the obvious mismatches.
    """
    wanted = []
    for t in (terms or ()):
        # Terms can be multi-word ("Palestina dibom"), and a title almost never
        # carries the exact phrase. Match on the individual words instead, or
        # every action-driven search gets filtered out before it is probed.
        for word in re.findall(r"\w+", str(t).lower()):
            if len(word) >= 4 and word not in wanted:
                wanted.append(word)
    if not wanted:
        return []
    out = []
    for hit in hits or ():
        title = str(hit.get("title", "")).lower()
        if sum(1 for t in wanted if t in title) >= require:
            out.append(hit)
    return out


# Credibility floor for cutaway footage. The operator's rule is that b-roll must
# be recent, actually watched, and not a hoax or AI-generated — and none of that
# can be read off a thumbnail, so these stand in for it:
#   * a verified channel with a real following is accountable for what it posts,
#     which is the closest available proxy for "not a hoax";
#   * view count filters clips nobody has watched, where fabrications survive;
#   * an age cap keeps the footage current rather than a decade-old reupload.
# None of this detects AI footage directly. It raises the cost of a fake passing,
# and the title screen below rejects the labels fakes advertise.
MIN_VIEWS = int(os.environ.get("CLIPPER_BROLL_MIN_VIEWS", "20000"))
# The view floor exists to screen out reupload accounts, and on a verified
# channel that job is already done by the verification itself. Keeping one
# number for both cost real footage: searches for the Gaza strikes returned
# 7-8 relevant Kompas/CNN packages and exactly ONE cleared 20k, so the frame
# gate had a single source to judge and a clip shipped with no cutaways at
# all. A verified broadcaster's 600-view upload is not a hoax risk; it is a
# quiet news day.
MIN_VIEWS_VERIFIED = int(os.environ.get("CLIPPER_BROLL_MIN_VIEWS_VERIFIED",
                                        "500"))
MAX_AGE_DAYS = int(os.environ.get("CLIPPER_BROLL_MAX_AGE_DAYS", "1460"))
MIN_FOLLOWERS = int(os.environ.get("CLIPPER_BROLL_MIN_FOLLOWERS", "50000"))
# Titles that advertise synthetic or unverified footage. The operator forbids
# generated footage outright, so anything self-labelling as such is rejected
# before it is downloaded.
_FAKE_MARKERS = (
    "ai generated", "ai-generated", "generated by ai", "ai video", "veo",
    "sora", "midjourney", "runway", "deepfake", "deep fake", "sintetis",
    "animation", "animasi", "cartoon", "kartun", "game", "gameplay",
    "simulation", "simulasi", "ilustrasi", "illustration", "cgi", "vfx",
    "hoax", "hoaks", "rekayasa", "parodi", "parody", "prank", "fiksi",
    "trailer", "film", "movie", "drama", "sinopsis", "review",
)


def credible(hit, min_views=None, max_age_days=None, min_followers=None):
    """(True, "") when a hit clears the credibility floor, else (False, reason).

    Returns the reason so a rejection is visible in the render log instead of
    looking like an empty search.
    """
    min_views = MIN_VIEWS if min_views is None else min_views
    max_age_days = MAX_AGE_DAYS if max_age_days is None else max_age_days
    min_followers = MIN_FOLLOWERS if min_followers is None else min_followers

    title = str(hit.get("title", "")).lower()
    for marker in _FAKE_MARKERS:
        if marker in title:
            return False, f"title says '{marker}'"

    # A verified channel OR a large following: either is accountability. Both
    # are absent on the reupload accounts that carry hoax footage.
    verified = bool(hit.get("channel_is_verified"))
    try:
        followers = int(hit.get("channel_follower_count") or 0)
    except (TypeError, ValueError):
        followers = 0
    if not verified and followers < min_followers:
        return False, f"unverified channel with {followers} followers"

    try:
        views = int(hit.get("view_count") or 0)
    except (TypeError, ValueError):
        return False, "view count unreadable"
    # Accountability first, reach second: a verified broadcaster clears a much
    # lower floor, because on that channel the view count is measuring interest
    # rather than trustworthiness.
    floor = MIN_VIEWS_VERIFIED if (verified or followers >= min_followers) \
        else min_views
    if views < floor:
        return False, f"{views} views below {floor}"

    date = str(hit.get("upload_date") or "")
    if len(date) == 8 and date.isdigit():
        try:
            age = (datetime.date.today()
                   - datetime.date(int(date[:4]), int(date[4:6]),
                                   int(date[6:8]))).days
        except ValueError:
            return False, f"upload date unreadable ({date})"
        if age > max_age_days:
            return False, f"{age} days old, over {max_age_days}"
    elif max_age_days > 0:
        # No date means the age rule cannot be applied, and the rule is the
        # operator's. Unverifiable is treated as failing, not as passing.
        return False, "no upload date"
    return True, ""


def probe_meta(video_id):
    """Views, upload date and channel standing for one video. {} on failure.

    The flat search does not carry an upload date, so this is a second request
    per candidate — about 3 seconds. Paid once per insert, and only for hits
    that already matched on title.
    """
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extractor_args": {"youtube": {"player_client": ["web_embedded"]}},
    }
    if fetch.YTDLP_COOKIES:
        opts["cookiefile"] = fetch.YTDLP_COOKIES
    if not _VIDEO_ID.fullmatch(str(video_id or "")):
        return {}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info("https://youtu.be/%s" % video_id,
                                    download=False) or {}
    except Exception as exc:
        print("broll: probe failed for %s (%s: %s)"
              % (video_id, type(exc).__name__, exc), file=sys.stderr)
        return {}
    return {k: info.get(k) for k in
            ("view_count", "upload_date", "channel_is_verified",
             "channel_follower_count", "title", "duration")}


def vetted(hits, terms, limit=1, **kw):
    """Hits that match on title AND clear the credibility floor, best first.

    Ordered by view count: among clips that all pass, the most watched is the
    one most likely to be the real footage of the event rather than a reupload.

    `limit` defaults to 1 for callers that only want a single source, but the
    frame gate can now reject an entire video, so a caller that means to try
    several must ask for several. Returning one hit while the caller believed
    it had a shortlist is how a clip shipped with every cutaway dropped and
    "1 sources checked" in the warning.
    """
    out = []
    # The brief for this division: what was searched, and how many candidates
    # came back. "0 pass · 12 reject" reads differently when only three
    # candidates were ever offered.
    hits = list(hits)
    audit.briefed("sourcing", f"terms = {list(terms)!r}",
                  f"{len(hits)} candidate(s)", f"want {limit}")
    for hit in relevant(hits, terms):
        meta = probe_meta(hit.get("id"))
        if not meta:
            continue
        merged = dict(hit)
        merged.update({k: v for k, v in meta.items() if v is not None})
        ok, why = credible(merged, **kw)
        if not ok:
            audit.rejected("sourcing", merged.get("title", "")[:48], why)
            print("broll: rejected %r — %s" % (merged.get("title", "")[:60],
                                               why), file=sys.stderr)
            continue
        audit.passed("sourcing", merged.get("title", "")[:48],
                     f"{int(merged.get('view_count') or 0):,} views")
        out.append(merged)
    out.sort(key=lambda h: -int(h.get("view_count") or 0))
    return out[:limit]


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
    # Offline first: the credibility floor against real shapes from the field.
    # No network, so this runs as a gate even when YouTube is unreachable.
    today = datetime.date.today().strftime("%Y%m%d")
    old_date = (datetime.date.today()
                - datetime.timedelta(days=MAX_AGE_DAYS + 30)).strftime("%Y%m%d")

    # The exact clip that shipped in v6 and should never have.
    cartoon = {"title": "PUTING BELIUNG - Game Petualangan Animasi",
               "view_count": 734778, "channel_is_verified": True,
               "channel_follower_count": 5_000_000, "upload_date": today}
    ok, why = credible(cartoon)
    # Rejected on whichever marker is hit first — 'animasi' or 'game', both
    # correct reasons. Asserting the exact marker would test the list's order.
    assert not ok and ("game" in why or "animasi" in why), (ok, why)

    low_reach = {"title": "Serangan Gaza Terbaru", "view_count": 50000,
                 "channel_is_verified": False, "channel_follower_count": 100,
                 "upload_date": today}
    ok, why = credible(low_reach)
    assert not ok and "unverified" in why, (ok, why)

    too_old = {"title": "Serangan Gaza Terbaru", "view_count": 500000,
               "channel_is_verified": True,
               "channel_follower_count": 1_000_000, "upload_date": old_date}
    ok, why = credible(too_old)
    assert not ok and "old" in why, (ok, why)

    few_views = {"title": "Serangan Gaza Terbaru", "view_count": 50,
                 "channel_is_verified": True,
                 "channel_follower_count": 1_000_000, "upload_date": today}
    ok, why = credible(few_views)
    assert not ok and "views" in why, (ok, why)

    no_date = {"title": "Serangan Gaza Terbaru", "view_count": 500000,
               "channel_is_verified": True,
               "channel_follower_count": 1_000_000}
    ok, why = credible(no_date)
    assert not ok and "date" in why, (ok, why)

    real = {"title": "Serangan Udara Israel Bombardir Gaza Tengah - Reuters",
            "view_count": 500000, "channel_is_verified": True,
            "channel_follower_count": 1_000_000, "upload_date": today}
    ok, why = credible(real)
    assert ok, why

    # relevant() is a title filter and nothing more: it must NOT be mistaken
    # for credibility, or the cartoon passes again.
    picks = relevant([cartoon, real], ["Gaza"])
    assert real in picks, picks
    assert vetted([], ["Gaza"]) == []

    print("broll.py self-check OK — game/old/low-reach/low-view/no-date "
          "rejected, real footage kept")

    if len(sys.argv) > 1:
        text, ctx = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
        print("HOOK terms  :", hook_terms(text, ctx))
        for hit in search(hook_terms(text, ctx), results=4):
            print("   %-13s %5ss  %s"
                  % (hit["id"], hit["duration"], hit["title"][:55]))
        phrase = "mereka dibantai mereka dibom mereka diserang terus menerus"
        print("INSERT terms:", insert_terms(phrase, ctx))
        terms = insert_terms(phrase, ctx)
        for hit in vetted(search(terms, results=8), terms, limit=3):
            print("   VETTED %-13s %8s views  %s"
                  % (hit["id"], hit.get("view_count"), hit["title"][:50]))
