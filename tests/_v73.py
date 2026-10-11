#!/usr/bin/env python3
"""A reported number must be comparable to the threshold it is compared to.

The freeze summary reported `best_conf` as max() over EVERY judged frame.
But `confidence` is the model's confidence in its own reading, not a score
for the subject: on a frame it rejected, 0.95 means "certain this is somebody
else". A real render printed

    trigger : conf terbaik 0,95 vs ambang 0,55
    error   : no qualifying frame

which states a number ABOVE the floor as the reason nothing cleared the
floor, drawn from the frame the gate was most sure to throw away. A reader
checking the gate would conclude the threshold logic was inverted.

Only confidences on frames that READ AS THE SUBJECT are on the same scale as
MIN_CONF. When none do, there is no comparable number and the summary has to
say that instead of producing one.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import freeze_pick  # noqa: E402


def rows(specs):
    """[(t, ok, conf, read)] from [(ok, conf)]."""
    return [(144.0 + i * 0.2, ok, conf, "someone (profile / blurred)")
            for i, (ok, conf) in enumerate(specs)]


def test_rejected_confidence_is_not_reported_as_best():
    # The shape from the real render: high confidence, all of it on frames the
    # gate rejected.
    s = freeze_pick.summarise(rows([(False, 0.95), (False, 0.78),
                                    (False, 0.72)]), 145.0)
    assert s["qualified"] == 0, s
    assert s["best_conf"] == 0.0, \
        f"best_conf {s['best_conf']} came from a rejected frame"
    assert abs(s["best_conf_rejected"] - 0.95) < 1e-9, s

    # A number that IS comparable: a frame read as the subject but under the
    # floor. That is the genuine "close but not enough" case and must survive.
    s = freeze_pick.summarise(rows([(True, 0.48), (False, 0.95)]), 144.0)
    assert s["qualified"] == 0, s
    assert abs(s["best_conf"] - 0.48) < 1e-9, s
    assert s["best_conf"] < s["min_conf"], s


def test_reported_number_never_contradicts_the_verdict():
    """Whatever is reported as best must be below the floor on a reject."""
    cases = [
        [(False, 0.95), (False, 0.90)],            # nothing read as subject
        [(True, 0.48), (False, 0.99)],             # one close, under floor
        [(True, 0.10), (True, 0.54), (False, 1.0)],  # several, all under
    ]
    for spec in cases:
        s = freeze_pick.summarise(rows(spec), 144.0)
        assert s["qualified"] == 0, (spec, s)
        assert s["best_conf"] < s["min_conf"], (
            "reject reports conf terbaik %.2f against a %.2f floor: %r"
            % (s["best_conf"], s["min_conf"], spec))


def test_pass_reports_a_qualifying_frames_confidence():
    s = freeze_pick.summarise(rows([(False, 0.99), (True, 0.82)]), 144.2)
    assert s["qualified"] == 1, s
    assert abs(s["best_conf"] - 0.82) < 1e-9, \
        f"pass reported {s['best_conf']}, not the qualifying frame's 0.82"
    assert s["best_conf"] >= s["min_conf"], s


def test_job_phrases_the_untested_threshold_honestly():
    """With no comparable number, job.py must not print a comparison."""
    import re
    src = open(os.path.join(ROOT, "job.py"), encoding="utf-8").read()
    # The reject branch has to branch on best_conf before claiming a
    # comparison; a single unconditional "conf terbaik X < ambang Y" is the
    # bug.
    block = src[src.index("gambar penutup: ga ada frame yang jelas"):]
    block = block[:block.index("else:")]
    assert "if _fsum[\"best_conf\"]" in block or \
           "if _fsum['best_conf']" in block, \
        "job.py prints a confidence comparison unconditionally"
    assert "ga pernah diuji" in block, \
        "no wording for the case where nothing read as the subject"
    assert not re.search(r"best_conf_rejected", block), \
        "the rejected-frame confidence must not be offered as the trigger"


def main():
    test_rejected_confidence_is_not_reported_as_best()
    test_reported_number_never_contradicts_the_verdict()
    test_pass_reports_a_qualifying_frames_confidence()
    test_job_phrases_the_untested_threshold_honestly()
    print("_v73: ok (reported confidence is comparable to the threshold)")


if __name__ == "__main__":
    main()
