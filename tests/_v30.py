"""The act gate, and a ledger that cannot stay silent.

Two failures, one release apart, with the same shape.

First: `look = ""` in job.py switched the act gate off. It was a deliberate fix
for per-word gating, which had thrown away real footage of the same event three
renders running — but with the act question gone the gate only asked WHERE a
frame was shot. A mass funeral and a quiet border terminal, both genuinely in
Palestine, both the aftermath, shipped under "mereka dibantai" and "mereka
dibom". The operator: "footage dibantai dan di bom harusnya cuplikan perang
dari berita, berapa kali gw harus bilang".

Second, and the reason the first went unnoticed for a release: a gate that
rejects nothing prints nothing, so `warnings: []` on that clip was truthful and
useless. Silence from a working gate and silence from a disabled gate were the
same bytes.

So the act is asked once per clip (not per caption word), and every gate
records its verdict in a ledger that prints DID NOT RUN for gates that never
reported.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import job
import audit


def words(ws):
    return [{"word": w, "start": float(i), "end": float(i) + 0.4}
            for i, w in enumerate(ws)]


# --- the act gate decides per clip, from the speaker's own words -------------

violent = job._clip_act(words(
    "Mereka dibantai Mereka dibom Mereka diserang terus menerus".split()))
assert violent, "a clip about people being bombed must demand the act"
for must in ("strikes", "rubble", "explosions"):
    assert must in violent, f"{must!r} missing from {violent!r}"
# Phrased as footage, not as a verb to match per caption.
assert "dibantai" not in violent and "dibom" not in violent, violent

# The other half of the same clip names no violence: kiai, ulama, studying.
calm = job._clip_act(words(
    "apalagi para kiai para ulama kehendak untuk belajar sungguh".split()))
assert calm == "", f"a non-violent clip must not demand war footage: {calm!r}"

# Single word is enough, and punctuation must not hide it.
assert job._clip_act(words(["Mereka", "dibantai."])), "punctuation broke it"
# "korban berjatuhan" used to count on the strength of "korban" alone. It no
# longer does, and that was a real bug, not a loosening: Indonesian "korban" is
# the victim of anything — korban keracunan, korban banjir, korban PHK — so it
# put a school-meal poisoning clip under a war-footage veto and shipped zero
# cutaways. The violence has to be named. See _v33.
assert job._clip_act(words(["korban", "berjatuhan"])) == "", \
    "'korban' alone must not make a clip a war clip"
assert job._clip_act(words(["korban", "serangan"])), \
    "'korban' next to real violence must still count"
# A word that merely contains a violence stem is not a violence word. This is
# the censor.py trap in another costume: "bom" inside "bombardir".
assert job._clip_act(words(["serangga", "bombardir"])) == "", \
    "substring match would make every clip a war clip"
assert job._clip_act([]) == "", "empty transcript"
assert job._clip_act(None) == "", "no transcript at all"


# --- the ledger reports gates that never ran --------------------------------

led = audit.Ledger()
led.rejected("footage", "gbDzBo9w890 @110s", "off topic",
             "Israeli air force pilot")
led.rejected("footage", "zgS8aYWWArg @95s", "not the action",
             "mass funeral, aftermath")
led.passed("sourcing", "Kompas 1.35M", "verified channel")

text = led.report(checkers=("sourcing", "footage", "copy", "sound"))

# The whole point: a gate that recorded nothing is visible as not having run,
# rather than being absent from the report.
assert "copy       DID NOT RUN" in text, text
assert "sound      DID NOT RUN" in text, text
# A gate that ran and rejected everything is not confusable with one that
# never ran.
assert "footage    0 pass · 2 reject" in text, text
assert "DID NOT RUN" not in text.split("footage")[1].split("\n")[0], text
# Reasons survive to the report, since "why" is what makes a log worth reading.
assert "not the action — mass funeral, aftermath" in text, text
# Divisions come from the real roster in ~/skill-sources/agency-agents/ — this
# comment used to say that while asserting on "RESEARCH", a label no division in
# that repo defines. The labels below are from its divisions.json, and the
# report must also name the reviewing agent. _v37 holds the full contract.
assert "TESTING" in text and "MARKETING" in text, text
assert "agent: Evidence Collector" in text, text

# Counts are computed, not narrated.
ok, no, warn = led.counts("footage")
assert (ok, no, warn) == (0, 2, 0), (ok, no, warn)
ok, no, warn = led.counts()
assert (ok, no, warn) == (1, 2, 0), (ok, no, warn)

# Recording outside a render must not accumulate state: these modules are
# imported by tests and tools that never call start().
audit.stop()
audit.rejected("footage", "orphan", "no render active")
assert audit.current() is None, "module-level record leaked a ledger"

# Accepts are printed too, however many there are. Hiding them to keep the
# report short removed the one line that answers "which frame actually got
# used?" — on a real render seventeen rejects buried six accepts.
busy = audit.Ledger()
for i in range(9):
    busy.passed("sourcing", f"clip {i}", "fine")
busy.rejected("sourcing", "rally Jakarta", "off topic")
btext = busy.report(checkers=("sourcing",))
assert "9 pass · 1 reject" in btext, btext
assert "rally Jakarta" in btext, btext
assert "clip 4" in btext, btext

print("v30 ok — act gate asked per clip; silent gates are reported")
