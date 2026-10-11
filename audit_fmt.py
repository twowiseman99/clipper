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
import sys

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
    # Which frame the clip freezes on at the end. Registered late: until it
    # was in this table and in audit.DIVISIONS, the section header read
    # "**freeze** · freeze" — the internal name standing in for both the
    # subject and the reviewer.
    "freeze": "Gambar penutup",
}

# Order the reader cares about: what was said, how it was written, how it
# sounds, how it was cut, then the b-roll gates that reject most often.
ORDER = ["language", "copy", "sound", "edit", "freeze", "sourcing", "footage"]

MARK = {audit.PASS: "✅", audit.REJECT: "❌", audit.WARN: "⚠️"}

# Whole strings written at the call sites, with the Indonesian the operator
# would use. Matched COMPLETE ONLY.
#
# This used to fall back to substring replacement so a reason carrying a
# number still got its words translated, and that produced half-translated
# nonsense wherever a string was not in the table: "right edge dari frame",
# "--klip-type", "woman in red jacket at right dari fr". A table of phrases is
# not a translator, and a word swapped inside an English sentence is worse
# than the English sentence -- it reads as a decision the gate never made and
# corrupts CLI flags and field names on the way through.
#
# Strings carrying a measurement are handled by NUMERIC below, which matches
# the whole string with the number as a capture group. Anything in neither
# table ships in English, deliberately.
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
    "a still reads ~0 between beats; video never does":
        "gambar diam bacanya ~0 antar beat, video ga pernah",
    "outro": "outro",
    "freeze": "beku",
    "subject": "subjek",
    "window": "jendela",
    "pick": "pilih",
    "no qualifying frame": "ga ada frame yang lolos",
    "the picture is still moving inside the ending":
        "gambarnya masih gerak di dalam ending",
    "clip too short": "klip kependekan",
    "read from transcript": "dibaca dari transkrip",
    "mood clash": "mood tabrakan",
}

# Strings that are a sentence with a number in them. Matched against the WHOLE
# string with re.fullmatch, so the number is the only thing that varies and
# nothing can be rewritten inside a string the table does not fully describe.
# The number is carried across untouched; `_num` only swaps the decimal point
# for the comma Indonesian uses.
NUMERIC = [
    (r"(\d+) word\(s\) of transcript", r"\1 kata transkrip"),
    (r"(\d+) track\(s\) on this box", r"\1 lagu di box ini"),
    (r"(\d+) fixed", r"\1 diperbaiki"),
    (r"clip ([\d.]+)s", r"klip \1s"),
    (r"source ([\d.]+)s", r"sumber \1s"),
    (r"floor ([\d.]+)", r"lantai gerakan \1"),
    (r"last (\d+)s", r"\1s terakhir"),
    (r"last (\d+)s of (.+)", r"\1s terakhir dari \2"),
    (r"frozen through the last (\d+)s", r"beku terus sampai \1s terakhir"),
    (r"needs (\d+)s for a (\d+)s ending", r"butuh \1s buat ending \2s"),
    (r"clip too short — (\d+)s needed", r"klip kependekan, butuh \1s"),
    (r"hook (\d+) / title (\d+) chars", r"hook \1 / judul \2 huruf"),
    (r"mood = '(\w+)'", r"mood = '\1'"),
    (r"style = '([\w-]+)'", r"gaya = '\1'"),
    (r"outro = '(\w+)'", r"outro = '\1'"),

    (r"mood (\w+) -> (.+)", r"mood \1 -> \2"),
    (r"used '(\w+)'", r"dipakai '\1'"),
    (r"kept '(\w+)' \(explicit (--[\w-]+)\)", r"tetep '\1' (dipaksa \2)"),
    (r"preset '(\w+)' vs transcript '(\w+)'",
     r"preset '\1' vs transkrip '\2'"),
    # The music gate passes its mood list straight from Python, so the reason
    # reads `mood ['hype']` -- a repr, brackets and quotes included, in a
    # chat message. One mood is the normal case; several are joined with a
    # comma rather than printed as a list.
    (r"mood \['([\w-]+)'\]", r"mood \1"),
    (r"mood \['([\w-]+)', '([\w-]+)'\]", r"mood \1 + \2"),
]

