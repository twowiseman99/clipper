"""The hook can start at a chosen second of the opening file.

Operator: "Pas hook coba pakai scene lain, contoh <link> / di video ini cari
scene gibran, rulenya sama pas hook di mute"

The opening path existed already (`--opening`), but it always took the file's
FIRST frames. On a 220s ceremony reel that is the wrong 7 seconds: measured with
the repo's own vision gate, Gibran is identifiable for 4.5s of it (125.5-130.0s)
and the opening frames are a military officer and Megawati.

So `--opening-start` is a seek applied to the input, `-ss` placed BEFORE `-i`.
The ordering matters for the same reason the `loop`/`fps` bug mattered: an
option after `-i` applies to the output, and the seek would silently do nothing.

Mute is unchanged and already correct — CLIPPER_MUTE_BROLL_HOOK defaults to on,
so the opening footage's own audio never reaches the mix. This test pins that
too, because "the rule is the same" means it must not regress when the hook
footage becomes interesting enough to have usable sound.
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import edit  # noqa: E402
import job  # noqa: E402

# --- 1. the parameter exists end to end --------------------------------------
rc = inspect.signature(edit.render_clip).parameters
rn = inspect.signature(job.run).parameters
assert "intro_start" in rc, "edit.render_clip has no intro_start parameter"
assert "opening_start" in rn, "job.run has no opening_start parameter"

# --- 2. the CLI accepts it and passes it on ----------------------------------
# argparse turns --opening-start into a.opening_start; the call site must read
# it. A flag parsed and then dropped is the failure mode this guards.
src = open(os.path.join(os.path.dirname(__file__), "..", "job.py")).read()
assert "--opening-start" in src, "job.py does not declare --opening-start"
assert "opening_start=a.opening_start" in src, (
    "job.py parses --opening-start but never passes it to run(): the flag is "
    "accepted and silently ignored")
assert "intro_start=opening_start" in src, (
    "job.run never forwards opening_start to render_clip")

esrc = open(os.path.join(os.path.dirname(__file__), "..", "edit.py")).read()
assert "intro_start=a.intro_start" in esrc, (
    "edit.py's own CLI parses --intro-start but never passes it on")

# --- 3. the seek is applied to the INPUT, not the output ---------------------
i_intro = esrc.find('"-i", os.path.abspath(intro)')
assert i_intro > 0, "could not find the intro input in edit.py"
window = esrc[max(0, i_intro - 500):i_intro]
assert 'if intro_start:' in window, (
    "intro_start is not used where the intro input is opened")
i_ss = window.rfind('"-ss"')
i_loop = window.rfind('"-stream_loop"')
assert i_ss > 0, "no -ss emitted for the intro input"
assert i_ss < i_loop, (
    "-ss is emitted after -stream_loop/-t for the intro: an input option "
    "placed after -i applies to the output and the seek does nothing")

# --- 4. the hook stays muted -------------------------------------------------
assert edit.BGM_MUTE_BROLL_HOOK, (
    "CLIPPER_MUTE_BROLL_HOOK defaults to off: the opening footage's own audio "
    "would play under the hook")
i_guard = esrc.find("if intro_idx is not None and not BGM_MUTE_BROLL_HOOK")
assert i_guard > 0, "the hook-audio guard is gone"
i_use = esrc.find("[aintro]")
assert i_use > i_guard, (
    "the intro audio chain is built outside the mute guard")

# --- 5. a local file is accepted as the opening ------------------------------
# The verified hook is a trimmed cut on disk, not a link. Routing it back
# through the downloader would discard the frame-by-frame check that produced
# it, and classify_source calls an unknown scheme unsupported.
import tempfile  # noqa: E402

assert "if os.path.exists(url):" in src, (
    "job._fetch_one does not accept a local path: a verified hook cut cannot "
    "be passed as --opening")
i_exists = src.find("if os.path.exists(url):")
i_classify = src.find("kind = fetch.classify_source(url)")
assert 0 < i_exists < i_classify, (
    "the local-path branch runs after classify_source, which already raised "
    "on a plain path")

with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fh:
    fh.write(b"not really a video")
    probe = fh.name
try:
    got = job._fetch_one(probe, "opening")
    assert got == os.path.abspath(probe), (
        "a local path was not returned as-is: got %r" % (got,))
finally:
    os.unlink(probe)

print("_v58 ok — intro_start reaches render_clip and job.run, both CLIs pass it "
      "on, -ss precedes -stream_loop/-i so the seek applies to the input, a "
      "local file is accepted as the opening, and the hook audio stays muted "
      "(BGM_MUTE_BROLL_HOOK=%s)" % edit.BGM_MUTE_BROLL_HOOK)
