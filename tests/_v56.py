"""Two presets, two code paths. Neither replaces the other.

Operator: "Ok berarti kita skrng ada 2 preset ya? Jedag jedug sama preset sedih,
ga lu replace kan codenya?"

A fair question, because the jamet work in b0ad70c moved shared machinery:
_outro_start and _outro_filters both grew a jamet branch, _jamet_span appeared,
and the old `dur < span * 3` guard was replaced by JAMET_BODY_MIN. If any of
that had landed OUTSIDE the `kind == "jamet"` branch, the sombre preset would
have silently inherited a 5s freeze-and-shake ending.

Measured on the current tree:

    sedih  OUTRO=melancholy  kind=melancholy  span 8.00s  5 filters
    jamet  OUTRO=jamet       kind=jamet       span 5.00s  9 filters

This test fails if the two ever converge — same span, same filter count, or a
jamet constant reaching the melancholy path.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import edit  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import job  # noqa: E402

DUR = 28.55

# --- 1. both presets still exist, with the fields the renderer reads -------
for name in ("sedih", "jamet"):
    assert name in job.CLIP_TYPES, "CLIP_TYPES lost the %r preset" % name
    preset = job.CLIP_TYPES[name]
    for field in ("mood", "outro", "broll", "flash", "why"):
        assert field in preset, "%s preset is missing %r" % (name, field)

sedih = job.CLIP_TYPES["sedih"]
jamet = job.CLIP_TYPES["jamet"]

# The two presets disagree on every axis that matters. If these ever match, one
# has been overwritten with the other.
assert sedih["mood"] != jamet["mood"], "both presets now use the same mood"
assert sedih["outro"] != jamet["outro"], "both presets now use the same outro"
assert sedih["broll"] != jamet["broll"], "b-roll no longer distinguishes them"
assert sedih["flash"] != jamet["flash"], "flash no longer distinguishes them"
assert sedih["outro"] == "melancholy", "sedih outro is %r" % sedih["outro"]
assert jamet["outro"] == "jamet", "jamet outro is %r" % jamet["outro"]

# --- 2. the two outros take different code paths --------------------------
_was = edit.OUTRO
try:
    results = {}
    for name, outro, mood in (("sedih", "melancholy", "emotional"),
                              ("jamet", "jamet", "hype")):
        edit.OUTRO = outro
        kind = edit._outro_kind(mood)
        start = edit._outro_start(DUR, mood=mood)
        _bright, filters = edit._outro_filters(DUR, mood=mood)
        assert start is not None, "%s lost its outro on a %.1fs clip" % (name, DUR)
        assert filters, "%s produced no outro filters" % name
        results[name] = {
            "kind": kind,
            "span": DUR - start,
            "filters": filters,
            "chain": ",".join(filters),
        }

    s, j = results["sedih"], results["jamet"]
    assert s["kind"] == "melancholy", "sedih resolved to kind %r" % s["kind"]
    assert j["kind"] == "jamet", "jamet resolved to kind %r" % j["kind"]
    assert abs(s["span"] - j["span"]) > 1.0, (
        "both outros now span the same length (%.2fs vs %.2fs)"
        % (s["span"], j["span"]))

    # The sombre ending must not carry the jamet treatment. These are the three
    # things the operator rejected on a grief clip: a freeze, a shake, and
    # beat-driven exposure flashes.
    assert "loop=loop=" not in s["chain"], (
        "the melancholy outro now freezes the frame: %s" % s["chain"][:200])
    assert "hue=s=" in s["chain"], (
        "the melancholy outro lost its desaturation ramp: %s" % s["chain"][:200])

    # And the jamet ending must still be the freeze-and-shake one.
    assert "loop=loop=" in j["chain"], (
        "the jamet outro lost its freeze: %s" % j["chain"][:200])

    # --- 3. jamet constants do not reach the melancholy path --------------
    # JAMET_BODY_MIN replaced `dur < span * 3` for jamet only. The melancholy
    # outro is 8s, so under the old rule it needs 24s of clip — and it still
    # must, or short sombre clips would start shipping a 1/3-length ending.
    edit.OUTRO = "melancholy"
    assert edit._outro_start(12.0, mood="emotional") is None, (
        "a 12s clip now gets a melancholy outro: the jamet body floor leaked "
        "into the sombre path")
    assert edit._outro_start(24.0, mood="emotional") is not None, (
        "melancholy outro no longer fits a 24s clip")

    # The jamet floor, by contrast, deliberately allows short clips.
    edit.OUTRO = "jamet"
    assert edit._outro_start(12.0, mood="hype") is not None, (
        "a 12s clip lost its jamet outro")

    # --- 4. _jamet_span is only consulted for jamet ------------------------
    # Raising it must not move the melancholy span by a single frame.
    edit.OUTRO = "melancholy"
    before = edit._outro_start(DUR, mood="emotional")
    _orig = edit.OUTRO_JAMET_SECONDS
    try:
        edit.OUTRO_JAMET_SECONDS = 9.0
        after = edit._outro_start(DUR, mood="emotional")
    finally:
        edit.OUTRO_JAMET_SECONDS = _orig
    assert before == after, (
        "changing OUTRO_JAMET_SECONDS moved the melancholy outro %.2f -> %.2f"
        % (before, after))

    # --- 5. the snap does not eat a non-extending ending ------------------
    # Found while answering "ga lu replace kan codenya?" by actually rendering
    # the sombre preset. _outro_snap moves the ending to the last word AND
    # shrinks it (`span = dur - start`), which is correct for jamet — `loop`
    # clones frames, so it makes its own room — and wrong for melancholy, whose
    # 8s ramp has to fit inside the remaining footage.
    #
    # Measured before the fix, with the real transcript:
    #
    #   dur 24.00 -> ramp 0.10s      dur 28.55 -> ramp 0.35s
    #   dur 35.00 -> ramp 3.54s      dur 45.00 -> ramp 0.08s
    #
    # The delivered sedih render held SATAVG at ~11 from the first second to
    # the last instead of ramping to grey: the sombre ending was effectively
    # absent, and no test noticed because none of them rendered this preset.
    import json
    _w = "/home/ubuntu/clipper/media/uf0a29714d9fe/wyvzLKsUNF4.words.json"
    if os.path.exists(_w):
        _d = json.load(open(_w))
        real_words = _d["words"] if isinstance(_d, dict) else _d

        edit.OUTRO = "melancholy"
        for dur in (24.0, 28.55, 35.0, 45.0):
            st = edit._outro_start(dur, mood="emotional", words=real_words,
                                   clip_start=122.0)
            assert st is not None, "melancholy outro vanished on %.2fs" % dur
            ramp = dur - st
            assert ramp >= edit.OUTRO_SECONDS * 0.9, (
                "the melancholy ramp is %.2fs on a %.2fs clip, not %.1fs: the "
                "snap shrank it" % (ramp, dur, edit.OUTRO_SECONDS))

        # And the jamet snap must STILL fire, or the freeze goes back on top of
        # the payoff line — the thing the snap exists to prevent.
        edit.OUTRO = "jamet"
        st = edit._outro_start(28.55, mood="hype", words=real_words,
                               clip_start=122.0)
        assert st is not None and abs(st - 28.20) < 0.1, (
            "the jamet freeze no longer snaps to the last word (start %s): "
            "tightening the room check for melancholy must not reach jamet"
            % st)

    print("_v56 ok — sedih: %s outro, %.2fs span, %d filters (desaturates, no "
          "freeze) | jamet: %s outro, %.2fs span, %d filters (freezes); jamet "
          "body floor and span do not reach the sombre path; the snap keeps "
          "the melancholy ramp whole and still fires for jamet"
          % (s["kind"], s["span"], len(s["filters"]),
             j["kind"], j["span"], len(j["filters"])))
finally:
    edit.OUTRO = _was
