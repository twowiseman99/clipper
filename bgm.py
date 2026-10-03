"""BGM selection — match a curated track to the mood of a clip (PRD §3.6).

The model never picks a file: it cannot hear the music, and a hallucinated
filename would be unrenderable. It labels the CLIP with a mood (which it can do
from the transcript), and the mood is resolved to a track here, against a
manifest you write once. Adding or retiring a track never touches the prompt.

Selection is deterministic: the same clip re-rendered after a retry gets the
same track (PRD §5 idempotency), which random.choice could not promise.

Drop the files in background_music/ and describe them in
background_music/tracks.json:

    {"tracks": [
      {"file": "01.mp3", "mood": ["hype", "funny"],
       "attribution": "Music: Sunny Day by X (CC BY 4.0)"},
      {"file": "02.mp3", "mood": ["emotional"]}
    ]}

Without a manifest, moods are read from filenames like `03_tense_slowbuild.mp3`
so a folder can be dropped in and still route sensibly.
"""
import hashlib
import json
import os
import re

_BASE = os.path.dirname(os.path.abspath(__file__))
BGM_DIR = os.environ.get("CLIPPER_BGM_DIR",
                         os.path.join(os.path.dirname(_BASE), "background_music"))
MANIFEST = "tracks.json"
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".ogg")

# Mood vocabulary. Kept small on purpose: the model has to choose reliably, and
# ten tracks cannot meaningfully fill more buckets than this.
MOODS = ("hype", "emotional", "tense", "funny", "chill", "inspiring", "mysterious")
DEFAULT_MOOD = "chill"


def _from_filename(name):
    """Moods embedded in a filename: `03_tense_slowbuild.mp3` -> ['tense'].

    Deduplicated, because a mood word can appear twice: bgm_add.py prefixes the
    bucket and the uploader's own title often already contains it, giving
    `emotional_emotional_background_lights.mp3` and a track listed twice.
    """
    parts = re.split(r"[^a-z]+", os.path.splitext(name)[0].lower())
    seen = []
    for p in parts:
        if p in MOODS and p not in seen:
            seen.append(p)
    return seen


def load_tracks(dirpath=None):
    """Return [{path, file, mood[], attribution}] for every playable track.

    A manifest entry naming a file that is not on disk is skipped rather than
    raising: a half-synced asset folder should cost one track, not the run.
    """
    dirpath = dirpath or BGM_DIR
    try:
        names = sorted(f for f in os.listdir(dirpath) if f.lower().endswith(AUDIO_EXT))
    except OSError:
        return []

    described = {}
    mpath = os.path.join(dirpath, MANIFEST)
    if os.path.exists(mpath):
        try:
            with open(mpath, encoding="utf-8") as f:
                for t in (json.load(f) or {}).get("tracks") or []:
                    if t.get("file"):
                        described[t["file"]] = t
        except (ValueError, OSError):
            pass  # a broken manifest degrades to filename routing

    out = []
    for name in names:
        entry = described.get(name, {})
        moods = [m for m in (entry.get("mood") or []) if m in MOODS] or _from_filename(name)
        out.append({
            "path": os.path.join(dirpath, name),
            "file": name,
            "mood": moods,
            "attribution": str(entry.get("attribution") or "").strip(),
        })
    return out


