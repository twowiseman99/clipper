#!/usr/bin/env python3
"""Every checker any module records under must be registered in both tables.

`freeze` was recording 781 entries across 25 ledgers while absent from
audit.DIVISIONS and audit_fmt.SECTIONS, so its header read "**freeze** ·
freeze" — the internal name standing in for both the subject and the
reviewer, which is the exact leak audit_fmt exists to prevent.

This test finds checkers by grepping the call sites rather than by listing
them, so a gate added next month fails here instead of shipping its internal
name to the channel. It also fails when a registered agent file is missing:
naming a reviewer the roster does not define is the same class of error as the
invented division labels DIVISIONS replaced.
"""

import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import audit        # noqa: E402
import audit_fmt    # noqa: E402

CALL = re.compile(
    r"audit\.(?:record|passed|rejected|warned|briefed)\(\s*[\"']([\w-]+)[\"']")


def recorded_checkers():
    """Checker names passed to audit.* anywhere in the package."""
    found = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "*.py"))):
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                for name in CALL.findall(line):
                    found.setdefault(name, []).append(
                        f"{os.path.basename(path)}:{i}")
    return found


def main():
    found = recorded_checkers()
    assert found, "no audit.* call sites found — the regex stopped matching"

    unregistered = {n: w for n, w in found.items() if n not in audit.DIVISIONS}
    assert not unregistered, (
        "checker recorded but missing from audit.DIVISIONS, so the ledger "
        f"names no reviewer for it: {unregistered}")

    unlabelled = {n: w for n, w in found.items()
                  if n not in audit_fmt.SECTIONS}
    assert not unlabelled, (
        "checker recorded but missing from audit_fmt.SECTIONS, so its header "
        f"shows the internal name: {unlabelled}")

    # Both tables describe the same set of gates. A row in one and not the
    # other is how "freeze" ended up half-registered.
    assert set(audit.DIVISIONS) == set(audit_fmt.SECTIONS), (
        "DIVISIONS and SECTIONS disagree: "
        f"{set(audit.DIVISIONS) ^ set(audit_fmt.SECTIONS)}")

    # ORDER decides reading order and drives the `checkers` tuple that makes a
    # silent gate visible, so a gate absent from it is invisible when it does
    # not run.
    assert set(audit_fmt.ORDER) == set(audit_fmt.SECTIONS), (
        "ORDER is missing a section: "
        f"{set(audit_fmt.SECTIONS) - set(audit_fmt.ORDER)}")

    # THE THIRD TABLE. Registering `freeze` in DIVISIONS and SECTIONS left it
    # absent from agent_skills.SKILLS, which decides which skills the gate's
    # reviewer loads. This test asserted two of the three tables and reported
    # the gate as fully registered; tests/_v38.py caught the third. Asserting
    # a set is complete means naming every table that has to contain it.
    import agent_skills
    unskilled = {n: w for n, w in found.items()
                 if n not in agent_skills.SKILLS}
    assert not unskilled, (
        "checker recorded but missing from agent_skills.SKILLS, so no skills "
        f"decision exists for it: {unskilled}")
    assert set(agent_skills.SKILLS) == set(audit.DIVISIONS), (
        "SKILLS and DIVISIONS disagree: "
        f"{set(agent_skills.SKILLS) ^ set(audit.DIVISIONS)}")

    # A registered reviewer must exist on disk and must have a real name.
    assert not audit.missing_agents(), (
        f"agent file missing for: {audit.missing_agents()} under "
        f"{audit.AGENTS_ROOT}")
    for checker in audit.DIVISIONS:
        who = audit.agent_name(checker)
        assert who != checker, f"{checker}: agent_name fell back to the key"
        assert who != audit.DIVISIONS[checker][1], (
            f"{checker}: agent_name returned the file stem {who!r}, so the "
            "frontmatter `name:` was not read")

    print("_v70: ok (%d checkers registered: %s)"
          % (len(found), ", ".join(sorted(found))))


if __name__ == "__main__":
    main()
