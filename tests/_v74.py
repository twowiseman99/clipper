#!/usr/bin/env python3
"""The log must not reach into the render.

Everything in this session was supposed to touch the agency log only. One
edit did not: I rewrote `result["mood"]` from the transcript's reading to the
mood the render scored with, because the ledger header disagreed with the
music line. That key is part of the render contract -- pipeline.py picks BGM
from it -- so a log defect would have changed what music a re-render chooses.
Reverted; the header now gets `mood_used` as its own key.

This test pins the boundary so the next log fix cannot drift across it:

  * `mood` keeps the clip's own reading, `mood_used` carries what was scored.
  * The freeze gate's decision rule is untouched by the reporting rewrite:
    a frame qualifies on ok AND conf >= MIN_CONF, and the winner is the
    qualifier nearest the freeze point -- not the most confident one.
  * `summarise` is pure: handed rows, it must not look at files or clocks.

It cannot assert "the pixels are the same" -- that needs two renders and a
real measurement, done by hand this session (mean |Y| 0.5113 before-vs-after
against 0.5044 for two runs of IDENTICAL code, so the delta is encoder noise,
not an effect). What it can do is keep the decision inputs honest.
"""

import inspect
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import freeze_pick  # noqa: E402


def test_mood_stays_the_clips_own_reading():
    """`result["mood"]` is read by the pipeline, so the log cannot own it."""
    src = open(os.path.join(ROOT, "job.py"), encoding="utf-8").read()
    # The result dict the renderer returns.
    block = src[src.index('"hook": meta["hook"],'):]
    block = block[:block.index('"music":')]
    assert '"mood": meta.get("mood")' in block, (
        'result["mood"] must stay the transcript/metadata reading -- '
        "pipeline.py picks BGM from it. Put the scored mood in mood_used.")
    assert '"mood_used": _mood' in block, \
        "the scored mood must still reach the ledger, under its own key"

    # And the ledger must be handed both, or the header silently loses one.
    saved = src[src.index("led.save(path, checkers=checkers"):]
    saved = saved[:saved.index("})")]
    for key in ('"mood"', '"mood_used"'):
        assert key in saved, f"{key} missing from the ledger meta"


def test_pipeline_still_reads_the_clips_mood():
    """The consumer that made this a render concern, not a log one."""
    src = open(os.path.join(ROOT, "pipeline.py"), encoding="utf-8").read()
    assert 'bgm_lib.pick(meta.get("mood")' in src, (
        "pipeline.py no longer picks BGM from meta['mood'] -- re-check "
        "whether the mood keys still need to be kept apart")


def test_freeze_decision_rule_is_unchanged():
    """Reporting was rewritten around the gate; the gate itself was not."""
    rows = [
        # (t, ok, conf, read)
        (140.0, True, 0.99, "subject, frontal"),   # best conf, far away
        (148.8, True, 0.60, "subject, frontal"),   # nearest qualifier
        (149.0, True, 0.40, "subject, frontal"),   # nearer but under floor
        (149.1, False, 0.99, "somebody else"),     # confident reject
    ]
    s = freeze_pick.summarise(rows, 149.0)
    assert s["qualified"] == 2, s
    # Nearest qualifier wins, NOT the most confident one: the still should
    # look like the picture stopping, not like a cut elsewhere.
    assert s["picked"] == 148.8, (
        f"picked {s['picked']}, expected the nearest qualifier 148.8")
    # A frame under the floor never qualifies even when it is nearer.
    assert s["best_conf"] >= freeze_pick.MIN_CONF, s

    # Threshold constants are still what the gate reads, not copies.
    assert s["min_conf"] == freeze_pick.MIN_CONF, s


def test_summarise_is_pure():
    """A reporting helper must not touch the disk or the clock.

    write_debug does the I/O and returns "" on failure so diagnostics can
    never fail a render; summarise just counts.
    """
    body = inspect.getsource(freeze_pick.summarise)
    for forbidden in ("open(", "os.", "datetime", "json.", "subprocess"):
        assert forbidden not in body, \
            f"summarise touches {forbidden!r} -- it must stay pure"


def test_debug_writer_cannot_fail_a_render():
    body = inspect.getsource(freeze_pick.write_debug)
    assert "except Exception" in body and 'return ""' in body, \
        "write_debug must swallow its own failure and return an empty path"
    # Proof, not just a source read: an unwritable directory returns "".
    got = freeze_pick.write_debug([(1.0, True, 0.9, "x")], {"render_id": "r"},
                                  directory="/proc/nope/nowhere")
    assert got == "", f"expected '' for an unwritable dir, got {got!r}"


def test_log_modules_are_not_imported_by_the_renderer():
    """edit.py composes pixels; it must not depend on the logging layer."""
    src = open(os.path.join(ROOT, "edit.py"), encoding="utf-8").read()
    head = src[:src.index("def ")] if "def " in src else src
    for mod in ("audit_fmt", "audit_watch"):
        assert not re.search(rf"^\s*import {mod}\b", head, re.M), \
            f"edit.py imports {mod} -- the log is leaking into the render"


def main():
    test_mood_stays_the_clips_own_reading()
    test_pipeline_still_reads_the_clips_mood()
    test_freeze_decision_rule_is_unchanged()
    test_summarise_is_pure()
    test_debug_writer_cannot_fail_a_render()
    test_log_modules_are_not_imported_by_the_renderer()
    print("_v74: ok (the log layer stays out of the render contract)")


if __name__ == "__main__":
    main()
