"""Load the agency-agents files that review each render, as real prompts.

The gap this closes: audit.py already names the agent that reviews each gate,
and _v37 proves the file exists and that the printed name is the one the file
declares. But nothing ever READ those files. The prompts actually sent to the
model were written by hand in metadata.py and language.py, so the ledger said
"agent: TikTok Strategist" while a different, separately-maintained instruction
did the work. That is the fake-reviewer bug with a verifiable name on it.

The operator's call was explicit: the agent file becomes the real prompt,
combined with Clipper's technical constraints — identity and rules from the
.md, format and limits from the code. Not a wholesale swap: these files are
written for general-purpose coding agents and know nothing about 9:16 output,
Indonesian captions, or an 80-character title cap. Dropping the hand-written
half would lose constraints that took a dozen renders to get right.

So: persona from the file, contract from the code, in that order.

Heading layout is NOT consistent across the repo — tiktok-strategist has
"Core Mission" and a "Critical Rules" that opens straight into a subheading,
evidence-collector has neither. The extractor therefore takes what is there and
never requires a section.
"""

import os
import re

import agent_skills
import audit

# Sections worth putting in front of a model, in the order they should appear.
# Identity establishes who is reviewing, mission what they are for, rules what
# they refuse to do. Workflow/metrics/communication sections are left out: they
# describe how the agent reports to a human team, which is noise here and would
# crowd out the technical contract that follows.
SECTIONS = ("Identity", "Core Mission", "Mission", "Critical Rules", "Rules")
# Cap on persona text per agent. These files run 900-1400 words; the whole point
# of the technical half is that it stays in the model's attention, and a 6000
# character persona in front of it does not help.
MAX_PERSONA = int(os.environ.get("CLIPPER_AGENT_PERSONA_CHARS", "2600"))

_cache = {}


def _frontmatter(text):
    """{key: value} from the leading --- block, or {} when absent."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    out = {}
    for line in text[3:end].split("\n"):
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _body(text):
    """Everything after the frontmatter."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end >= 0:
            return text[end + 4:]
    return text


def _section(body, want):
    """A heading's content INCLUDING its subheadings, or "".

    Stopping at the next heading of any level is wrong here: the repo's
    "## Critical Rules" is immediately followed by "### TikTok-Specific
    Standards", so a naive scan returns an empty string for the one section
    whose whole job is to carry the rules.
    """
    pat = re.compile(r"^(#{2,4})\s*[^\n]*?" + re.escape(want) + r"[^\n]*\n",
                     re.I | re.M)
    m = pat.search(body)
    if not m:
        return ""
    depth = len(m.group(1))
    rest = body[m.end():]
    # Stop only at a heading at the same depth or shallower.
    stop = re.search(r"^#{1,%d}\s" % depth, rest, re.M)
    return (rest[:stop.start()] if stop else rest).strip()


def persona(checker):
    """The agent's own words, trimmed to MAX_PERSONA, or "" when unavailable.

    Never raises: a render must not die because an agent file moved. The ledger
    reports a missing file separately (audit.missing_agents), so a silent "" here
    cannot be mistaken for "the agent approved it".
    """
    if checker in _cache:
        return _cache[checker]
    path = audit.agent_path(checker)
    if not path or not os.path.exists(path):
        _cache[checker] = ""
        return ""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        _cache[checker] = ""
        return ""
    fm = _frontmatter(text)
    body = _body(text)
    parts = []
    name = fm.get("name", "")
    if name:
        head = f"You are {name}"
        role = fm.get("description", "")
        if role:
            head += f". {role}"
        parts.append(head)
    if fm.get("vibe"):
        parts.append(fm["vibe"])
    seen = set()
    for want in SECTIONS:
        chunk = _section(body, want)
        if not chunk or chunk[:120] in seen:
            continue
        seen.add(chunk[:120])
        parts.append(chunk)
    out = "\n\n".join(p for p in parts if p).strip()
    # Trim on a line boundary so a rule is never cut in half.
    if len(out) > MAX_PERSONA:
        out = out[:MAX_PERSONA].rsplit("\n", 1)[0].rstrip()
    _cache[checker] = out
    return out


def system_for(checker, technical):
    """Persona, then the gate's skills, then Clipper's contract — contract wins.

    Order and the closing line are both deliberate: these agent files are
    written for a general audience and will happily suggest a 16:9 deliverable
    or an English hook. The technical half is the part that was verified against
    real renders, so it comes last and is declared authoritative.

    Skills sit between the two: they belong to the agent (the operator's
    instruction was to hand each agent the skills matching its job desk), but
    they are advisory, so the binding contract still has the final word.
    """
    body = persona(checker)
    skills = agent_skills.block(checker)
    if not body and not skills:
        return technical
    parts = [p for p in (body, skills) if p]
    return (
        "\n\n".join(parts) + "\n\n"
        f"--- Clipper assignment: the rules below are binding and override "
        f"anything above them, including format, language and length. ---\n\n"
        f"{technical}"
    )


def _selftest():
    missing = audit.missing_agents()
    assert not missing, f"agent files missing: {missing}"

    # Every gate must yield a usable persona. A gate whose file parses to
    # nothing would silently fall back to the old hand-written prompt while the
    # ledger still claimed the agent reviewed it.
    for checker in audit.DIVISIONS:
        body = persona(checker)
        assert body, f"{checker}: empty persona"
        assert len(body) <= MAX_PERSONA, f"{checker}: {len(body)} chars"
        assert body.startswith("You are "), body[:60]
        assert audit.agent_name(checker) in body, checker

    # The subheading trap: "## Critical Rules" followed straight by "###" must
    # still return the rules.
    tik = persona("copy")
    assert "TikTok" in tik, tik[:200]

    # The linguist's rules mention Indonesian morphology, which is the content
    # that makes it the right agent for the language gate.
    ling = persona("language")
    assert "Indonesian" in ling

    # The technical contract must survive, come last, and be declared binding.
    sysmsg = system_for("copy", "RETURN JSON ONLY. maksimal 80 karakter.")
    assert sysmsg.endswith("RETURN JSON ONLY. maksimal 80 karakter.")
    assert "override" in sysmsg
    assert sysmsg.index("You are") < sysmsg.index("RETURN JSON ONLY")

    # An unknown agent degrades to the technical prompt unchanged, rather than
    # raising mid-render.
    assert system_for("nope", "X") == "X"
    saved = audit.AGENTS_ROOT
    saved_skills = dict(agent_skills.SKILL_ROOTS)
    try:
        audit.AGENTS_ROOT = "/nonexistent"
        _cache.clear()
        assert persona("copy") == ""
        # With the agent file gone the persona is empty, but the gate's skills
        # are a separate source and still apply — so the prompt is NOT bare.
        # Both must be unavailable before falling all the way back.
        assert "### Skills" in system_for("copy", "X")
        for k in agent_skills.SKILL_ROOTS:
            agent_skills.SKILL_ROOTS[k] = "/nonexistent"
        agent_skills._cache.clear()
        assert system_for("copy", "X") == "X"
    finally:
        audit.AGENTS_ROOT = saved
        agent_skills.SKILL_ROOTS.update(saved_skills)
        agent_skills._cache.clear()
        _cache.clear()

    print("agents: self-check ok")


if __name__ == "__main__":
    _selftest()