_NUMERIC = [(re.compile(src), repl) for src, repl in NUMERIC]

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
    """Indonesian for a string the tables describe WHOLE, else the original.

    Whole-string only, in both tables. The previous version also replaced
    every table key found anywhere inside the string, which rewrote words in
    the middle of English sentences no table entry covered: the model's own
    "right edge of frame" came out as "right edge dari frame", the field name
    `subject` became `subjek` inside an English clause, and `--clip-type`
    became `--klip-type` -- a CLI flag that does not exist, printed as if the
    operator could paste it.

    A phrase table can only honestly translate what it describes completely.
    What it does not describe ships in English.
    """
    if not text:
        return ""
    if text in PHRASES:
        return PHRASES[text]
    # Literals are masked even on the no-match path, so a file name can never
    # be touched by a pattern that happens to span it.
    masked, literals = _protect(text)
    out = masked
    for rx, repl in _NUMERIC:
        m = rx.fullmatch(masked)
        if m:
            out = m.expand(repl)
            break
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
    """Indonesian decimal comma, applied only to a MEASUREMENT.

    "Only a bare number" was not what the pattern did: it rewrote any digit
    pair around a dot, which includes the stamp inside a path. A real render
    printed the debug file as
    `jobs/freeze-debug/render3,20261011-185702.freeze.json` -- a path that
    does not exist, in the field whose whole job is to be openable.

    Literals are masked out first, by the same rule that protects a file name
    from translation, so a decimal point only becomes a comma in prose.
    """
    # Not preceded by a word character, slash or dot, and not followed by a
    # digit, slash, dot or underscore -- those would make it part of an
    # identifier, a version or a path. A dash is allowed on BOTH sides: a
    # range reads "144.27s-150.27s" and both halves are measurements. Paths
    # are already masked above, which is what keeps a dash inside a file
    # stamp out of reach.
    masked, literals = _protect(str(value))
    out = re.sub(r"(?<![\w/.])(\d+)\.(\d+)(?![\d/._])", r"\1,\2", masked)
    for i, lit in enumerate(literals):
        out = out.replace("\x00%d\x00" % i, lit)
    return out


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


# The detail fields a warning carries after its narrative sentence, written at
# the call site as "narasi | stage: x | source: y.py:fn | ...". Rendered as an
# aligned code block rather than a paragraph: these are a file name, a flag, a
# timestamp and a path, and a reader needs to copy them, not read them.
#
# Order is fixed here rather than taken from the string, so every error block
# in the channel has its fields in the same places.
DETAIL_ORDER = ["stage", "source", "video", "trigger", "error", "fix",
                "fallback", "debug"]


def split_detail(text):
    """("narrative", {field: value}) from a pipe-separated warning."""
    parts = [p.strip() for p in text.split(" | ")]
    narrative = parts[0] if parts else ""
    fields = {}
    for part in parts[1:]:
        if ": " not in part:
            continue
        key, _, value = part.partition(": ")
        key = key.strip()
        # A later field of the same name would silently win, which for
        # `error` would mean showing the wrong one. First wins.
        fields.setdefault(key.strip(), value.strip())
    return narrative, fields


def detail_block(fields):
    """The fields as an aligned code block, in DETAIL_ORDER, nothing invented.

    Only keys actually present are shown. An absent field means the call site
    did not record it; printing an empty row would read as a measured blank.
    """
    keys = [k for k in DETAIL_ORDER if fields.get(k)]
    keys += [k for k in fields if k not in DETAIL_ORDER and fields.get(k)]
    if not keys:
        return []
    width = max(len(k) for k in keys)
    rows = ["```"]
    for k in keys:
        # Values are never translated: file names, functions, CLI flags, raw
        # error text and paths. _num is applied to the measured ones only,
        # where a decimal comma is the operator's own notation.
        value = fields[k]
        if k in ("video", "trigger"):
            value = _num(value)
        rows.append(f"{k.ljust(width)} : {value}")
    rows.append("```")
    return rows


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


