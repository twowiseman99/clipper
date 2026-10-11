#!/usr/bin/env python3
"""Printing is not delivering, and a delivery job that cannot deliver must fail.

The operator asked "kok gajalan lognya?" after a day of the cron job reporting
ok every 15 minutes into an empty channel. Both halves of that were my bug:

  1. `run_once` marked a ledger `sent` whether it was POSTED or merely printed.
     With no webhook configured, one cron run consumed all 70 ledgers to a
     stdout nobody reads. `sent` is permanent, so configuring the webhook
     afterwards would have delivered NOTHING -- the backlog was already
     "delivered".

  2. The missing webhook was reported on stderr and the process exited 0, so
     the scheduler showed success. A watchdog that cannot fail is worse than no
     watchdog: it actively tells you the silence is fine.

This is the same family as the fail-silent traps already in this codebase -- a
silent fallback is a bug even when the command succeeds -- and the same shape
as the audit ledger's own "DID NOT RUN" rule, which exists because a gate that
records nothing reads as a gate that passed.

Measured before the fix: with no webhook, run 1 printed 3211 characters and
wrote {"sent": ["render5.audit.json"]}; run 2 WITH a webhook delivered 0.
"""

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PY = os.path.join(ROOT, ".venv", "bin", "python")
WATCH = os.path.join(ROOT, "audit_watch.py")
LEDGER = {
    "title": "T", "duration_sec": 28.0, "clip": "/tmp/x/render9.mp4",
    "totals": {"pass": 1, "reject": 1, "warn": 0},
    "entries": [
        {"checker": "freeze", "verdict": "reject", "target": "pick",
         "reason": "no qualifying frame", "detail": ""},
        {"checker": "copy", "verdict": "pass", "target": "risky words",
         "reason": "none found", "detail": ""},
    ],
    "warnings": ["gambar penutup: ga ada frame | stage: freeze"
                 " | error: no qualifying frame | debug: /tmp/x.json"],
}


def _run(jobs, state, webhook):
    env = dict(os.environ)
    env["CLIPPER_JOBS"] = jobs
    env["AUDIT_WATCH_STATE"] = state
    env["AUDIT_WEBHOOK"] = webhook
    env.pop("AUDIT_NARRATE", None)  # keep the test off the router
    p = subprocess.run([PY, WATCH, "--once"], capture_output=True, text=True,
                       env=env, cwd=ROOT)
    return p


def _fixture(tmp):
    jobs = os.path.join(tmp, "jobs")
    os.makedirs(jobs, exist_ok=True)
    with open(os.path.join(jobs, "render9.audit.json"), "w") as fh:
        json.dump(LEDGER, fh)
    return jobs, os.path.join(tmp, "state.json")


def test_no_webhook_exits_nonzero_and_says_why():
    with tempfile.TemporaryDirectory() as tmp:
        jobs, state = _fixture(tmp)
        p = _run(jobs, state, "")
        assert p.returncode != 0, \
            "a delivery job with nowhere to deliver must FAIL, not report ok"
        assert "AUDIT_WEBHOOK" in p.stderr, \
            f"the failure must name what is missing:\n{p.stderr}"
        assert "/home/ubuntu/.hermes/audit-watch/webhook" in p.stderr, \
            f"the failure must name the file to create:\n{p.stderr}"


def test_printing_does_not_consume_the_backlog():
    """The cost of the original bug: an undeliverable run ate 70 ledgers."""
    with tempfile.TemporaryDirectory() as tmp:
        jobs, state = _fixture(tmp)
        _run(jobs, state, "")
        if os.path.exists(state):
            marked = json.load(open(state)).get("sent", [])
            assert "render9.audit.json" not in marked, \
                ("printing marked the ledger delivered -- configuring the "
                 "webhook later would deliver nothing")
        # And the ledger is still pending, so a later configured run sends it.
        import audit_watch
        audit_watch.JOBS = __import__("pathlib").Path(jobs)
        audit_watch.STATE = __import__("pathlib").Path(state)
        assert len(audit_watch.pending(audit_watch.load_state())) == 1, \
            "the undelivered ledger must stay in the queue"


def test_a_real_post_does_mark_it_sent():
    """The guard must not break the working path: a POSTED ledger is recorded.

    Without this, "never mark as sent" would pass the test above and re-post
    every ledger forever -- which is the flood this whole effort removed.
    """
    import pathlib

    import audit_watch
    with tempfile.TemporaryDirectory() as tmp:
        jobs, state = _fixture(tmp)
        audit_watch.JOBS = pathlib.Path(jobs)
        audit_watch.STATE = pathlib.Path(state)
        posted = []
        real = audit_watch.post
        audit_watch.post = lambda hook, text: posted.append(text)
        try:
            n = audit_watch.run_once("https://example.invalid/hook")
        finally:
            audit_watch.post = real
        assert n == 1 and len(posted) == 1, f"expected one post, got {posted}"
        marked = json.load(open(state)).get("sent", [])
        assert "render9.audit.json" in marked, \
            "a delivered ledger must be recorded or it ships again next run"
        # Idempotent: the second run is silent.
        posted.clear()
        assert audit_watch.run_once("https://example.invalid/hook") == 0
        assert not posted, "a delivered ledger was posted twice"


def test_the_wrapper_refuses_to_run_without_a_webhook_file():
    sh = "/home/ubuntu/.hermes/scripts/audit_watch.sh"
    if not os.path.exists(sh):
        print("  (wrapper not on this box, skipped)")
        return
    src = open(sh, encoding="utf-8").read()
    assert "-s \"$WEBHOOK_FILE\"" in src or "-s $WEBHOOK_FILE" in src, \
        "the wrapper must test the webhook file is NON-EMPTY, not just present"
    assert "exit 1" in src, \
        "a missing webhook must fail the cron run, not pass quietly"


def main():
    test_no_webhook_exits_nonzero_and_says_why()
    test_printing_does_not_consume_the_backlog()
    test_a_real_post_does_mark_it_sent()
    test_the_wrapper_refuses_to_run_without_a_webhook_file()
    print("_v76: ok (printing is not delivering; undeliverable runs fail loud)")


if __name__ == "__main__":
    main()
