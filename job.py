"""Agent-facing entry point: two links in, one clip out.

Built for an agent (Hermes) to drive over chat, so everything it needs is
machine readable and nothing needs a human at a terminal:

    python job.py --list                      # catalogue of styles and music
    python job.py --opening URL --content URL # render, print a JSON result

One job runs at a time per host, and a request arriving while another is in
flight exits 3 with {"busy": true} rather than queueing behind it.

Both commands print JSON on stdout and nothing else; progress goes to stderr.
A failure prints {"ok": false, "error": ...} and exits non-zero, so the caller
never has to parse a traceback to tell the user what went wrong. It also files
a diagnostic report (see report.py) and returns its path, so the failure can be
looked at later without shell access to the box.

This module deliberately stops at the file: posting to Discord, parsing the
chat message and holding the conversation belong to the agent, which knows its
own transport. What it gets from here is a stable contract.
"""
import argparse
import json
import os
import re
import sys
import time
import traceback

_BASE = os.path.dirname(os.path.abspath(__file__))


def _load_dotenv():
    """Load clipper/.env into os.environ before any module reads its config.

    edit.py, fetch.py and transcribe.py read CLIPPER_* at import time, so the
    .env has to be applied before they are imported. ai.py parses the same file
    but only when metadata imports it, which is too late for edit's defaults.
    """
    path = os.path.join(_BASE, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

OUT_DIR = os.environ.get("CLIPPER_JOB_OUT", os.path.join(_BASE, "jobs"))
# Run a language reviewer over the transcript before captions are drawn. Costs
# one model call per job and only ever corrects words in place.
LANG_REVIEW = os.environ.get("CLIPPER_LANG_REVIEW", "1") not in ("0", "", "false")
# Search YouTube for b-roll and cut away to it mid-clip. Off by default: it adds
# a download per insert, and a clip without cutaways is still a clip.
BROLL_INSERT = os.environ.get("CLIPPER_BROLL_INSERT", "0") not in ("0", "", "false")
# How many search hits to actually open per cutaway. The frame gate can reject
# an entire source (no window shows the action), so trying only the top hit
# loses the cutaway whenever that one video happens to be aftermath footage.
BROLL_SOURCE_TRIES = int(os.environ.get("CLIPPER_BROLL_TRIES", "3"))
# Longest subject handed to the b-roll frame gate, in words. The gate answers
# "does this frame show X" reliably for a thing, badly for a sentence: each
# extra clause is another way real footage can be scored a miss. Measured: an
# eleven-word subject produced 35 rejects and zero cutaways on a clip where
# usable footage existed.
TOPIC_MAX_WORDS = int(os.environ.get("CLIPPER_TOPIC_MAX_WORDS", "7"))
LOCK_PATH = os.environ.get("CLIPPER_JOB_LOCK", os.path.join(_BASE, ".job.lock"))
# Seconds to wait for a job already running. Zero means refuse immediately,
# which is the right answer over chat: a caller would rather be told to try
# again than watch a request hang.
LOCK_WAIT = float(os.environ.get("CLIPPER_JOB_LOCK_WAIT", "0"))


class Busy(RuntimeError):
    """Another job holds the machine."""


class _Lock:
    """One job at a time on this host.

    Whisper and ffmpeg each want most of a small VPS; two jobs in parallel do
    not run twice as fast, they run out of memory. The lock is advisory and
    per-host, held only for the duration of the run.
    """

    def __init__(self, path=LOCK_PATH, wait=LOCK_WAIT):
        self.path, self.wait, self.fh = path, wait, None

    def __enter__(self):
        import fcntl
        self.fh = open(self.path, "w")
        deadline = time.time() + self.wait
        while True:
            try:
                fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.fh.write(f"{os.getpid()} {time.time():.0f}\n")
                self.fh.flush()
                return self
            except OSError:
                if time.time() >= deadline:
                    self.fh.close()
                    self.fh = None
                    raise Busy(
                        "another clip is being rendered on this host — try "
                        "again in a minute")
                time.sleep(1.0)

    def __exit__(self, *exc):
        import fcntl
        if self.fh:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()
            self.fh = None
        return False


def _log(msg):
    print(msg, file=sys.stderr, flush=True)


# Catalogue: what an agent can ask for.

def catalogue():
    """Everything the caller may choose from, with a line of copy for each.

    The agent renders this straight into chat, so each entry carries the label
    a person should see rather than only the identifier the code wants.
    """
    import bgm
    import edit
    import segments

    tracks = bgm.load_tracks()
    return {
        "frame_mode": [
            {"id": "cover", "label": "Full frame",
             "desc": "Footage fills the whole 9:16 frame. Best for vertical "
                     "footage; crops the sides hard on landscape."},
            {"id": "fill", "label": "Band + blur",
             "desc": "Footage as a centred band over a blurred copy of itself. "
                     "A middle ground for landscape footage."},
            {"id": "fit", "label": "Whole frame, letterboxed",
             "desc": "Nothing is cropped. The subject ends up smallest."},
        ],
        "caption_style": [
            {"id": "phrase", "label": "Phrase captions",
             "desc": "Whole phrases in gold, two lines max, punchline tinted."},
            {"id": "karaoke", "label": "Word-by-word",
             "desc": "Per-word highlight as the speaker says it."},
            {"id": "editorial", "label": "Editorial serif",
             "desc": "Thin serif beside the speaker, mixed roman/italic, "
                     "punchline word set large. No box, no stroke."},
        ],
        "hook_style": [
            {"id": "boxes", "label": "Pull quote",
             "desc": "Teal quote mark over stacked white boxes, ragged right."},
            {"id": "card", "label": "Single card",
             "desc": "One continuous white card, no quote mark."},
        ],
        "opening": [
            {"id": "broll", "label": "B-roll first",
             "desc": "Second link plays first with the hook over it, then cuts "
                     "to the content. Nothing of the speech is lost."},
            {"id": "direct", "label": "Straight in",
             "desc": "No opening clip. The content starts straight away with no "
                     "hook, unless you write hook text yourself, in which case "
                     "it rides over the first seconds and those carry no "
                     "subtitle."},
        ],
        "moods": list(bgm.MOODS),
        "music": [{"file": t["file"], "mood": t["mood"] or ["untagged"]}
                  for t in tracks],
        "duration_windows": {k: list(v) for k, v in segments.DURATION_RANGES.items()},
        "defaults": {
            "frame_mode": edit.FRAME_MODE,
            "caption_style": edit.CAPTION_STYLE,
            "hook_style": edit.HOOK_STYLE,
            "hook_seconds": edit.HOOK_DUR,
        },
        "accepted_links": ["youtube", "google drive"],
    }


# One job: two links in, one clip out.

def _fetch_one(url, tag):
    """Download one link to its own folder. Returns the biggest video file.

    A path that already exists on disk is used as-is. The hook footage is often
    a verified cut of a longer reel — the scene was located, judged frame by
    frame and trimmed — and re-downloading the whole reel to seek inside it
    throws that verification away.
    """
    import fetch

    if os.path.exists(url):
        _log(f"[{tag}] local file -> {os.path.basename(url)}")
        return os.path.abspath(url)

    kind = fetch.classify_source(url)
    if kind not in fetch.ROUTES:
        raise ValueError(
            f"{tag}: {kind} links are not supported yet — send a YouTube or "
            f"Google Drive link")
    # Keyed by the URL, not by the run: two jobs never share a folder (a Drive
    # fetch walks the whole directory and would otherwise pick up the previous
    # job's file), and the same link retried reuses its download and its
    # cached transcript instead of paying for both again.
    slot = fetch.cache_tag(url)
    _log(f"[{tag}] downloading ({kind}) -> {slot}")
    try:
        files = fetch.fetch(kind, url, slot)
    except fetch.SourceTooBig as e:
        raise fetch.SourceTooBig(f"{tag}: {e}") from None
    if not files:
        raise RuntimeError(f"{tag}: nothing downloadable at that link")
    return max(files, key=os.path.getsize)



def _hook_for(asked, opening, topical, from_model):
    """Which hook text ends up on the clip, or None for no hook at all.

    A hook is drawn only when something asks for one: hook text the caller
    wrote, or an opening clip that needs text over it. With neither, the clip
    has no hook, rather than one the model wrote because it could.

    That is not only a style call. The seconds under a hook carry no subtitle,
    because nothing is allowed to share the screen with it, so a hook nobody
    asked for costs the opening line of speech.
    """
    if asked:
        return asked
    if opening:
        return topical or from_model
    return None


def _freeze_floor(path, after, fps=10):
    """Lowest frame-to-frame motion in `path` after `after` seconds, or None.

    Separates a frozen frame from moving video. A still reads ~0; a still being
    shaken on the beat spikes and then decays back to ~0 between beats; real
    video never returns to zero because something is always changing. So the
    FLOOR over the window is the discriminating statistic, not the mean — the
    mean of a shaking still and the mean of moving video are similar, which is
    why the old settings-only check could not tell them apart.

    Measured on the renders that prompted this: inside a working frozen ending
    the floor was 0.39-0.87, and in the tail where the video had resumed it was
    2.70 with a mean of 6.5.
    """
    try:
        import subprocess
        import tempfile
        import edit as _e
        # metadata=print writes to ffmpeg's log, which `-v error` suppresses
        # entirely — the first version of this probe parsed an empty stderr and
        # returned None, i.e. "could not measure", on a perfectly good file.
        # Its `file=` option is independent of the log level.
        fd, tmp = tempfile.mkstemp(prefix="freeze_", suffix=".txt")
        os.close(fd)
        try:
            run = subprocess.run(
                [_e.FFMPEG, "-v", "error", "-ss", f"{after:.3f}", "-i", path,
                 "-vf", (f"fps={fps},scale=120:-1,tblend=all_mode=difference,"
                         "signalstats,metadata=print:"
                         f"key=lavfi.signalstats.YAVG:file={tmp}"),
                 "-f", "null", "-"],
                capture_output=True, text=True, timeout=180)
            if run.returncode != 0:
                return None
            with open(tmp) as fh:
                vals = [float(v) for v in re.findall(r"YAVG=([0-9.]+)",
                                                     fh.read())]
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except Exception:
        return None
    # The first difference after a seek compares against a frame outside the
    # window, so drop it.
    vals = vals[1:]
    return min(vals) if vals else None


def _delivery_copy(path, max_mb):
    """Re-encode under max_mb when the render is too big to send. Returns the
    new path, or None when the original already fits or the squeeze fails.

    The render targets 6 Mbps because it is the file that gets uploaded to a
    platform, and a 90s clip at that rate is 66 MB. Discord takes 10 MB on a
    free account and 50 MB on Nitro Basic, so the thing a chat agent hands back
    has to be a smaller copy. The original is left alone: the delivery copy is
    for looking at, not for publishing.
    """
    import subprocess

    import edit

    if max_mb <= 0 or os.path.getsize(path) <= max_mb * 1024 * 1024:
        return None
    seconds = None
    try:
        import fetch
        seconds = fetch.probe_seconds(path)
    except Exception:
        pass
    if not seconds:
        return None
    # Leave headroom for the container and the audio track we are about to fix
    # at 96k; aiming at exactly the cap overshoots it often enough to matter.
    total_kbit = (max_mb * 8 * 1024) / seconds * 0.90
    video_kbit = max(300, int(total_kbit - 96))
    small = os.path.splitext(path)[0] + "_small.mp4"
    cmd = [edit.FFMPEG, "-y", "-v", "error", "-i", path,
           "-c:v", edit.CODEC, "-b:v", f"{video_kbit}k",
           "-maxrate", f"{int(video_kbit * 1.3)}k", "-bufsize", f"{video_kbit * 2}k",
           "-preset", "veryfast", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", small]
    if subprocess.run(cmd, capture_output=True, text=True).returncode != 0:
        return None
    if not os.path.exists(small):
        return None
    _log(f"delivery copy: {os.path.getsize(small) / 1048576:.1f} MB "
         f"(original {os.path.getsize(path) / 1048576:.1f} MB)")
    return small


# Prepositions that mark the following proper noun as a place rather than the
# subject of the story. The operator writes the context line as a sentence, so
# "... di Gontor" says plainly that Gontor is where this happened.
_VENUE_MARKERS = ("di", "dari", "ke", "pada", "kepada")
# Words inside a place name itself, so the whole name is caught rather than its
# first token: "di Pondok Modern Gontor" is one venue, not three names.
_PLACE_WORDS = ("pondok", "pesantren", "masjid", "istana", "gedung", "aula",
                "kampus", "universitas", "sekolah", "lapangan", "stadion",
                "balai", "kantor", "desa", "kota", "kabupaten", "provinsi")


def _venue_names(context, names):
    """Names in `context` that read as the location, not the subject.

    A cutaway to the venue is a cutaway to the same event: the clip was already
    shot there. One shipped clip cut to an audience shot of Gontor exactly as
    the speaker said "Gontor", which looks like a continuity mistake rather
    than an edit. Only names the operator marked with a place preposition are
    excluded, so a story genuinely about a place still gets its footage.
    """
    tokens = re.findall(r"\w+", str(context or ""))
    venues = set()
    for i, tok in enumerate(tokens):
        key = tok.lower()
        if key not in names:
            continue
        # Kept in original case: capitalisation is the signal that a word is
        # part of the place name ("Pondok Modern Gontor"), so lowercasing here
        # would make the istitle() check below dead code.
        prev = tokens[max(0, i - 3):i]
        if not prev:
            continue
        # "di Gontor" — directly after a place preposition.
        if prev[-1].lower() in _VENUE_MARKERS:
            venues.add(key)
            continue
        # "di Pondok Modern Gontor" — preposition a little further back, with
        # only place words or more of the name in between.
        for j in range(len(prev) - 1, -1, -1):
            low = prev[j].lower()
            if low in _VENUE_MARKERS:
                if all(p.lower() in _PLACE_WORDS or p.istitle()
                       or p.lower() in names for p in prev[j + 1:]):
                    venues.add(key)
                break
            if low not in _PLACE_WORDS and not prev[j].istitle():
                break
    return venues


# The two kinds of clip this tool cuts. The operator asked for the second one
# as a named type, not as a pile of flags: "Ini jadiin jenis klip kedua,
# pertama kan sedih ya kmrn kita develop".
#
# Each type sets mood, outro and b-roll TOGETHER, because that is where the
# register mismatches came from. A hype shake over a melancholy BGM, or news
# b-roll of a hospital ward under a jedag-jedug beat, are both wrong in the
# same way: the layers disagree about what the clip is. One flag now settles
# all three.
#
# `broll` is False for jamet on purpose — the operator was explicit: "Duh,
# jangan beritanya dong, tapi pas bagian si gibran ngomong suruh bawa bekal aja
# cukup". The viral cut is the speaker's own sentence, not a news package.
CLIP_TYPES = {
    "sedih": {
        "mood": "emotional",
        "outro": "melancholy",
        "broll": True,
        "flash": False,
        "why": "sombre cut: news b-roll, desaturating outro, dip to black",
    },
    "jamet": {
        "mood": "hype",
        "outro": "jamet",
        "broll": False,
        "flash": True,
        "why": "viral cut: speaker's own sentence, freeze-frame shake outro",
    },
}


def _clip_act(seg_words):
    """What the cutaways in this clip must actually SHOW, or "" when nothing.

    Decided once per clip, like the topic. The gate already asks WHERE a frame
    was shot; on its own that let a mass funeral and a quiet border terminal —
    both really in Palestine, both the aftermath — run under "mereka dibantai"
    and "mereka dibom". The operator's rule: footage for those words has to be
    war material from the news, not its consequences.

    This is deliberately NOT the verb under each caption. Per-word gating threw
    away real footage of the same event three renders in a row. It asks instead
    whether the clip is about violence at all, and only then demands that the
    cutaway show it. A clip with no violence words gets "" and keeps the
    location-only question.
    """
    for w in seg_words or ():
        key = re.sub(r"[^\w-]", "", str(w.get("word", ""))).lower()
        if key and key in _ACT_WORDS:
            # A casualty word on its own is not violence: "korban keracunan
            # MBG" is a food-poisoning story, so _ACT_SOFT words are not
            # consulted here at all. It takes a hard word to make a war clip.
            return _ACT_LOOK
    return ""


# Violence words that make a clip a war clip. Taken from the transcript, not
# from --context: the speaker's own words are what the captions will show.
#
# Every word here must mean violence BY ITSELF. "korban", "meninggal" and
# "tewas" do not: Indonesian uses "korban" for the victim of anything at all —
# "korban keracunan MBG", "korban banjir", "korban PHK" — and people die of
# things other than attacks. "korban" alone put a food-poisoning clip under a
# war-footage veto, which rejected 37 frames and shipped zero cutaways while the
# ledger said "no footage passed the gates". Nothing in the gate was broken; the
# word list was.
#
# The replacement is a two-word test: a generic casualty word only counts when
# the clip ALSO names violence (see _ACT_SOFT below). A clip can then say
# "korban" a dozen times without becoming a war clip.
_ACT_WORDS = frozenset((
    "dibantai", "bantai", "dibom", "bom", "pemboman", "diserang", "serang",
    "serangan", "dibunuh", "hancur", "reruntuhan", "gugur",
))

# Casualty words that are NOT evidence of violence on their own. Kept as a
# named set so the next person to widen _ACT_WORDS sees why these are excluded
# rather than re-adding them. "kelaparan" sits here too: famine is a
# catastrophe, but footage of it is not a strike or rubble.
_ACT_SOFT = frozenset(("korban", "tewas", "meninggal", "kelaparan"))

# What the footage has to depict. Phrased as the news material itself —
# strikes, shelling, rubble, casualties being carried — so that a calm
# aftermath shot (an intact terminal, a street scene) does not qualify.
_ACT_LOOK = ("the attack itself or its immediate destruction: strikes, "
             "explosions, smoke over buildings, shelling, collapsed or "
             "burning buildings, rubble, wounded or dead being carried")


def _clip_topic(context, names=(), venues=()):
    """Where the footage has to have been SHOT. Decided once per clip.

    Two mistakes are baked into this function's history, both shipped:

    1. Asked per word ("does this frame show dibom"), which rejected real
       footage of the same event because the verb was not literally visible.

    2. Asked as the speech topic ("Prabowo membela Palestina"), which let a
       pro-Palestine rally in JAKARTA through — the gate could see it was
       Jakarta and still answered on_topic=true, because an Indonesian name
       plus Palestine describes that rally perfectly. It is a correct answer
       to the wrong question.

    What the operator actually requires is a place: "semua frame harus bener
    footage dari palestina yang dibahas". So the speaker's name and the verbs
    are stripped out and what survives is the location and the event there.
    """
    skip = {v.lower() for v in (venues or ())}
    text = str(context or "")
    # Phrases that describe the speaking occasion rather than the event.
    occasion = (r"di depan [^,;]*", r"di hadapan [^,;]*",
                r"dalam pidato[^,;]*", r"saat pidato[^,;]*",
                r"ketika berpidato[^,;]*", r"berpidato[^,;]*",
                r"pada acara[^,;]*", r"dalam acara[^,;]*",
                r"di acara[^,;]*", r"peringatan [^,;]*",
                r"forum [^,;]*", r"sidang [^,;]*")
    # What the SPEAKER does. Keeping these made the subject a person talking,
    # and footage of people talking about a place then counted as that place.
    stance = (r"\bmembela\b", r"\bmenyinggung\b", r"\bbicara soal\b",
              r"\bbicara tentang\b", r"\bbicara\b", r"\bmenyoroti\b",
              r"\bmengecam\b", r"\bmendukung\b", r"\bkomentar soal\b",
              # Things a speaker DOES at the event. Without these, "Gibran minta
              # maaf ke korban keracunan MBG, menyarankan siswa bawa bekal dari
              # rumah yang dimasak ibunya" survived whole and the frame gate was
              # asked whether one frame showed all fifteen words. It showed
              # nothing: 35 rejects, zero cutaways.
              r"\bminta maaf (?:ke|kepada)\b", r"\bminta maaf\b",
              r"\bmenyarankan\b", r"\bmengimbau\b", r"\bmengajak\b",
              r"\bmenjanjikan\b", r"\bmemastikan\b", r"\bmenjenguk\b",
              r"\bmengunjungi\b", r"\bmenemui\b",
              r"\bsoal\b", r"\btentang\b", r"\bmengenai\b")
    parts = []
    for clause in re.split(r"[,;]", text):
        c = clause.strip()
        if not c:
            continue
        for pat in occasion:
            c = re.sub(pat, "", c, flags=re.IGNORECASE).strip()
        if not c:
            continue
        # Drop everything up to and including the stance verb: what is left is
        # what the speaker was talking ABOUT, which is the place and event.
        for pat in stance:
            m = re.search(pat, c, flags=re.IGNORECASE)
            if m:
                c = c[m.end():].strip()
                break
        if not c:
            continue
        # Strip a trailing venue mention: "Palestina di Gontor" would ask the
        # gate for Gaza footage shot in East Java.
        for v in sorted(skip, key=len, reverse=True):
            c = re.sub(r"\b(?:di|dari|ke)\s+%s\b" % re.escape(v), "", c,
                       flags=re.IGNORECASE).strip()
            c = re.sub(r"\b%s\b" % re.escape(v), "", c,
                       flags=re.IGNORECASE).strip()
        c = re.sub(r"\s{2,}", " ", c).strip(" -—,")
        if not c:
            continue
        words = re.findall(r"[\w'-]+", c.lower())
        if words and all(w in skip or w in ("di", "dari", "ke", "yang")
                         for w in words):
            continue
        parts.append(c)
    topic = " ".join(parts).strip(" -—")
    # Keep the FIRST surviving clause, not all of them joined. --context is
    # written as "<what happened>, <what was said about it>", and only the first
    # half is footage-able: the Gibran clip's second clause ("menyarankan siswa
    # bawa bekal dari rumah") is advice, which no news frame shows. Joining both
    # asked the gate for a frame containing an event AND a recommendation, and
    # nothing qualified — 35 rejects, zero cutaways.
    if parts:
        topic = parts[0].strip(" -—")
    # Then cap it. A frame gate answers "does this frame show X" well when X is
    # a thing; past a handful of words X is a sentence with clauses, and every
    # clause is another way real footage can be judged a miss. Indonesian puts
    # the subject first, so keeping the head keeps the event.
    if topic:
        words = topic.split()
        if len(words) > TOPIC_MAX_WORDS:
            topic = " ".join(words[:TOPIC_MAX_WORDS])
        return topic
    # No usable context: fall back to the subjects heard in the clip itself,
    # minus the venue, in the order they were ranked.
    rest = [n for n in (names or ()) if n.lower() not in skip]
    return ", ".join(rest)


def _footage_subject(context, term, venues=()):
    """What the b-roll frame gate should be asked to look for.

    --context describes the SPEECH, not the footage: "Prabowo membela Palestina
    di depan banyak pemimpin negara, di Gontor". Handing that whole string to a
    frame gate asks whether Gaza footage shows Gontor and a podium, which real
    Gaza footage does not, so correct material was logged as "off topic".

    The venue is dropped — the same names already excluded as cutaway triggers
    — along with the clauses that describe the speaking occasion rather than the
    event. What is left is the subject the cutaway is actually about.
    """
    parts = []
    skip = {v.lower() for v in (venues or ())}
    # Clauses about the speaking occasion, not about the event being discussed.
    occasion = ("di depan", "di hadapan", "dalam pidato", "saat pidato",
                "berpidato", "acara", "peringatan", "forum", "sidang")
    for clause in re.split(r"[,;]", str(context or "")):
        c = clause.strip()
        if not c:
            continue
        low = c.lower()
        if any(o in low for o in occasion):
            continue
        words = [w for w in re.findall(r"[\w'-]+", low)]
        # A clause that is only a venue mention ("di Gontor") carries no
        # information about the footage.
        if words and all(w in skip or w in ("di", "dari", "ke") for w in words):
            continue
        parts.append(c)
    if term:
        t = str(term).strip()
        if t.lower() not in skip:
            parts.append(t)
    return " — ".join(parts) if parts else str(term or "").strip()


def _gather_inserts(seg_words, seg_start, dur, context, source_path,
                    warnings=None):
    """Search, download and cut b-roll for this segment. [] on any failure.

    Footage is searched on YouTube, never generated: the clips have to be real
    material on the same subject. Each stage is wrapped because all of them talk
    to something outside this box — the network, yt-dlp, ffmpeg — and none of
    them failing is a reason to lose the clip.

    Pass `warnings` to be told about cutaways that were dropped because no
    footage showed the action. A silently empty b-roll list is how v22 shipped
    with no cutaways at all and nothing in the result to say so.
    """
    notes = warnings if warnings is not None else []
    try:
        import audit
        import broll
        import broll_place
        import edit
        import fetch

        text = " ".join(str(w.get("word", "")) for w in seg_words)
        # Only names the clip returns to: a one-off capital is usually
        # sentence-case noise, and acting on it produced a cutaway to cartoon
        # game art in a clip about Palestine.
        repeated = broll.repeated_names(text, context)
        # A name Whisper mis-hears ("Gontor" -> "Gontar") still has to search
        # under the correct spelling, or the query finds unrelated footage
        # instead of nothing. anchor_names() only trusts what the operator
        # typed in --context; a mis-heard name with no match there is dropped,
        # not guessed.
        anchors = broll.anchor_names(context, text)
        names = set()
        for n in repeated:
            fixed = anchors.get(n.lower())
            if fixed:
                names.add(fixed.lower())
            elif n.lower() in {a.lower() for a in broll.proper_nouns(context or "")}:
                names.add(n.lower())
            # else: heard repeatedly but not in --context and not close to
            # anything that is — no anchor to check it against, so it is
            # dropped rather than searched under a possibly wrong spelling.
        if not names:
            return []
        # The transcript still carries the mis-heard spelling, so matching on
        # the trusted name alone would never fire. Accept a word when either
        # its own spelling or its anchored spelling is a wanted name.
        #
        # Actions open a window too. A name alone searches the subject in the
        # abstract and returns more podium footage; the moment a clip stresses
        # "dibom" or "diserang", the viewer is picturing the event, and that is
        # the shot worth cutting to. Actions are a closed list, so this cannot
        # fire on arbitrary words.
        #
        # The venue is excluded. "Gontor" is where the speech is being given,
        # so footage of it is footage of this same event from another angle —
        # an audience shot at the moment the speaker says the word, which reads
        # as a continuity error rather than a cutaway. The subject of the story
        # is worth cutting to; the room the story is told in is not.
        venues = _venue_names(context or "", names)
        if venues:
            _log(f"b-roll: venue not used as a cutaway trigger: "
                 f"{', '.join(sorted(venues))}")

        def _wanted(word):
            key = str(word).lower()
            anchored = anchors.get(key, "").lower()
            if key in venues or anchored in venues:
                return False
            if key in names or anchored in names:
                return True
            return bool(broll.action_terms(key))

        wins = broll_place.phrase_windows(
            seg_words, seg_start, dur, terms_fn=_wanted)
        if not wins:
            return []

        source_id = os.path.splitext(os.path.basename(source_path or ""))[0]
        out = []
        used = {source_id}
        # Which subject an action belongs to is decided per window, not once per
        # clip. `sorted(names)[0]` picked "gontor" over "palestina" purely on
        # alphabetical order, so "mereka dibom" searched Gontor footage and cut
        # to an audience shot of the venue instead of the event being described.
        #
        # Preference order: a name inside this phrase, then a name from
        # --context in the order the operator WROTE it, then whatever remains.
        # proper_nouns() returns its own sorted order, so the context string is
        # re-scanned here: "Prabowo membela Palestina ... di Gontor" names the
        # subject before the venue, and that order is the operator's intent.
        ctx_all = {n.lower() for n in broll.proper_nouns(context or "")}
        ctx_names = []
        for word in re.findall(r"\w+", str(context or "")):
            key = word.lower()
            if key in ctx_all and key not in ctx_names:
                ctx_names.append(key)
        ordered = ([n for n in ctx_names if n in names]
                   + sorted(n for n in names if n not in ctx_names))

        # Decided once, before the loop: every cutaway in this clip is judged
        # against the same event.
        topic = _clip_topic(context, ordered, venues)
        _log(f"b-roll: topic for every cutaway = {topic!r}")
        # Record the question, not just the answers. An eleven-word subject was
        # what turned a clip with usable footage into 35 rejects, and the report
        # showed only the rejects.
        audit.briefed("footage", f"subject = {topic!r}",
                      f"{len(topic.split())} word(s)",
                      f"from context {str(context or '')[:60]!r}")

        def _subject_for(phrase):
            said = {w.lower() for w in re.findall(r"\w+", str(phrase or ""))}
            for n in ordered:
                if n in said:
                    return n
            return ordered[0] if ordered else ""

        for t0, t1, heard_term in wins:
            # Search under the trusted spelling, not whatever Whisper wrote at
            # this exact word — that is the whole point of anchoring.
            term = anchors.get(heard_term.lower(), heard_term)
            actions = broll.action_terms(heard_term)
            subject = _subject_for(heard_term)
            if actions and subject:
                # News footage of the event, qualified by subject so the result
                # belongs to this story rather than a similar one elsewhere.
                terms = [subject.title(), actions[0]]
            else:
                terms = broll.insert_terms(term, context, topic=topic)
            # relevant() filters the title; vetted() then probes each survivor
            # for views, upload date and channel standing — the operator's
            # rule that footage be recent, actually watched, and not a hoax or
            # AI generation. Rejections are logged with a reason.
            hits = broll.vetted(
                broll.search(terms, exclude_ids=used, results=8), terms,
                limit=BROLL_SOURCE_TRIES)
            if not hits:
                _log(f"b-roll: nothing credible for '{term}', skipping")
                continue
            # What the footage has to show: the EVENT the clip is about, decided
            # once for the whole clip, not the verb under this caption.
            #
            # Asking per word was wrong. A news package about Gaza is footage of
            # one event; demanding each frame depict "dibantai" specifically
            # threw away a funeral procession from that same event, and the
            # whole source went with it. The operator's rule is that the footage
            # be real material of the Palestine being discussed — a question
            # about the event, not about the word.
            #
            # The venue stays out: --context describes the speech, and asking
            # whether Gaza footage shows Gontor correctly returns no.
            #
            # But dropping the act question entirely went too far the other
            # way. With look="" the gate only asked WHERE a frame was shot, so
            # a mass funeral and a border terminal — both genuinely in
            # Palestine, both the aftermath — shipped under "mereka dibantai"
            # and "mereka dibom". The operator's words: "footage dibantai dan
            # di bom harusnya cuplikan perang dari berita". So the act is asked
            # once per clip, at the clip's own level: is this war footage, not
            # is this the specific verb under this caption.
            look = _clip_act(seg_words)
            if look:
                audit.briefed("footage", "act required", look,
                              "violence named in the clip")
                audit.passed("footage", "act required", "war footage only",
                             "clip names violence")
                print(f"b-roll: cutaways must show the act: {look}")
            else:
                audit.briefed("footage", "act required", "none",
                              "no violence word in the clip")
                audit.passed("footage", "act required", "location only",
                             "clip names no violence")
            subject = topic
            # Try more than the top hit. The frame gate rejects whole sources
            # now, and asking only hits[0] meant one rejected video dropped the
            # cutaway entirely: v22 shipped with zero b-roll because both top
            # hits failed while later candidates were never opened.
            cut = None
            chosen = None
            for hit in hits[:BROLL_SOURCE_TRIES]:
                paths = fetch.fetch("youtube", hit["url"], f"broll-{hit['id']}")
                if not paths:
                    continue
                candidate = os.path.join(os.path.dirname(paths[0]),
                                         f"insert-{hit['id']}.mp4")
                if broll_place.prepare(paths[0], candidate, seconds=t1 - t0,
                                       canvas=(edit.CANVAS_W, edit.CANVAS_H),
                                       subject=subject, action=look):
                    used.add(hit["id"])
                    cut = candidate
                    chosen = hit
                    break
                used.add(hit["id"])
            if cut is None:
                notes.append(
                    f"b-roll: no real footage of {topic!r} found for "
                    f"'{heard_term.strip()}' "
                    f"({len(hits[:BROLL_SOURCE_TRIES])} sources checked), "
                    f"cutaway dropped")
                _log(f"b-roll: no source showed {topic!r} for "
                     f"'{term}', cutaway dropped")
                continue
            out.append({"path": cut, "start": t0, "end": t1, "term": term,
                        "title": (chosen or {}).get("title", "")})
        return out
    except Exception as exc:
        _log(f"b-roll unavailable ({type(exc).__name__}: {exc})")
        return []


def run(content_url, opening_url=None, opening_start=0.0, hook=None,
        platform="youtube",
        start=None, seconds=None, mood=None, mood_from_preset=False,
        out=None, max_mb=0, context=None,
        copy_style=None, snap_end=False, portrait=None, **style):
    """Fetch, transcribe, pick a segment, render. Returns a result dict."""
    import bgm
    import edit
    import emphasis
    import fetch
    import language
    import metadata
    import segments as selector
    import transcribe

    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()

    swept = fetch.prune_cache()
    if swept:
        _log(f"swept {len(swept)} cached download(s) past their TTL")

    content = _fetch_one(content_url, "content")
    opening = _fetch_one(opening_url, "opening") if opening_url else None

    _log("transcribing (cached beside the video)...")
    # The context line doubles as the decoder's topic prompt: it carries the
    # speaker and place names Whisper's Indonesian model otherwise rewrites
    # into similar-sounding common words.
    words, info = transcribe.transcribe(content, topic_prompt=context or None)
    if not words:
        raise RuntimeError("no speech found in the content video")

    # The reviewer runs AFTER the segment is chosen, further down: reviewing the
    # whole video sends every word of a one-hour source when the clip uses about
    # sixty of them, and that is what kept timing out. Selection itself does not
    # need corrected spelling — it works on stress and topic, not orthography.
    review_status = {"ok": None, "reason": "disabled"}

    # Everything that degraded the clip without failing the job, collected as
    # it happens and returned in the result. Declared before segment selection
    # because that is the first stage allowed to fall back. Fail-soft is fine;
    # fail-silent is what shipped `sololah` burned into a caption, and what
    # shipped the opening greeting when the operator asked for Palestina.
    warnings = []

    # One ledger per render. Every gate records here so the end of the run can
    # say which division checked what — including gates that found nothing,
    # because a silent gate used to be indistinguishable from a gate that was
    # switched off. That is not hypothetical: `look = ""` disabled the act gate
    # for a whole release and the only sign was cutaways that felt wrong.
    import audit
    audit.start()

    lo, hi = selector.duration_window(platform)
    if start is not None:
        seg_start = float(start)
        seg_end = seg_start + float(seconds or hi)
        seg_end = min(seg_end, info["duration"])
        topic_hook = None
        if snap_end:
            # The operator picks --start by watching, then has to guess how
            # long the thought runs. Guessing 22s on a 6.5s sentence shipped a
            # clip that kept rolling into "tapi dua perempuan rekomendasi apa
            # itu?" and "jangan dorong" — the point ended, the clip did not.
            # Snap the tail to where speech actually stops instead.
            # A silence alone is not the right boundary. Opening earlier to
            # include build-up puts several silences before the actual point,
            # and the first of them cuts the clip BEFORE the line it exists
            # for. The context line names the subject, so the cut goes to the
            # first break after the subject is last mentioned.
            keys = [t for t in re.findall(r"\w+", (context or "").lower())
                    if len(t) > 3]
            snapped, why = selector.snap_to_speech_end(
                words, seg_start, seg_end,
                min_dur=float(os.environ.get("CLIPPER_SNAP_MIN", "9.0")),
                after_words=keys)
            if snapped is None:
                warnings.append(f"--end-at-sentence did nothing: {why}")
            else:
                _log(f"end snapped {seg_end:.1f}s -> {snapped:.1f}s ({why})")
                seg_end = snapped
                # Give the ending its own room AFTER the sentence.
                #
                # "nanti selesai dari si gibran suruh bawa kotak makan,
                # langsung jedag jedug" asks for two things at once: cut the
                # aside that follows the payoff, AND close with the freeze.
                # Snapping alone satisfies the first and starves the second —
                # the snap leaves 0.35s of breath, so a 3s ending has nowhere
                # to go and _outro_start silently falls back to "dur - span",
                # which is 20.55s, i.e. back on top of the payoff line.
                #
                # So the clip is extended past the sentence by the ending's own
                # span. The extra seconds carry no speech (that is exactly why
                # the snap cut there), so nothing is said under the freeze —
                # and the operator's "durasi videonya jg engga kependekan"
                # comes out of the same change.
                # The ending does NOT need extra source footage: the jamet
                # freeze is built with `loop`, which CLONES the frame at the
                # cut and fills the rest of the clip with copies, and the real
                # tail is then dropped by the encoder's -t. So the right length
                # here is the sentence itself — the freeze extends the output
                # on its own.
                #
                # Extending the segment by the ending's span instead pulled the
                # aside back in: 28.55s became 31.55s and "tapi dua perempuan
                # rekomisasi apa itu?" played again, this time UNDER the freeze.
                # Measured, not assumed — the first attempt at this shipped
                # that exact result.
                import edit as _e
                if _e._outro_kind(mood) == "jamet":
                    _log(f"jamet ending will extend {seg_end - seg_start:.1f}s "
                         f"by {_e.OUTRO_JAMET_SECONDS:.1f}s of frozen frame")
    else:
        _log("choosing a segment...")
        picks = selector.pick_topical_segments(words, platform, 1,
                                               video_duration=info["duration"],
                                               context=context)
        if not picks:
            # Same ladder the pipeline uses: an unreachable router costs the
            # topic-aware cut, not the clip. Without this a 9Router hiccup
            # takes the whole chat flow down.
            #
            # But it must be said out loud. The heatmap does not know what the
            # clip is about, so this silently shipped the opening greeting of a
            # speech when the operator asked for the part about Palestina — and
            # the only trace was one line on stderr.
            _log("topical selection unavailable — falling back to heatmap")
            warnings.append(
                "topic-aware cut unavailable (model unreachable) — segment "
                "chosen by watch-time heatmap, which ignores --context")
            heat = fetch.heatmap_for(content)
            picks = [{"start": s, "end": e, "hook": None}
                     for s, e in selector.pick_segments(
                         info["duration"], heat, words, platform, 1)]
        if not picks:
            raise RuntimeError(
                f"could not find a self-contained {lo}-{hi}s segment — pass "
                f"--start to choose one by hand")
        seg_start, seg_end = picks[0]["start"], picks[0]["end"]
        topic_hook = picks[0].get("hook")

    seg_words = selector.words_in(words, seg_start, seg_end)

    # Beam search cuts mishearings but does not end them — the remaining ones
    # are lexical, not acoustic (`sololah` for `seolah`, `darah` for `dakwah`).
    # The reviewer fixes those in place; word timings are required to survive
    # untouched, and language.review returns the transcript unchanged if they
    # would not.
    #
    # Scoped to the chosen segment on purpose. Reviewing the whole transcript
    # sent 522 words of a one-hour video to correct the 61 that reach the
    # screen, which timed out at both 120s and 300s; the segment alone comes
    # back in about 11s. The outcome travels out in `warnings`, because a clip
    # once shipped with `sololah` burned in and the only evidence was a line on
    # stderr.
    if LANG_REVIEW:
        audit.briefed("language", f"{len(seg_words)} word(s) of transcript",
                      "after segment selection",
                      "reviewing the whole video timed the router out once")
        seg_words = language.review(seg_words, context=context or "",
                                    status=review_status)
    if review_status.get("ok") is False:
        audit.rejected("language", "transcript review", "skipped",
                       str(review_status.get("reason", "?")))
        warnings.append("transcript review skipped: %s — captions are raw "
                        "Whisper output" % review_status.get("reason", "?"))
    elif LANG_REVIEW:
        # language.review puts the count in `reason` ("3 fixed", "no
        # mishearings found"), so there is no separate counter to invent.
        audit.passed("language", "transcript review",
                     str(review_status.get("reason") or "reviewed"))
    else:
        audit.warned("language", "transcript review", "disabled",
                     "CLIPPER_LANG_REVIEW is off")

    # Measure which words the speaker actually leaned on before captions are
    # drawn. Failure here scores every word 0.0 and the captions fall back to
    # the model's punchline pick, so a broken audio read never blocks a render.
    try:
        seg_words = emphasis.score_words(content, seg_words, seg_start, seg_end)
        stressed = emphasis.emphatic(seg_words)
        if stressed:
            _log(f"emphasis: {', '.join(sorted(stressed))}")
    except Exception as exc:
        _log(f"emphasis unavailable ({type(exc).__name__}: {exc})")
    seg_text = " ".join(w["word"] for w in seg_words)
    meta = metadata.generate(seg_text, {}, platform=platform, context=context,
                             style=copy_style)
    meta["hook"] = _hook_for(hook, opening, topic_hook, meta["hook"])

    # WHO DECIDES THE MUSIC, and the correction that overshot.
    #
    # First this read `mood or meta["mood"]`, so a preset default beat the
    # transcript and a grief clip got a jedag-jedug anthem. The fix made the
    # transcript win every clash — and overshot: `--clip-type jamet` is a
    # register the OPERATOR TYPED. Forcing a sad track under a preset whose
    # whole point is the beat is the same failure with the sign flipped
    # ("kenapa musik sedih? kan ini preset jedag jedug").
    #
    # So the ladder is by AUTHORSHIP, not by confidence:
    #   1. --mood                -> explicit, wins outright, no warning
    #   2. --clip-type           -> explicit register, wins, but a clash with
    #                               the transcript is WARNED so the operator
    #                               sees it and can pass --mood
    #   3. nothing               -> transcript decides
    # A guard whose job is to catch a register mismatch must SURFACE it, not
    # silently reverse a choice a human made. The operator asked for blockers
    # as explicit choices, and this is one.
    _mood = mood or meta.get("mood")
    if mood_from_preset and meta.get("mood") and meta["mood"] != mood:
        if bgm._clashes(mood, meta["mood"]):
            warnings.append(
                f"music mood: --clip-type asks for {mood!r} but the "
                f"transcript reads {meta['mood']!r}, which clash — kept "
                f"{mood!r} because the clip type was requested explicitly; "
                f"pass --mood {meta['mood']} to use the transcript's")
            audit.warned("sound", "mood clash",
                         f"preset {mood!r} vs transcript {meta['mood']!r}",
                         f"kept {mood!r} (explicit --clip-type)")
    track, why = bgm.pick(_mood, key=f"job:{int(seg_start)}")
    audit.briefed("sound", f"mood = {_mood!r}",
                  "operator override" if (mood and not mood_from_preset)
                  else "read from transcript",
                  f"{len(bgm.load_tracks())} track(s) on this box")
    if track:
        audit.passed("sound", track.get("file", "?"),
                     f"mood {track.get('mood') or meta.get('mood')}", why)
    else:
        # No music is a deliberate outcome, not a failure: a triumphal anthem
        # under a clip about people being killed is worse than silence.
        audit.warned("sound", "no music", "no track matched the mood", why)
    _log(f"bgm: {why}")
    # A clip shipping without music is a product decision, not a detail: it
    # happens when the stock would actively fight the clip. Say so in the
    # result rather than leaving the operator to notice the silence.
    if track is None:
        warnings.append(f"no background music: {why}")
    elif "no " in why and "using" in why:
        warnings.append(f"background music substituted: {why}")

    # Cutaways: find footage on the same subject, cut it to length, and hand it
    # over for the render. Every stage is allowed to come back empty — a clip
    # with no b-roll is the current product, so nothing here may block a render.
    inserts = _gather_inserts(seg_words, seg_start, seg_end - seg_start,
                              context, content,
                              warnings=warnings) if BROLL_INSERT else []
    if inserts:
        audit.passed("edit", "cutaways placed", f"{len(inserts)}",
                     ", ".join(i["term"] for i in inserts))
        _log("b-roll: %s" % ", ".join(
            "%s @%.0fs" % (i["term"], i["start"]) for i in inserts))
    elif BROLL_INSERT:
        # Silence here is how v22 shipped with no cutaways and a clean
        # warnings list. If nothing even got as far as being rejected, say so.
        audit.warned("edit", "cutaways placed", "0",
                     "no footage passed the gates")
        if not any(w.startswith("b-roll:") for w in warnings):
            warnings.append("b-roll: no cutaways were placed")

    # The ending is this division's other output, and it was invisible. The
    # jamet render printed "edit DID NOT RUN" while the graph really did carry
    # loop=loop=15:size=1:start=570 and the delivered file really did freeze
    # (0.007) and shake (11.4) — the ledger was wrong, not the render. A gate
    # that reports nothing is indistinguishable from a gate that was skipped,
    # which is the whole reason DID NOT RUN exists; so say which ending was
    # applied, and say it even when the answer is "none".
    import edit as _edit
    _kind = _edit._outro_kind(mood or meta.get("mood"))
    _span = (_edit.OUTRO_JAMET_SECONDS if _kind == "jamet"
             else _edit.OUTRO_SECONDS)
    audit.briefed("edit", f"outro = {_kind!r}",
                  f"clip {seg_end - seg_start:.1f}s",
                  f"needs {_span * 3:.0f}s for a {_span:.0f}s ending")
    if _kind == "none":
        audit.passed("edit", "outro", "none", "no closing treatment asked for")
    elif (seg_end - seg_start) < _span * 3:
        # Not a failure, but it must never be silent again: this is exactly how
        # the 22s viral cut shipped with no freeze and no shake at all.
        audit.warned("edit", "outro", _kind,
                     f"clip too short — {_span * 3:.0f}s needed")
        warnings.append(
            f"outro {_kind}: clip is {seg_end - seg_start:.1f}s, needs "
            f"{_span * 3:.0f}s — no closing treatment applied")
    else:
        audit.passed("edit", "outro", _kind, f"last {_span:.0f}s")

    out = out or os.path.join(
        OUT_DIR, f"clip_{int(time.time())}_{int(seg_start)}.mp4")

    # WHICH frame gets frozen is decided by what is in it, not by where the
    # clip stops. The jamet ending freezes at the end of the clip's own speech
    # — correct, and what the operator asked for — but `loop` clones whatever
    # frame sits there. Moving the stop point to the end of a sentence moved
    # the still onto a bystander and shipped a five second portrait of a woman
    # nobody can name.
    #
    # A veto has no fallback, so a failed pick is a WARNING plus the mechanical
    # frame, never a silently wrong still.
    # A portrait held at the end is a FACTUAL CLAIM about whose story this is,
    # the same class of error as the flag emoji on the Palestine clip. A wrong
    # face there is worse than no portrait, so a missing or unreadable file is a
    # warning and the ending runs without it rather than shipping a stranger.
    if portrait:
        portrait = os.path.abspath(os.path.expanduser(portrait))
        if not os.path.exists(portrait):
            warnings.append(
                f"portrait: {portrait} does not exist — the ending ran without "
                "it")
            portrait = None
        elif _kind != "jamet":
            warnings.append(
                "portrait: only the jamet ending has a tail to hold it — "
                f"this clip is '{_kind}', so it was ignored")
            portrait = None
    freeze_at = None
    freeze_still = None
    if _kind == "jamet":
        # The still is a PORTRAIT, so the gate needs a PERSON, not the clip
        # topic. _footage_subject answers "where was this shot", which is the
        # wrong question for "who is frozen on screen" — asked that way a
        # bystander in the right place passes. The first proper noun shared by
        # the context and the transcript is the person the clip is about.
        import broll
        _names = broll.repeated_names(
            context or "", " ".join(str(w.get("word") or "")
                                    for w in seg_words))
        _names = _names or broll.proper_nouns(context or "")
        _subject = _names[0] if _names else ""
        _freeze_abs = edit._outro_start(
            seg_end - seg_start, mood=(track or {}).get("mood")
            or meta.get("mood"), words=seg_words, clip_start=seg_start)
        if _subject and _freeze_abs is not None:
            audit.briefed("freeze", "subject", _subject)
            import freeze_pick
            _picked = freeze_pick.pick(
                content, seg_start + _freeze_abs, _subject,
                audit=lambda k, m: audit.record("freeze", k, "info", m),
                clip_end=seg_end)
            if _picked is None:
                warnings.append(
                    "freeze frame: no frame in the last "
                    f"{freeze_pick.LOOKBACK:.0f}s clearly shows the subject — "
                    "kept the mechanical frame, the still may show a bystander")
                audit.rejected("freeze", "pick", "no qualifying frame")
            else:
                freeze_at = max(0.0, _picked - seg_start)
                # Hand the renderer the COMPOSED still, not a timestamp. The
                # gate judged the 1080x1920 composition; passing a timestamp
                # would let the renderer compose it again with a pan offset and
                # deliver different pixels — exactly how source 149.2s became a
                # bystander on screen. Same still, same bytes, both places.
                freeze_still = os.path.join(
                    os.path.dirname(out),
                    os.path.basename(out).replace(".mp4", ".freeze.png"))
                if not freeze_pick.render_still(content, _picked,
                                                freeze_still):
                    freeze_still = None
                    warnings.append(
                        "freeze frame: the chosen still could not be rendered "
                        "— kept the mechanical frame")
                audit.passed("freeze", "pick",
                             f"source {_picked:.2f}s",
                             f"clip {freeze_at:.2f}s")
                _log(f"freeze frame picked at {_picked:.2f}s")
        else:
            warnings.append(
                "freeze frame: no subject to check against — the frozen frame "
                "was not verified")

    _log(f"rendering {seg_end - seg_start:.0f}s...")
    edit.render_clip(content, seg_start, seg_end, seg_words, out,
                     hook=meta["hook"], bgm=track["path"] if track else False,
                     accent_words=meta.get("punchline_words") or (),
                     intro=opening, intro_start=opening_start or 0.0,
                     inserts=inserts, freeze_at=freeze_at,
                     freeze_still=freeze_still,
                     portrait=portrait,
                     mood=(track or {}).get("mood") or meta.get("mood"),
                     **style)

    small = _delivery_copy(out, max_mb)

    # The edit gate used to pass on the strength of its own settings: "outro =
    # 'jamet', last 3s". It said PASS on a render whose last 3s was moving
    # video, because `loop` INSERTS its frozen frames and the real tail ran on
    # after them. The operator found it, not the gate: "harusnya videonya pause
    # sampe akhir".
    #
    # So the gate now measures the DELIVERED FILE. A frozen frame has
    # essentially no frame-to-frame difference; a shaking frozen frame has a
    # sharp spike on each beat that decays to near zero before the next one.
    # Moving video never returns to zero. Checking the floor inside the closing
    # stretch separates the two without being fooled by the shake.
    if _kind == "jamet" and (seg_end - seg_start) >= _span * 3:
        _still = _freeze_floor(out, max(0.0, (seg_end - seg_start) - _span))
        audit.briefed("edit", "freeze holds to the end",
                      f"last {_span:.0f}s of {os.path.basename(out)}",
                      "a still reads ~0 between beats; video never does")
        if _still is None:
            audit.warned("edit", "freeze", "not measured",
                         "ffmpeg motion probe failed")
            warnings.append("outro jamet: could not verify the freeze")
        elif _still > 1.5:
            audit.rejected("edit", "freeze", f"floor {_still:.2f}",
                           "the picture is still moving inside the ending")
            warnings.append(
                f"outro jamet: motion floor {_still:.2f} in the last "
                f"{_span:.0f}s — the freeze is not holding")
        else:
            audit.passed("edit", "freeze", f"floor {_still:.2f}",
                         f"frozen through the last {_span:.0f}s")

    result = {
        "ok": True,
        "file": os.path.abspath(out),
        "size_bytes": os.path.getsize(out),
        # Present only when the render was over --max-mb. Send this one; the
        # file above is the one that goes to a platform.
        "delivery_file": os.path.abspath(small) if small else None,
        "delivery_size_bytes": os.path.getsize(small) if small else None,
        "segment": [round(seg_start, 2), round(seg_end, 2)],
        "duration_sec": round(seg_end - seg_start, 2),
        "opening": bool(opening),
        "hook": meta["hook"],
        "title": meta["title"],
        "description": meta["description"],
        "mood": meta.get("mood"),
        "music": track["file"] if track else None,
        "attribution": (track or {}).get("attribution") or None,
        # Anything that degraded the clip without failing the job. An empty
        # list means every stage did its work; a non-empty one is the honest
        # answer to "why does the caption say sololah".
        "warnings": warnings,
        "elapsed_sec": round(time.time() - t0, 1),
    }

    # Printed after the JSON result is assembled but before returning, so the
    # review is the last thing on stderr and lines up with the clip just made.
    # The checker list is explicit: a gate named here that recorded nothing
    # prints DID NOT RUN instead of vanishing.
    led = audit.current()
    if led is not None:
        checkers = ("sourcing", "footage", "copy",
                    "language", "sound", "edit")
        led.emit(checkers=checkers)
        # Also write it down. Printing was the only output, so the review
        # existed solely in whoever's terminal ran the render — the operator
        # pointed a Discord channel at these logs and saw nothing, because
        # nothing had ever been saved for anything to deliver.
        try:
            out = result.get("file") or ""
            if out:
                path = os.path.splitext(out)[0] + ".audit.json"
                led.save(path, checkers=checkers, meta={
                    "file": out,
                    "title": result.get("title", ""),
                    "mood": result.get("mood", ""),
                    "music": result.get("music", ""),
                    "duration_sec": result.get("duration_sec", 0),
                    "warnings": result.get("warnings", []),
                })
                result["audit_file"] = path
        except Exception as exc:
            # A ledger that cannot be written must not lose the clip that was
            # already rendered and paid for.
            warnings.append(f"audit: ledger not saved — {exc}")
    audit.stop()
    return result


def _selftest():
    """Offline checks on the parts that are a contract, not an implementation."""
    # The hook rule the catalogue promises.
    assert _hook_for("Ditulis Tangan", None, "topical", "model") == "Ditulis Tangan"
    assert _hook_for("Ditulis Tangan", "/broll.mp4", "topical", "model") == "Ditulis Tangan"
    assert _hook_for(None, "/broll.mp4", "topical", "model") == "topical"
    assert _hook_for(None, "/broll.mp4", None, "model") == "model"
    # No opening and no text asked for: no hook, whatever the model wrote.
    assert _hook_for(None, None, "topical", "model") is None
    assert _hook_for(None, None, None, "model") is None
    assert _hook_for("", None, None, "model") is None

    # The catalogue is what an agent offers a user, so every id it advertises
    # has to be one the parser actually accepts.
    cat = catalogue()
    parser_choices = {
        "frame_mode": ("cover", "fill", "fit"),
        "caption_style": ("phrase", "karaoke", "editorial"),
        "hook_style": ("boxes", "card"),
    }
    for key, allowed in parser_choices.items():
        ids = [o["id"] for o in cat[key]]
        assert set(ids) <= set(allowed), (key, ids, allowed)
    for key, value in cat["defaults"].items():
        if key in parser_choices:
            assert value in parser_choices[key], (key, value)

    # A delivery copy is only made when one is needed.
    assert _delivery_copy("/nonexistent.mp4", 0) is None

    print(json.dumps({"ok": True, "checked": "hook rule, catalogue, delivery cap"}))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="job.py", description=__doc__)
    p.add_argument("--selftest", action="store_true",
                   help="check the contract without touching the network")
    p.add_argument("--list", action="store_true",
                   help="print the catalogue of styles and music, then exit")
    p.add_argument("--content", help="link to the video the clip is cut from")
    p.add_argument("--opening", help="link to the b-roll shown first (optional)")
    p.add_argument("--portrait",
                   help="still image (local path) held at the very END of a "
                        "jamet ending, after the footage freeze and before the "
                        "dip to black. Part of the outro, not a separate clip.")
    p.add_argument("--opening-start", type=float, default=0.0,
                   help="second in the opening video where the hook footage "
                        "begins. The default of 0 takes the file's first "
                        "frames, which on a long reel is rarely the scene "
                        "asked for")
    p.add_argument("--hook", help="hook text; **bold** with double asterisks. "
                                  "Without this and without --opening the clip "
                                  "gets no hook at all")
    p.add_argument("--platform", default="youtube",
                   help="destination, sets the length window")
    p.add_argument("--start", type=float, help="cut from here instead of letting "
                                               "the model choose")
    p.add_argument("--seconds", type=float, help="clip length when --start is given")
    p.add_argument("--end-at-sentence", action="store_true",
                   dest="end_at_sentence",
                   help="with --start: pull the end back to where speech stops "
                        "instead of using the full --seconds, so the clip does "
                        "not roll past the point being made")
    p.add_argument("--mood", help="override the music mood")
    p.add_argument("--context", help="what the clip is about: who is speaking, "
                                     "where, and why the moment matters. Steers "
                                     "which segment is cut and how the hook and "
                                     "title are written")
    p.add_argument("--out", help="output path")
    p.add_argument("--copy-style", dest="copy_style",
                   choices=("pr-politik",),
                   help="tone for the hook, title and description. Omit for "
                        "the neutral viral tone")
    p.add_argument("--frame-mode", dest="frame_mode",
                   choices=("cover", "fill", "fit", "pillar"))
    p.add_argument("--caption-style", dest="caption_style",
                   choices=("phrase", "karaoke", "editorial"))
    p.add_argument("--hook-style", dest="hook_style", choices=("boxes", "card"))
    p.add_argument("--broll", dest="broll", action="store_true", default=None,
                   help="cut away to b-roll found on YouTube at phrases that "
                        "name a person or place. Adds a download per insert")
    p.add_argument("--flash", dest="flash", action="store_true", default=None,
                   help="brief white pop on the strongest beats")
    p.add_argument("--clip-type", dest="clip_type",
                   choices=tuple(CLIP_TYPES),
                   help="the kind of clip to cut. 'sedih' is the sombre cut "
                        "developed first: news b-roll, melancholy outro that "
                        "desaturates and dips to black. 'jamet' is the viral "
                        "cut: the speaker's own sentence only, no news b-roll, "
                        "freeze on his face and shake it to the beat. Each one "
                        "sets mood, outro and b-roll together — see CLIP_TYPES")
    p.add_argument("--wait", type=float, default=None,
                   help="seconds to wait if another job holds the host")
    p.add_argument("--max-mb", dest="max_mb", type=float, default=0,
                   help="also write a smaller copy when the render exceeds "
                        "this, for a chat transport with an upload limit "
                        "(Discord: 10 free, 50 Nitro Basic)")
    a = p.parse_args(argv)

    if a.selftest:
        return _selftest()
    if a.list:
        print(json.dumps(catalogue(), indent=2, ensure_ascii=False))
        return 0
    if not a.content:
        print(json.dumps({"ok": False,
                          "error": "--content is required (or use --list)"}))
        return 2

    style = {k: v for k, v in
             (("frame_mode", a.frame_mode), ("caption_style", a.caption_style),
              ("hook_style", a.hook_style)) if v}
    # --clip-type picks mood, outro and b-roll as a set. An explicit flag still
    # wins over the preset, so --clip-type jamet --mood emotional is possible;
    # the preset is a default, not a cage.
    preset = CLIP_TYPES.get(a.clip_type or "", {})
    mood_from_preset = False
    if preset:
        # edit.OUTRO is read at import time, so setting the environment here is
        # only reliable while edit is still unimported. Set the module constant
        # directly instead — it works either way, and an env var the operator
        # set by hand still wins because that is what edit read first.
        import edit as _edit
        if os.environ.get("CLIPPER_OUTRO") in (None, "", "auto"):
            _edit.OUTRO = preset["outro"]
        if a.mood is None:
            # The preset's mood is a DEFAULT, not an operator override. Filling
            # a.mood here used to make it indistinguishable from `--mood hype`
            # typed by hand, and `mood or meta["mood"]` downstream then let
            # "jamet" beat a transcript that read `emotional` — so a clip of
            # Gibran apologising to a poisoned child's mother shipped with a
            # jedag-jedug anthem under it. bgm._CLASH already forbids
            # emotional x hype; it was never consulted because the clashing
            # mood arrived as a user override.
            a.mood = preset["mood"]
            mood_from_preset = True
        if a.broll is None:
            a.broll = preset["broll"]
        if a.flash is None:
            a.flash = preset["flash"]

    # Both are read at import time by the modules that own them, so a CLI flag
    # has to set the environment before those reads matter. Set here rather than
    # threaded through run(): edit.py reads its own module constants.
    if a.broll:
        global BROLL_INSERT
        BROLL_INSERT = True
    if a.flash:
        import edit as _edit
        _edit.FLASH = True
    try:
        with _Lock(wait=a.wait if a.wait is not None else LOCK_WAIT):
            res = run(a.content, a.opening, opening_start=a.opening_start,
                      hook=a.hook, platform=a.platform,
                      start=a.start, seconds=a.seconds, mood=a.mood,
                      mood_from_preset=mood_from_preset, out=a.out,
                      snap_end=a.end_at_sentence,
                      max_mb=a.max_mb, context=a.context,
                      copy_style=a.copy_style, portrait=a.portrait, **style)
    except Busy as e:
        # not a failure of this job, so it gets no report and its own code —
        # the caller should retry rather than escalate
        print(json.dumps({"ok": False, "busy": True, "error": str(e)},
                         ensure_ascii=False))
        return 3
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        import report
        filed = report.capture(e, "job", context={
            "content": a.content, "opening": a.opening, "platform": a.platform,
            "start": a.start, "seconds": a.seconds, "clip_context": a.context,
            **style})
        out = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        out.update(filed)
        print(json.dumps(out, ensure_ascii=False))
        return 1
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
