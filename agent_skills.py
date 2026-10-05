"""Which skills each reviewing agent is handed, and how they reach the prompt.

The operator's instruction: "Kita enhance agency agent dengan superpower,
github yg cocok jg ... cukup kasi skill2 yg relevan sama job desk mreka."
So each gate's agent gets the skills that match its job description, from the
repos already on disk — not a new invention, and not every skill.

Sources, all cloned already under ~/skill-sources:
  superpowers  github.com/obra/superpowers      15 skills
  gstack       github.com/garrytan/gstack       63 skills

Two constraints shaped the design:

1. Size. gstack's qa-only is 45 KB and test-audit is 40 KB. Inlining a skill
   body would bury the technical contract that took a dozen renders to get
   right — the same failure mode as an oversized persona. So the prompt gets
   each skill's NAME and its own one-line description, read from its SKILL.md
   frontmatter, plus the on-disk path. The agent is told the path so a human
   (or a coding agent with filesystem access) can open the full text.

2. Relevance. A skill is listed only where it matches the gate's job. The
   footage gate reviews whether a clip really shows what the caption claims,
   which is Evidence Collector's "marks untested scope honestly" — so
   verification-before-completion belongs there. iOS QA does not.

Upstream convention: agency-agents writes skills as a markdown "### Skills"
section inside the agent body (see specialized/zk-steward.md), NOT as a
frontmatter field. This module follows that, so a skills block added here
reads the same way as one written upstream.
"""

import os
import re

SKILL_ROOTS = {
    "superpowers": os.path.expanduser("~/skill-sources/superpowers"),
    "gstack": os.path.expanduser("~/skill-sources/gstack"),
}

# gate -> skills, in the order they should be offered. Keyed by the checker
# name a module registers with audit.py, so this table lines up with
# audit.DIVISIONS and _v39 can assert they agree.
#
# Each entry is (repo, skill-name). The rationale per gate is the agent's own
# job description, quoted in the comments, so a later reader can tell whether
# a pairing still holds.
SKILLS = {
    # Evidence Collector: "Reports reproducible issues with evidence and marks
    # untested scope honestly." That is exactly the b-roll rule — footage must
    # really show the thing, and "no footage exists" must be said out loud
    # rather than papered over with a loose match.
    "sourcing": [
        ("superpowers", "verification-before-completion"),
        ("gstack", "qa-only"),
    ],
    "footage": [
        ("superpowers", "verification-before-completion"),
        ("superpowers", "systematic-debugging"),
    ],
    # TikTok Strategist: "viral content creation, algorithm optimization".
    # brainstorming is the one superpowers skill about generating options
    # before committing, which is what hook/title writing is.
    "copy": [
        ("superpowers", "brainstorming"),
    ],
    # Indonesian Transcript Linguist: "Fixes ASR mishearings ... without
    # touching word timings". A mishearing is a bug with a wrong fix available
    # (plausible word, wrong word), so the debugging discipline applies.
    "language": [
        ("superpowers", "systematic-debugging"),
        ("superpowers", "verification-before-completion"),
    ],
    # Focus Music Architect: instrumental selection. No skill in either repo
    # covers audio or music, and inventing a pairing here would be the same
    # mistake as the invented division labels. Left empty on purpose.
    "sound": [],
    # Short-Video Editing Coach: "the full post-production pipeline".
    # design-review targets "visual inconsistency, spacing issues, hierarchy
    # problems, AI slop patterns" — the register mismatches the operator keeps
    # catching before the automated checks do.
    "edit": [
        ("gstack", "design-review"),
        ("superpowers", "verification-before-completion"),
    ],
}

_cache = {}


def skill_path(repo, name):
    """Absolute path to a skill's SKILL.md, or "" when it is not on disk.

    Layout differs between the two repos — superpowers nests under skills/,
    gstack puts each skill at the top level — so the file is located by search
    rather than by a hardcoded shape.
    """
    root = SKILL_ROOTS.get(repo)
    if not root or not os.path.isdir(root):
        return ""
    key = (repo, name)
    if key in _cache:
        return _cache[key]
    found = ""
    for base, dirs, files in os.walk(root):
        if ".git" in dirs:
            dirs.remove(".git")
        if "SKILL.md" in files and os.path.basename(base) == name:
            found = os.path.join(base, "SKILL.md")
            break
    _cache[key] = found
    return found