def issue_block(data):
    """The "check this before upload" section: every ⚠️ and ❌ with its fields.

    Built separately from the narrative because it is the part that must
    survive truncation. A render that produced no warning and no reject gets
    an empty list, and the caller prints nothing.
    """
    out = []
    for w in data.get("warnings", []):
        narrative, fields = split_detail(w)
        out.append(f"⚠️ {id_warning(narrative)}")
        out.extend(detail_block(fields))
    for e in data.get("entries", []):
        if e.get("verdict") != audit.REJECT:
            continue
        who = audit.agent_name(e["checker"])
        narrative, fields = split_detail(e.get("detail", ""))
        fields.setdefault("stage", e["checker"])
        fields.setdefault("error", e.get("reason", ""))
        out.append("❌ %s (%s) — %s" % (who, e["checker"],
                                        id_text(e.get("reason", ""))))
        if narrative:
            out.append("   " + _num(id_text(narrative)))
        out.extend(detail_block(fields))
    if out:
        out.insert(0, "**Perlu dicek sebelum upload:**")
        out.insert(0, "")
    return out


def format_ledger(data, checkers=(), limit=None):
    """The whole message: header, agent narrative, then the issues.

    `limit` caps the result in characters. When it is exceeded the NARRATIVE
    is dropped, never the issue block: the per-agent commentary is nice to
    read and the error fields are the reason the message exists. One render
    used to produce 179 messages and 328,206 truncated characters, which is
    exactly the content a reader needed being thrown away last.
    """
    entries = data.get("entries", [])
    title = data.get("title") or (data.get("clip", "").rsplit("/", 1)[-1])
    render_id = data.get("clip", "").rsplit("/", 1)[-1].replace(".mp4", "")
    head = [f"🎬 **{title}**",
            " · ".join(headline(data) + ([render_id] if render_id else []))]
    out = list(head)
    issues = issue_block(data)
    seen = [e["checker"] for e in entries]
    names = ORDER + [c for c in checkers if c not in ORDER]
    # Append one name per checker, checking against the list AS IT GROWS.
    # `names += [c for c in seen if c not in names]` reads like a dedupe and is
    # not one: the comprehension is fully evaluated against the OLD `names`
    # before `+=` extends it, so every occurrence of an unregistered checker
    # passed the test. A ledger with 33 freeze entries printed the freeze
    # section 33 times — 113,657 characters and 179 Discord messages for one
    # render.
    for c in seen:
        if c not in names:
            names.append(c)

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
        # A verdict this formatter does not know is a diagnostic stream, not a
        # decision — and printing it one line per entry is how the freeze
        # gate's "info" rows became 1,023 lines. Skipped, counted, and named
        # on stderr so the gate gets fixed instead of the channel flooded.
        unknown = [e for e in verdicts if e["verdict"] not in MARK]
        if unknown:
            verdicts = [e for e in verdicts if e["verdict"] in MARK]
            kinds = sorted({e["verdict"] for e in unknown})
            print("audit_fmt: %s recorded %d entries with unknown verdict(s) "
                  "%s — skipped. A gate must report pass/warn/reject; "
                  "per-item diagnostics belong in a debug file."
                  % (name, len(unknown), ", ".join(repr(k) for k in kinds)),
                  file=sys.stderr)
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

    body = "\n".join(out + issues)
    if limit is None or len(body) <= limit:
        return body

    # Over budget. Drop the narrative, keep the header and every issue field,
    # and say so — a message that silently lost its middle is indistinguishable
    # from a render that had nothing to report.
    debug = [f for f in (split_detail(w)[1].get("debug")
                         for w in data.get("warnings", [])) if f]
    note = ["", "_(obrolan per-agent dipotong, ga masuk batas Discord"
            + (f" — lengkapnya: {debug[0]}" if debug else "") + ")_"]
    trimmed = "\n".join(head + note + issues)
    if len(trimmed) <= limit:
        return trimmed
    # Even the issues do not fit. Keep whole lines from the front rather than
    # cutting mid-field, and name the debug file so nothing is lost silently.
    kept, used = [], 0
    for ln in head + note + issues:
        if used + len(ln) + 1 > limit - 80:
            break
        kept.append(ln)
        used += len(ln) + 1
    kept.append("_(kepotong — detail lengkap di %s)_"
                % (debug[0] if debug else "jobs/freeze-debug/"))
    return "\n".join(kept)


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
    # The phrase itself is translated now ("floor" -> "lantai gerakan"), so
    # assert on the measurement, which is the part this check is about.
    assert "lantai gerakan 0,39" in body, body
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