def _stable_index(key, n):
    """Deterministic 0..n-1 from a clip key — same clip, same track."""
    digest = hashlib.sha1(str(key).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % n


# Which moods can stand in for each other. A missing bucket used to fall back
# to *any* track, which is how a clip about people being bombed got a stadium
# anthem under it: musically the opposite of what the words are doing, and more
# jarring than having no music at all.
#
# Substitutes are quieter neighbours only. The lists are deliberately not
# symmetric — a chill clip can borrow an emotional track, but an emotional clip
# must never borrow hype.
_NEAR = {
    "emotional": ("mysterious", "chill"),
    "tense": ("mysterious", "emotional"),
    "mysterious": ("tense", "emotional"),
    "chill": ("emotional", "mysterious"),
    "inspiring": ("chill",),
    "hype": ("inspiring", "tense"),
    "funny": ("chill",),
}
# Pairs that must never substitute for each other regardless of what is in
# stock. Checked after _NEAR so a config mistake cannot reintroduce the clash.
_CLASH = {
    frozenset(("emotional", "hype")),
    frozenset(("emotional", "funny")),
    frozenset(("emotional", "inspiring")),
    frozenset(("tense", "funny")),
    frozenset(("mysterious", "funny")),
    # A triumphal anthem is wrong under a joke and wrong under suspense: it
    # tells the viewer to feel victorious while the clip is doing something
    # else. hype -> inspiring stays allowed, because those genuinely rhyme.
    frozenset(("funny", "inspiring")),
    frozenset(("tense", "inspiring")),
}


def _clashes(mood, other):
    return frozenset((mood, other)) in _CLASH


def pick(mood, key="", exclude=(), dirpath=None):
    """Choose a track for a clip. Returns (track_or_None, reason).

    mood: label from metadata.generate. An unstocked mood falls back to a
    quieter neighbouring mood (see _NEAR) and otherwise to no music at all:
    silence under a clip about a massacre is a defensible result, a triumphal
    anthem is not. The caller surfaces the reason so a thin BGM folder is
    visible rather than silently papered over.
    exclude: paths already used by sibling clips, avoided when alternatives
    exist so one task's clips do not all share a track.
    """
    tracks = load_tracks(dirpath)
    if not tracks:
        return None, "no tracks in the BGM folder"

    mood = (mood or "").strip().lower()
    matching = [t for t in tracks if mood in t["mood"]] if mood in MOODS else []
    note = ""
    if not matching and mood in MOODS:
        # Try the neighbours, nearest first.
        for alt in _NEAR.get(mood, ()):
            if _clashes(mood, alt):
                continue
            matching = [t for t in tracks if alt in t["mood"]]
            if matching:
                note = f"no {mood!r} track, using {alt!r}"
                break
    if not matching:
        # Anything left that does not actively fight the clip.
        safe = [t for t in tracks
                if not any(_clashes(mood, m) for m in t["mood"])]
        if safe and mood in MOODS:
            matching = safe
            note = f"no {mood!r} or near-mood track"
        elif mood not in MOODS:
            matching = tracks
            note = (f"unknown mood {mood!r}" if mood else "no mood given")
        else:
            # Every track in stock clashes with this clip. No music.
            have = sorted({m for t in tracks for m in t["mood"]})
            return None, (f"no track suitable for {mood!r} — stock is "
                          f"{', '.join(have)}; add one with "
                          f"`bgm_add.py --mood {mood} <url>`")

    fresh = [t for t in matching if t["path"] not in set(exclude)]
    if fresh:
        matching = fresh
    else:
        note = (note + "; " if note else "") + "all candidates already used"

    chosen = matching[_stable_index(key, len(matching))]
    why = f"mood {mood or '-'}" + (f" ({note})" if note else "")
    return chosen, f"{why} -> {chosen['file']}"


if __name__ == "__main__":
    import tempfile

    d = tempfile.mkdtemp()
    for n in ("01.mp3", "02.mp3", "03_tense_slowbuild.mp3", "notes.txt"):
        open(os.path.join(d, n), "w").close()
    with open(os.path.join(d, MANIFEST), "w", encoding="utf-8") as f:
        json.dump({"tracks": [
            {"file": "01.mp3", "mood": ["hype", "funny"], "attribution": "Music: A by X"},
            {"file": "02.mp3", "mood": ["hype"]},
            {"file": "missing.mp3", "mood": ["chill"]},
        ]}, f)

    tracks = load_tracks(d)
    assert [t["file"] for t in tracks] == ["01.mp3", "02.mp3", "03_tense_slowbuild.mp3"]
    assert tracks[0]["mood"] == ["hype", "funny"] and tracks[0]["attribution"] == "Music: A by X"
    assert tracks[2]["mood"] == ["tense"], tracks[2]     # routed by filename
    assert all(t["file"] != "notes.txt" for t in tracks)  # non-audio ignored

    t, why = pick("tense", key="vidA:100", dirpath=d)
    assert t["file"] == "03_tense_slowbuild.mp3", why

    # deterministic: same clip -> same track, across calls
    a, _ = pick("hype", key="vidA:100", dirpath=d)
    b, _ = pick("hype", key="vidA:100", dirpath=d)
    assert a["file"] == b["file"], (a, b)
    # ...but different clips spread across the bucket
    picks = {pick("hype", key=f"vidA:{i}", dirpath=d)[0]["file"] for i in range(30)}
    assert picks == {"01.mp3", "02.mp3"}, picks

    # sibling clip's track is avoided when an alternative exists
    first, _ = pick("hype", key="vidA:100", dirpath=d)
    second, _ = pick("hype", key="vidA:100", exclude=[first["path"]], dirpath=d)
    assert second["file"] != first["file"], (first, second)

    # An unstocked mood borrows a neighbouring one and says so.
    t, why = pick("mysterious", key="k", dirpath=d)
    assert t and "no 'mysterious' track, using" in why, why
    # An unknown mood is a config typo, not a clash: still return something.
    t, why = pick("banana", key="k", dirpath=d)
    assert t and "unknown mood" in why, why
    t, why = pick("", key="k", dirpath=d)
    assert t and "no mood given" in why, why

    # A clip about grief must never borrow hype or comedy music. With only
    # those in stock the answer is no music, and the reason names the fix —
    # one shipped with a stadium anthem under an apology for a massacre.
    clash_dir = tempfile.mkdtemp()
    for name in ("01_hype_drums.mp3", "02_funny_kazoo.mp3"):
        open(os.path.join(clash_dir, name), "wb").close()
    t, why = pick("emotional", key="k", dirpath=clash_dir)
    assert t is None, (t, why)
    assert "bgm_add.py --mood emotional" in why, why

    # Every declared substitute must be a real mood and must not be a pair the
    # clash table forbids, or the two tables disagree silently.
    for mood, alts in _NEAR.items():
        assert mood in MOODS, mood
        for alt in alts:
            assert alt in MOODS, (mood, alt)
            assert not _clashes(mood, alt), f"{mood} lists clashing {alt}"

    # empty folder is not an error, it just means no BGM
    assert pick("hype", dirpath=tempfile.mkdtemp()) == (None, "no tracks in the BGM folder")
    print("bgm.py self-check OK")
