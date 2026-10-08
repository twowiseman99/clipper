"""Turn a render's ledger into a message a person wants to read.

audit.py prints a fixed-width report built for a terminal: six columns, the
checker's internal name, English reasons written at the call site. Pasted into
Discord inside a code fence it arrives as a wall the operator has to decode,
which is how a ledger stops being read.

This module is presentation only. It adds no verdict and no number: every line
traces to an entry audit.py recorded. What it does change is who the text is
addressed to — division labels become the thing that was checked, the brief
becomes a sentence saying what we handed the agent, and the English fragments
written at the call sites get an Indonesian equivalent where one is known.

The phrase table is deliberately a lookup with a passthrough fallback. A
machine-translated reason would read fluently and could say something the gate
never decided, which is the one failure a ledger cannot afford. Anything not in
the table ships as written.
"""

import re

import audit

# What each gate is actually about, in the operator's words. The checker names
# ("sourcing", "footage", "edit") are internal; nobody outside this repo knows
# that "footage" means per-frame rather than per-video.
SECTIONS = {
    "sourcing": "Sumber b-roll",
    "footage": "Frame b-roll",
    "copy": "Hook & judul",
    "language": "Transkrip",
    "sound": "Musik",
    "edit": "Editing",
}

# Order the reader cares about: what was said, how it was written, how it
# sounds, how it was cut, then the b-roll gates that reject most often.
ORDER = ["language", "copy", "sound", "edit", "sourcing", "footage"]

MARK = {audit.PASS: "✅", audit.REJECT: "❌", audit.WARN: "⚠️"}

# Fragments written at the call sites, with the Indonesian the operator would
# use. Matched whole-string first, then as a substring, so a reason carrying a
# number ("floor 0.39") still gets its words translated.
PHRASES = {
    "no mishearings found": "ga ada salah dengar",
    "b-roll: no cutaways were placed": "b-roll: ga ada cutaway yang kepasang",
    "no cutaways were placed": "ga ada cutaway yang kepasang",
    "transcript review": "review transkrip",
    "after segment selection": "sesudah segmen dipilih",
    "reviewing the whole video timed the router out once":
        "pernah timeout waktu review video penuh",
    "marketing filler": "filler marketing",
    "risky words": "kata berisiko",
    "none found": "ga ketemu",
    "none": "ga ada",
    "operator override": "dipaksa operator",
    "no footage passed the gates": "ga ada footage yang lolos pagar",
    "cutaways placed": "cutaway kepasang",
    "no footage of the act": "ga ada footage kejadiannya",
    "off topic": "beda topik",
    "not the action": "bukan kejadiannya",
    "verified channel": "channel terverifikasi",
    "freeze holds to the end": "beku nahan sampai habis",
    "frozen through the last 5s": "beku terus sampai 5s terakhir",
    "a still reads ~0 between beats; video never does":
        "gambar diam bacanya ~0 antar beat, video ga pernah",
    "last 5s": "5s terakhir",
    "last 8s": "8s terakhir",
    "outro": "outro",
    "freeze": "beku",
    "track(s) on this box": "lagu di box ini",
    "word(s) of transcript": "kata transkrip",
    "needs": "butuh",
    "for a": "buat",
    "ending": "ending",
    "clip": "klip",
    "mood": "mood",
    "style": "gaya",
    "subject": "subjek",
    "chars": "huruf",
    "hook": "hook",
    "title": "judul",
}

_SORTED = sorted(PHRASES, key=len, reverse=True)

# Warnings carry a measurement, so they cannot be table lookups: "motion floor
# 3.05 in the last 5s" is a different string every render. These rewrite the
# sentence around the number while leaving the number alone.
WARN_PATTERNS = [
    (re.compile(r"outro jamet: motion floor ([\d.]+) in the last (\d+)s"
                r".*freeze is not holding", re.I),
     r"outro jamet: gerakan masih \1 di \2s terakhir, bekunya ga nahan"),
    (re.compile(r"outro jamet: clip is ([\d.]+)s, needs ([\d.]+)s"
                r".*no closing treatment", re.I),
     r"outro jamet: klip cuma \1s, butuh \2s, jadi ga ada ending"),
]


