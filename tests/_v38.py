"""The agent file must be the prompt that is actually sent, not a label.

Before this, audit.py named the reviewing agent and _v37 proved the file
existed and that the printed name matched the file's frontmatter — but nothing
read the body. The prompts sent to the model were hand-written in metadata.py
and language.py, so the ledger credited "TikTok Strategist" for copy that a
separately-maintained SYSTEM string produced. A verifiable name on an
unconsulted reviewer is still a fake reviewer.

The operator's instruction was "ikutin structure itu, kenapa buat-buat
sendiri", and on the merge question: identity and rules from the .md, format
and limits from the code. So this test asserts the real call, by intercepting
ai.chat_json and reading what the model would have received:

  1. the agent's persona leads the system message
  2. Clipper's technical contract is still present, AFTER it
  3. the override line sits between them, so the contract wins
  4. a missing agent file degrades to the old prompt instead of raising
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import agent_skills  # noqa: E402
import agents  # noqa: E402
import ai  # noqa: E402
import audit  # noqa: E402
import language  # noqa: E402
import metadata  # noqa: E402

STUB = {"hook": "a", "title": "b", "description": "c #x", "youtube_tags": [],
        "punchline": "", "words": ["bekal"]}


def capture(fn):
    """Run fn with ai.chat_json intercepted; return the system messages."""
    seen = []
    orig = ai.chat_json
    # language.py and metadata.py both import ai and call ai.chat_json, so
    # patching the attribute on the module object covers both call sites.
    ai.chat_json = lambda system, user, **kw: (seen.append(system) or
                                               dict(STUB))
    try:
        fn()
    finally:
        ai.chat_json = orig
    return seen


def run_copy():
    metadata.generate("Gibran minta anak bawa bekal dari rumah yang dimasak ibu",
                      {"hashtags": ["#Gibran"]}, style="pr-politik")


def run_language():
    language.review([{"word": "bekal", "start": 1.0, "end": 1.4}],
                    context="Gibran")


copy_sys = capture(run_copy)
lang_sys = capture(run_language)
assert copy_sys, "metadata.generate never called the model"
assert lang_sys, "language.review never called the model"

# --- 1. the agent leads -----------------------------------------------------
for label, msgs, want in (("copy", copy_sys, "TikTok Strategist"),
                          ("language", lang_sys, "Indonesian Transcript Linguist")):
    for s in msgs:
        assert s.startswith("You are "), f"{label}: persona not first: {s[:80]!r}"
        assert want in s, f"{label}: {want!r} missing from the system message"
        # The declared name, read from the file — not a copy in audit.py.
        assert audit.agent_name(label) in s, label

# --- 2. the technical contract survives, after the persona ------------------
# Checked by content, not by position in the tail: metadata appends a style
# preset after SYSTEM, so the last characters are the preset's rules rather
# than the JSON contract. An earlier version of this check looked only at the
# final 1200 characters and reported a false failure.
copy_body = copy_sys[0]
mark = copy_body.index("--- Clipper assignment")
technical = copy_body[mark:]
# Only rules that live in SYSTEM. The character caps ("maksimal 90 karakter")
# are in USER_TEMPLATE, which is a separate message and is not affected by the
# persona merge — asserting on them here failed for the right reason and would
# have been a wrong fix to chase in agents.py.
for needed in ("Output strictly a JSON object", "NEVER use the em dash",
               "NEVER state a number", "Title craft"):
    assert needed in technical, f"copy: lost technical rule {needed!r}"
# The style preset the operator picked must still arrive.
assert "transkrip" in technical.lower()

lang_body = lang_sys[0]
lmark = lang_body.index("--- Clipper assignment")
# language.SYSTEM is one sentence (129 chars); its JSON word-list contract is
# in the user message, not the system message. Assert on what SYSTEM actually
# says — that this is ASR repair only — rather than on a string that was never
# there.
lang_tech = lang_body[lmark:]
assert "speech-to-text" in lang_tech, lang_tech[:300]
assert "HANYA memperbaiki" in lang_tech, lang_tech[:300]

# --- 3. the contract is declared binding, between the two halves ------------
for label, body in (("copy", copy_body), ("language", lang_body)):
    m = body.index("--- Clipper assignment")
    assert "override" in body[m:m + 200], label
    assert body.index("You are ") < m, f"{label}: persona is not first"
    # Nothing of the persona may appear after the binding line, or the
    # "code wins" ordering is only decorative.
    assert "You are " not in body[m:], label

# --- 4. a missing agent file must not break a render ------------------------
# The agent file and the gate's skills are two independent sources, so losing
# the .md does not strip the prompt bare — the skills block still applies, and
# the technical contract is still declared binding. Only when BOTH are gone
# does it fall back to the plain hand-written prompt.
saved = audit.AGENTS_ROOT
saved_roots = dict(agent_skills.SKILL_ROOTS)
try:
    audit.AGENTS_ROOT = "/nonexistent-agency-root"
    agents._cache.clear()
    degraded = capture(run_copy)
    assert degraded, "render died when the agent file was missing"
    body = degraded[0]
    assert "You are " not in body.split("--- Clipper assignment")[0]
    assert "### Skills" in body, body[:200]
    assert "Output strictly a JSON object" in body, "technical prompt lost"

    for k in agent_skills.SKILL_ROOTS:
        agent_skills.SKILL_ROOTS[k] = "/nonexistent-skill-root"
    agent_skills._cache.clear()
    bare = capture(run_copy)
    body = bare[0]
    assert "--- Clipper assignment" not in body, body[:200]
    assert "### Skills" not in body, body[:200]
    assert "Output strictly a JSON object" in body, "technical prompt lost"
finally:
    audit.AGENTS_ROOT = saved
    agent_skills.SKILL_ROOTS.update(saved_roots)
    agent_skills._cache.clear()
    agents._cache.clear()

# --- 4b. each gate is handed the skills matching its job desk ---------------
# The operator's instruction was "cukup kasi skill2 yg relevan sama job desk
# mreka", so the pairing is asserted at the prompt, not just in the table.
assert not agent_skills.missing(), agent_skills.missing()
for checker in audit.DIVISIONS:
    assert checker in agent_skills.SKILLS, f"{checker}: no skills decision"
copy_skills = agent_skills.block("copy")
assert "brainstorming" in copy_skills
assert "/skill-sources/" in copy_skills, "skill path not given to the agent"
# The sound gate is deliberately empty: neither repo has an audio skill, and a
# near-miss pairing would repeat the invented-label mistake.
assert agent_skills.block("sound") == ""
# Skills are advisory and must sit BEFORE the binding contract.
assert copy_body.index("### Skills") < copy_body.index("--- Clipper assignment")

# --- 5. the persona is bounded ---------------------------------------------
# These files run 900-1400 words. The technical half is the verified one; it
# must not be pushed out of the model's attention by a 6000-character persona.
for checker in audit.DIVISIONS:
    assert len(agents.persona(checker)) <= agents.MAX_PERSONA, checker

print("_v38 ok — agent personas reach the model (copy %d chars, language %d), "
      "technical contract preserved and binding, missing file degrades safely"
      % (len(copy_body), len(lang_body)))
