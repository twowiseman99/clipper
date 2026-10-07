"""The camera settles, and it stops before the ending.

Operator, on the sombre preset: "Tpi kok hooknya hilang dan videonya masi goyang
ya di preset sedih?"

Two separate things, and only the second is a code bug — the missing hook was me
omitting --hook from the render command, nothing in the renderer.

The movement was real. Measured on the delivered 45s sedih render against a fair
control (same pillar card, same scales, window frozen, no effects):

    static window   >3px 50.5%   hard throws 4.68/s
    the pan set     >3px 58.7%   hard throws 8.43/s

`flash: False` in the preset only turns off the exposure flicker. PAN is not a
preset field at all, so the sombre cut inherited the same reframing as jamet —
and because moves are triggered per face-sample, a 45s clip collected more of
them than a 28s one: slides at 24-26s, 33-35s and 36-38s.

Two faults behind that:

1. The only spacing rule was `t <= keys[-1][0]`, which stops a move starting
   before the previous one LANDS. A 1.0s gap passed, so the camera never read as
   settled. PAN_GAP is now a real quiet period between slides.

2. Nothing stopped a pan running into the outro. The 36-38s slide overlapped an
   ending that starts at 37.0s, so the desaturation ramp and the reframe were
   fighting over the same seconds. A reframe is framing for SPEECH; once the
   ending has begun there is no speech left to follow.

This test drives _pan_keys directly with a synthetic track, so it needs no
footage and no network.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import edit  # noqa: E402

# A subject that jumps between two positions every 4s, sampled twice a second.
# Enough to request a move far more often than the camera should grant one.
PTS = [(t / 2.0, 0.30 + 0.45 * ((t // 8) % 2)) for t in range(0, 90)]
WIN = 0.42
OUTRO_AT = 37.0

_gap = edit.PAN_GAP
try:
    # --- 1. without a gap the camera moves constantly -----------------------
    edit.PAN_GAP = 0.0
    loose = edit._pan_keys(PTS, WIN)
    edit.PAN_GAP = _gap
    tight = edit._pan_keys(PTS, WIN)

    assert len(loose) > len(tight), (
        "PAN_GAP did not reduce the number of camera moves (%d vs %d): the "
        "spacing rule is not being applied"
        % (len(loose), len(tight)))

    # --- 2. every slide is separated by a real quiet period -----------------
    # keys come in pairs: (start, held position), (start+slide, new position).
    # So the gap to check is between one pair's END and the next pair's START.
    starts = [t for t, _ in tight[1::2]]
    ends = [t for t, _ in tight[2::2]]
    for i, nxt in enumerate(starts[1:]):
        prev_end = ends[i]
        assert nxt >= prev_end + edit.PAN_GAP - 0.01, (
            "two reframes %.2fs apart (%.2f -> %.2f), under PAN_GAP=%.1f: the "
            "camera never settles" % (nxt - prev_end, prev_end, nxt,
                                      edit.PAN_GAP))

    # --- 3. no slide crosses into the ending -------------------------------
    bounded = edit._pan_keys(PTS, WIN, pan_until=OUTRO_AT)
    assert bounded, "pan_until removed every keyframe"
    for t, _x in bounded:
        assert t <= OUTRO_AT + 0.01, (
            "a pan keyframe sits at %.2fs, past the %.2fs outro start: the "
            "reframe and the ramp are fighting over the same seconds"
            % (t, OUTRO_AT))
    assert len(bounded) < len(tight), (
        "pan_until did not drop the slide that ran into the ending (%d keys "
        "either way)" % len(tight))

    # --- 4. the subject is still followed ----------------------------------
    # Fewer moves must not mean a frozen window: that trade was measured at
    # 56% of the clip with the subject outside the frame, which is worse than
    # the movement being fixed here.
    assert len(bounded) >= 3, (
        "only %d keyframes left: the window is effectively static, and a fixed "
        "window put the subject outside the frame 56%% of the time"
        % len(bounded))
    span = max(x for _t, x in bounded) - min(x for _t, x in bounded)
    assert span > 0.05, (
        "the window only travels %.3f of the frame width: it is not tracking "
        "the subject at all" % span)

    print("_v57 ok — PAN_GAP=%.1f cuts %d keyframes to %d, pan_until=%.1f "
          "drops the slide that crossed the ending (%d keys), window still "
          "travels %.2f of frame width"
          % (edit.PAN_GAP, len(loose), len(tight), OUTRO_AT, len(bounded),
             span))
finally:
    edit.PAN_GAP = _gap