def id_warning(text):
    """A warning, in Indonesian, with its measurement untouched."""
    for rx, repl in WARN_PATTERNS:
        if rx.search(text):
            return _num(rx.sub(repl, text))
    return _num(id_text(text))

# Filenames, ids and timestamps are not prose. "clip_1791434587_122.mp4" came
# out as "klip_1791434587_122.mp4" because the word "clip" is in the phrase
# table: a translator rewrote a path, which makes the ledger point at a file
# that does not exist. These are masked out before translation and restored
# after.
_LITERAL = re.compile(
    r"[\w./-]+\.(?:mp4|mp3|m4a|json|txt|png|jpg|webm)\b"   # files
    r"|\b[A-Za-z0-9_-]{8,}\s*@\s*\d+s"                      # youtube id @ 95s
)


def _protect(text):
    """Replace literals with placeholders, returning (masked, originals)."""
    found = []

    def swap(m):
        found.append(m.group(0))
        return "\x00%d\x00" % (len(found) - 1)

    return _LITERAL.sub(swap, text), found


def id_text(text):
    """Indonesian for the known fragments, the original for everything else."""
    if not text:
        return ""
    if text in PHRASES:
        return PHRASES[text]
    out, literals = _protect(text)
    for src in _SORTED:
        if src in out:
            out = out.replace(src, PHRASES[src])
    # Residual English connectives that only appear inside a reason built at a
    # call site, e.g. "last 5s of clip_x.mp4".
    out = re.sub(r"\s+of\s+", " dari ", out)
    # A mood arrives as the raw Python repr the gate carried: mood ['hype'].
    out = re.sub(r"\[\s*'([^']*)'\s*\]", r"\1", out)
    for i, lit in enumerate(literals):
        out = out.replace("\x00%d\x00" % i, lit)
    return out


def _trim_detail(target, reason, detail):
    """Drop a detail that only restates the target or the reason.

    The call sites were written for a terminal where repetition is cheap. The
    music gate passes target "a.mp3", reason "mood ['hype']" and detail
    "mood hype -> a.mp3", which in a chat message says the same thing three
    times and buries the one fact that matters.
    """
    if not detail:
        return ""
    if target and target in detail:
        return ""
    if reason and reason in detail:
        return ""
    return detail


def _num(value):
    """Indonesian decimal comma, applied only to a bare number."""
    return re.sub(r"(\d)\.(\d)", r"\1,\2", str(value))


def line(entry):
    """One verdict as a sentence: what was checked, then why."""
    target = _num(id_text(entry["target"]))
    detail = _trim_detail(entry["target"], entry["reason"], entry["detail"])
    # Reason and detail are two separate things the call site said. Joined with
    # a space they fuse into one bogus clause: "0 ga ada footage yang lolos"
    # reads as a quantity, when the gate said "0" and, separately, why.
    why = ", ".join(x for x in (id_text(entry["reason"]),
                                id_text(detail)) if x).strip()
    mark = MARK.get(entry["verdict"], "·")
    if not why:
        return f"{mark} {target}"
    return f"{mark} {target} — {_num(why)}"


def brief_line(entry):
    """The brief as a sentence saying what the agent was handed."""
    detail = _trim_detail(entry["target"], entry["reason"], entry["detail"])
    parts = [id_text(entry["target"])]
    parts += [id_text(x) for x in (entry["reason"], detail) if x]
    return "↳ dikasih: " + _num(", ".join(p for p in parts if p))


