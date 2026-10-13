"""Project provenance on a render ledger.

The operator runs more than one product through this pipeline (Clipper and
YouTube Automation, each with its own vault note), so a channel full of
ledgers has to answer "which product" before anything else.

What this pins, and why each one is a property rather than a number:

1. The project line sits ABOVE the clip title. That is the request: the
   first question is which product, not which clip.
2. A ledger with NO project field renders with no project line at all. The
   ~70 ledgers already on disk predate the field and genuinely do not know
   which project they came from. Printing a placeholder there would teach a
   reader to trust a field that is sometimes a guess, which is the same
   failure as a gate that records nothing and reads as a pass.
3. Empty or whitespace-only is treated as absent, not printed as an empty
   label.
4. project_name() prefers CLIPPER_PROJECT, so a second project reusing this
   pipeline sets one variable. Without it the repo directory name is used:
   a fact about where the code ran, not an assumption about intent.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import audit
import audit_fmt


def _ledger(**extra):
    d = {"title": "Judul Klip", "clip": "/x/clip_9.mp4", "entries": [],
         "totals": {"pass": 0, "reject": 0, "warn": 0}}
    d.update(extra)
    return d


def test_project_sits_above_the_clip_title():
    lines = audit_fmt.format_ledger(_ledger(project="Clipper"),
                                    checkers=()).splitlines()
    assert "Clipper" in lines[0], lines[:2]
    assert "Judul Klip" in lines[1], lines[:2]


def test_missing_project_prints_no_project_line():
    """A ledger that does not know its project must not claim one."""
    lines = audit_fmt.format_ledger(_ledger(), checkers=()).splitlines()
    assert "Judul Klip" in lines[0], lines[:2]
    assert not any("\U0001F4C1" in l for l in lines[:3]), lines[:3]


def test_blank_project_is_treated_as_absent():
    for blank in ("", "   ", None):
        lines = audit_fmt.format_ledger(_ledger(project=blank),
                                        checkers=()).splitlines()
        assert "Judul Klip" in lines[0], (blank, lines[:2])


def test_env_overrides_directory():
    before = os.environ.get("CLIPPER_PROJECT")
    try:
        os.environ["CLIPPER_PROJECT"] = "YouTube Automation"
        assert audit.project_name() == "YouTube Automation"
    finally:
        if before is None:
            os.environ.pop("CLIPPER_PROJECT", None)
        else:
            os.environ["CLIPPER_PROJECT"] = before


def test_directory_name_used_without_env():
    before = os.environ.pop("CLIPPER_PROJECT", None)
    try:
        # audit.py lives in the clipper repo, so the fallback must resolve
        # through PROJECTS rather than returning a raw directory name.
        assert audit.project_name() == "Clipper"
    finally:
        if before is not None:
            os.environ["CLIPPER_PROJECT"] = before


def test_job_passes_project_into_the_ledger():
    """The field has to be PLUMBED, not just available.

    Same class as the _v67 portrait check: a helper that exists but is never
    called looks identical to a working feature until you read the output.
    """
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "job.py")).read()
    assert '"project": audit.project_name()' in src


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as exc:
                fails += 1
                print(f"FAIL {name}: {exc}")
    print(f"_v78 {'ok' if not fails else f'{fails} FAIL'}")
    sys.exit(1 if fails else 0)