def describe(repo, name):
    """(name, one-line description) read from the skill's own frontmatter.

    The description is the skill's, not a summary written here: a second copy
    would drift from the source the same way the agent names did before they
    were read from frontmatter.
    """
    path = skill_path(repo, name)
    if not path:
        return name, ""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            head = fh.read(4000)
    except OSError:
        return name, ""
    desc = ""
    m = re.search(r"^description:\s*(.+)$", head, re.M)
    if m:
        desc = m.group(1).strip().strip('"').strip()
    # Descriptions run long and some span lines; one sentence is enough to say
    # what the skill is for.
    if len(desc) > 180:
        desc = desc[:180].rsplit(" ", 1)[0] + "..."
    return name, desc


def missing(gate=None):
    """[(repo, name)] for skills referenced but not present on disk."""
    gates = [gate] if gate else list(SKILLS)
    out = []
    for g in gates:
        for repo, name in SKILLS.get(g, ()):
            if not skill_path(repo, name):
                out.append((repo, name))
    return out


def block(gate):
    """The "### Skills" section for a gate, or "" when it has none.

    Follows the upstream convention of a markdown section in the agent body.
    Paths are included because the body is only a pointer: these files run to
    45 KB and belong on disk, not in a system prompt.
    """
    entries = SKILLS.get(gate) or []
    if not entries:
        return ""
    found = [(r, n) for r, n in entries if skill_path(r, n)]
    if not found:
        # Every skill for this gate is absent. A block listing nothing but
        # "NOT INSTALLED" is noise in a system prompt — the caller treats ""
        # as "no skills available" and falls back. Partial availability still
        # reports the gaps below, because there the agent needs to know which
        # of the skills it was promised it cannot use.
        return ""
    lines = ["### Skills available to you",
             "Apply these when they fit the task. Full text is on disk at the "
             "path shown; the one-line summary is the skill's own."]
    for repo, name in entries:
        path = skill_path(repo, name)
        if not path:
            # Silence here would read as "this agent has no such skill", so an
            # absent file is stated rather than dropped.
            lines.append(f"- {name} ({repo}) — NOT INSTALLED, skip it")
            continue
        _n, desc = describe(repo, name)
        lines.append(f"- {name} ({repo}): {desc}" if desc
                     else f"- {name} ({repo})")
        lines.append(f"  {path}")
    return "\n".join(lines)


def _selftest():
    import audit

    # Every gate audit knows about must have an entry, even an empty one, so a
    # new gate cannot silently inherit no skills by omission.
    for checker in audit.DIVISIONS:
        assert checker in SKILLS, f"{checker}: no skills decision recorded"

    gone = missing()
    assert not gone, f"skills referenced but not on disk: {gone}"

    # A populated gate produces a block naming each skill with its path.
    b = block("footage")
    assert "verification-before-completion" in b
    assert "systematic-debugging" in b
    assert "/skill-sources/" in b
    assert b.startswith("### Skills")

    # The empty gate stays empty rather than being padded with a near-miss.
    assert block("sound") == ""
    assert block("nope") == ""

    # Descriptions come from the skill files themselves.
    _n, desc = describe("superpowers", "verification-before-completion")
    assert desc and "complete" in desc.lower(), desc
    assert len(desc) <= 184, len(desc)

    # A skill that is listed but missing must say so in the prompt.
    saved = SKILL_ROOTS["gstack"]
    try:
        SKILL_ROOTS["gstack"] = "/nonexistent"
        _cache.clear()
        assert "NOT INSTALLED" in block("edit")
    finally:
        SKILL_ROOTS["gstack"] = saved
        _cache.clear()

    print("agent_skills: self-check ok — %d gates, %d pairings"
          % (len(SKILLS), sum(len(v) for v in SKILLS.values())))


if __name__ == "__main__":
    _selftest()