def headline(data):
    totals = data.get("totals", {})
    ok = totals.get("pass", 0)
    no = totals.get("reject", 0)
    warn = totals.get("warn", 0)
    if no:
        verdict = f"{no} ditolak"
    elif warn:
        verdict = f"lolos, {warn} catatan"
    else:
        verdict = "lolos semua"
    checks = ok + no + warn
    facts = [f"{checks} cek · {verdict}"]
    if data.get("duration_sec"):
        facts.insert(0, f"{data['duration_sec']:.0f} detik")
    if data.get("mood"):
        facts.insert(-1, f"mood {data['mood']}")
    return facts


def format_ledger(data, checkers=()):
    """The whole message. Sections in reading order, briefs above verdicts."""
    entries = data.get("entries", [])
    title = data.get("title") or (data.get("clip", "").rsplit("/", 1)[-1])
    out = [f"🎬 **{title}**", " · ".join(headline(data))]

    for w in data.get("warnings", []):
        out.append(f"⚠️ {id_warning(w)}")

    seen = [e["checker"] for e in entries]
    names = ORDER + [c for c in checkers if c not in ORDER]
    names += [c for c in seen if c not in names]

    skipped = []
    for name in names:
        rows = [e for e in entries if e["checker"] == name]
        label = SECTIONS.get(name, name)
        who = audit.agent_name(name)
        if not rows:
            # A gate that never ran stays visible. Collected into one line at
            # the end instead of six empty sections: the information is "these
            # did not run", and repeating the agent name for each one buried
            # the gates that did.
            if name in checkers or name in seen:
                skipped.append(label)
            continue
        briefs = [e for e in rows if e["verdict"] == audit.BRIEF]
        verdicts = [e for e in rows if e["verdict"] != audit.BRIEF]
        out.append("")
        out.append(f"**{label}** · {who}")
        for e in briefs:
            out.append(brief_line(e))
        for e in verdicts:
            out.append(line(e))
        if briefs and not verdicts:
            # Briefed and then silent. The look="" shape: the gate got its
            # question and decided nothing, which reads as a pass unless said.
            out.append("❓ dikasih brief tapi ga mutusin apa-apa")

    if skipped:
        out.append("")
        out.append("⏸️ ga jalan di render ini: " + ", ".join(skipped))

    gone = audit.missing_agents()
    if gone:
        out.append(f"‼️ file agent hilang: {', '.join(sorted(gone))}")

    return "\n".join(out)


