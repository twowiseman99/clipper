#!/usr/bin/env python3
"""A ledger already posted is never posted twice, even when a batch dies.

The happy path was already idempotent: run twice, the second run is silent.
What was not idempotent was a batch that failed partway. `save_state` sat
AFTER the loop, so a webhook error on ledger 2 of 2 skipped it entirely and
the next run re-posted the one already delivered. Measured before the fix:
ledger 1 posted, HTTP 500 on ledger 2, next run sent 2.

Nothing here touches the network — `post` is replaced with a stub that counts
calls and can be told which call to fail.
"""

import importlib
import json
import os
import pathlib
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

LEDGER = {
    "title": "Judul", "clip": "/x/clip_1.mp4",
    "totals": {"pass": 1, "reject": 0, "warn": 0},
    "duration_sec": 20.0, "mood": "emotional", "warnings": [],
    "entries": [{"checker": "language", "target": "transcript review",
                 "verdict": "pass", "reason": "no mishearings found",
                 "detail": ""}],
}


def fresh(tmp, n_ledgers):
    jobs = pathlib.Path(tmp, "jobs")
    jobs.mkdir(parents=True, exist_ok=True)
    for i in range(n_ledgers):
        d = dict(LEDGER, clip=f"/x/clip_{i}.mp4", title=f"Judul {i}")
        pathlib.Path(jobs, f"clip_{i}.audit.json").write_text(
            json.dumps(d), encoding="utf-8")
    state = pathlib.Path(tmp, "state", "s.json")
    os.environ["CLIPPER_JOBS"] = str(jobs)
    os.environ["AUDIT_WATCH_STATE"] = str(state)
    import audit_watch
    importlib.reload(audit_watch)
    return audit_watch, state


def stub(mod, fail_on=None):
    """Replace post() with a counter. Returns the list of posted titles."""
    posted = []

    def fake(webhook, text):
        posted.append(text.split("\n")[0])
        if fail_on is not None and len(posted) == fail_on:
            raise RuntimeError("webhook HTTP 500")

    mod.post = fake
    return posted


def main():
    tmp = tempfile.mkdtemp(prefix="v69-")
    try:
        # --- the happy path stays idempotent over many runs ----------------
        mod, _ = fresh(tmp, 3)
        posted = stub(mod)
        assert mod.run_once("https://fake") == 3, "first run must send all 3"
        for i in range(10):
            assert mod.run_once("https://fake") == 0, f"run {i + 2} re-sent"
        assert len(posted) == 3, f"10 further runs posted {len(posted)}"

        # --- a batch that dies partway must not re-send what it delivered --
        shutil.rmtree(tmp)
        mod, state = fresh(tmp, 3)
        posted = stub(mod, fail_on=2)
        try:
            mod.run_once("https://fake")
        except RuntimeError:
            pass
        else:
            raise AssertionError("stub was supposed to raise")

        # Ledger 1 was delivered; ledger 2 raised. The state must already
        # record the delivered one, which means it was written DURING the
        # loop and not after it.
        assert state.exists(), \
            "state was never written, so the next run re-posts everything"
        sent = json.loads(state.read_text())["sent"]
        assert len(sent) == 1, f"expected 1 ledger marked sent, got {sent}"

        # The retry sends the two that never made it, and not the first.
        again = stub(mod)
        n = mod.run_once("https://fake")
        assert n == 2, f"retry sent {n}, expected the 2 undelivered"
        assert len(again) == 2, again
        first_title = posted[0]
        assert first_title not in again, \
            f"already-delivered ledger was posted again: {first_title}"

        print("_v69: ok (10 runs -> 3 posts; failed batch retries 2, not 3)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
