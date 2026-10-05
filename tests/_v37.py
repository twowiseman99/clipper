"""Every division the ledger names must be a real division with a real agent.

The ledger used to print invented labels — "RESEARCH" for the footage gate,
"SPECIALIZED" for language, "DESIGN" for sound. They read like the
agency-agents repo's divisions while matching no agent in it, so the review
named a reviewer that did not exist. The operator's instruction was direct:
"ikutin structure itu, kenapa buat-buat sendiri".

The repo declares its own source of truth in divisions.json, and ships a CI
check (scripts/check-divisions.sh) that fails the build when that list
disagrees with the directories on disk. This test holds Clipper to the same
contract: every division we name is in divisions.json, every agent we name is a
file on disk with frontmatter, and the name we print is the one the agent
declares — not a copy kept here that can drift.
"""

import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import audit  # noqa: E402

root = pathlib.Path(audit.AGENTS_ROOT)
assert root.is_dir(), f"agency-agents repo not found at {root}"

# --- divisions.json is the authority, not this file ------------------------
declared = json.loads((root / "divisions.json").read_text())["divisions"]
for checker, (division, stem) in audit.DIVISIONS.items():
    assert division in declared, (
        f"{checker}: division {division!r} is not in divisions.json "
        f"({sorted(declared)})")
    # The repo's own rule: a division is a directory on disk.
    assert (root / division).is_dir(), f"{division} has no directory"

# --- every agent we name is a file, with frontmatter -----------------------
for checker in audit.DIVISIONS:
    path = pathlib.Path(audit.agent_path(checker))
    assert path.exists(), f"{checker}: no agent file at {path}"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{checker}: {path.name} has no frontmatter"
    head = text.split("---", 2)[1]
    for field in ("name:", "description:"):
        assert field in head, f"{checker}: {path.name} missing {field}"

assert not audit.missing_agents(), audit.missing_agents()

# --- the printed name comes FROM the file ----------------------------------
# Not a second copy in audit.py. Two copies of a name drift, and the whole
# point of pointing at the repo is that the repo wins.
for checker, (division, stem) in audit.DIVISIONS.items():
    declared_name = ""
    for line in (root / division / f"{stem}.md").read_text().split("---")[1].split("\n"):
        if line.startswith("name:"):
            declared_name = line.split(":", 1)[1].strip()
            break
    assert declared_name, f"{checker}: agent file declares no name"
    assert audit.agent_name(checker) == declared_name, (
        f"{checker}: ledger prints {audit.agent_name(checker)!r} but the agent "
        f"file declares {declared_name!r}")

# --- a missing agent file must be reported, never printed silently ---------
saved = audit.AGENTS_ROOT
try:
    audit.AGENTS_ROOT = "/nonexistent-agency-root"
    gone = audit.missing_agents()
    assert len(gone) == len(audit.DIVISIONS), gone
    led = audit.Ledger()
    led.passed("copy", "marketing filler", "none")
    text = led.report(checkers=("copy",))
    assert "agent file hilang" in text, text
    # And it must still name what it was looking for, so the fix is obvious.
    assert "/nonexistent-agency-root" in text, text
finally:
    audit.AGENTS_ROOT = saved

# --- the Indonesian linguist is ours, and is not the Spanish translator ----
# The repo's specialized/language-translator.md is Spanish <-> English. Using it
# for Indonesian ASR repair would be exactly the fake-reviewer bug again.
ling = pathlib.Path(audit.agent_path("language"))
assert "indonesian" in ling.name, ling.name
body = ling.read_text(encoding="utf-8").lower()
assert "indonesian" in body
translator = root / "specialized" / "language-translator.md"
if translator.exists():
    assert audit.agent_path("language") != str(translator), (
        "language gate must not point at the Spanish/English translator")

print("_v37 ok — %d divisions, all in divisions.json, all agents on disk, "
      "names read from frontmatter" % len(audit.DIVISIONS))