def _selftest():
    data = {
        "title": "Judul Klip",
        "clip": "/x/c.mp4",
        "totals": {"pass": 2, "reject": 1, "warn": 1},
        "mood": "emotional",
        "duration_sec": 31.81,
        "warnings": [],
        "entries": [
            {"checker": "language", "target": "84 word(s) of transcript",
             "verdict": "brief", "reason": "after segment selection",
             "detail": ""},
            {"checker": "language", "target": "transcript review",
             "verdict": "pass", "reason": "no mishearings found",
             "detail": ""},
            {"checker": "edit", "target": "cutaways placed",
             "verdict": "warn", "reason": "0",
             "detail": "no footage passed the gates"},
            {"checker": "edit", "target": "freeze", "verdict": "pass",
             "reason": "floor 0.39", "detail": "frozen through the last 5s"},
            {"checker": "footage", "target": "abc @40s", "verdict": "reject",
             "reason": "not the action", "detail": "hospital corridor"},
            {"checker": "copy", "target": "style = 'pr-politik'",
             "verdict": "brief", "reason": "mood emotional", "detail": ""},
        ],
    }
    body = format_ledger(data, checkers=("sourcing", "footage", "copy"))

    # Translation happened, and the internal checker names are gone from the
    # reader's view.
    assert "ga ada salah dengar" in body, body
    assert "ga ada footage yang lolos pagar" in body, body
    assert "Transkrip" in body and "Editing" in body, body
    assert "\n**language**" not in body and "\n**edit**" not in body, body

    # The brief still prints above its gate's verdicts.
    assert body.index("dikasih: 84 kata transkrip") < body.index(
        "ga ada salah dengar"), body

    # A rejection keeps its mark and its reason.
    assert "❌ abc @40s — bukan kejadiannya, hospital corridor" in body, body

    # Briefed-but-silent is still called out, and a gate with no entries is
    # reported as not run rather than dropped.
    assert "ga mutusin apa-apa" in body, body
    assert "ga jalan di render ini: Sumber b-roll" in body, body

    # The agent's real name comes from the repo, not from this file.
    assert "Indonesian Transcript Linguist" in body, body
    assert "Short-Video Editing Coach" in body, body

    # Counts are the ledger's, not recomputed here.
    assert "4 cek · 1 ditolak" in body, body
    assert "32 detik" in body and "mood emotional" in body, body

    # Decimal comma reaches a number inside a reason, and no number is minted.
    assert "floor 0,39" in body, body
    # Two call-site fields stay two clauses.
    assert "⚠️ cutaway kepasang — 0, ga ada footage yang lolos pagar" in body, body

    # An unknown fragment ships verbatim rather than being guessed at.
    assert "hospital corridor" in body, body

    # --- regressions found by reading the posted message ------------------
    # A filename is not prose. "clip_x.mp4" must survive the phrase table,
    # which contains the word "clip" and rewrote a real path to a fake one.
    out = id_text("last 5s of clip_1791434587_122.mp4")
    assert "clip_1791434587_122.mp4" in out, out
    assert "klip_1791434587" not in out, out
    assert "dari" in out, out
    # A youtube id is not prose either.
    assert "gbDzBo9w890 @110s" in id_text("gbDzBo9w890 @110s"), \
        id_text("gbDzBo9w890 @110s")

    # A detail that restates target or reason is dropped: the music gate said
    # the same thing three times in one line.
    music = line({"checker": "sound", "target": "hype_a.mp3",
                  "verdict": "pass", "reason": "mood ['hype']",
                  "detail": "mood hype -> hype_a.mp3"})
    assert music.count("hype_a.mp3") == 1, music
    assert "->" not in music, music
    assert "['hype']" not in music, music

    # Warnings get translated too; an English warning next to Indonesian
    # verdicts is the line the operator reads first.
    warned = format_ledger({
        "title": "T", "totals": {"pass": 1, "reject": 0, "warn": 0},
        "warnings": ["b-roll: no cutaways were placed"],
        "entries": [{"checker": "edit", "target": "outro", "verdict": "pass",
                     "reason": "jamet", "detail": ""}]})
    assert "ga ada cutaway yang kepasang" in warned, warned
    assert "no cutaways" not in warned, warned

    # A warning carrying a measurement is rewritten around the number, not
    # looked up: the string differs every render, so a table cannot cover it.
    w1 = id_warning(
        "outro jamet: motion floor 3.05 in the last 5s — the freeze is not "
        "holding")
    assert "3,05" in w1 and "5s terakhir" in w1, w1
    assert "freeze is not holding" not in w1, w1
    w2 = id_warning(
        "outro jamet: clip is 14.7s, needs 15s — no closing treatment applied")
    assert "14,7s" in w2 and "15s" in w2, w2
    assert "no closing treatment" not in w2, w2
    # An unknown warning still ships rather than being dropped or invented.
    assert id_warning("something new happened") == "something new happened"

    # Clean render: no warning section, no stray "ditolak".
    clean = format_ledger({
        "title": "T", "totals": {"pass": 6, "reject": 0, "warn": 0},
        "duration_sec": 32.0, "mood": "hype", "entries": [
            {"checker": "sound", "target": "a.mp3", "verdict": "pass",
             "reason": "mood ['hype']", "detail": ""}]})
    assert "lolos semua" in clean, clean
    assert "ditolak" not in clean, clean

    print("audit_fmt: self-check ok")


if __name__ == "__main__":
    _selftest()
