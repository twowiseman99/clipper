"""One ledger for every gate that can reject something, printed as a report.

Clipper has a dozen checks spread over six modules: title credibility, frame
vision, the act gate, censor masking, the emoji/flag rule, BGM mood clash. Each
one printed its own line in its own wording, interleaved with downloads and
ffmpeg chatter, so reading a render meant grepping. Worse, a check that found
nothing printed nothing — silence looked identical to "did not run", which is
how `warnings: []` got trusted on a clip whose cutaways were never gated.

So every check reports here instead: who checked, what it looked at, the
verdict, and why. A check with zero rejections still shows up with a count, so
"this gate ran and passed everything" is distinguishable from "this gate never
ran". That difference is the whole point.

Divisions are named after the roster in ~/skill-sources/agency-agents/ so the
report reads like the company reviewing the clip rather than a debug dump.
"""

import os
import sys

# Division labels. Keyed by the checker name a module registers under.
DIVISIONS = {
    "sourcing": "RESEARCH",     # which videos may be used at all
    "footage": "RESEARCH",      # which frames inside a video may be used
    "copy": "MARKETING",        # hook, title, description
    "language": "SPECIALIZED",  # transcript review, Indonesian
    "sound": "DESIGN",          # music mood
    "edit": "ENGINEERING",      # render-level facts
}

PASS = "pass"
REJECT = "reject"
WARN = "warn"
# What a checker was GIVEN, as opposed to what it decided. The operator asked
# to see "apa yg lu kasih ke agent-agent kita dan hasilnya gimana", and the
# ledger could only answer the second half: a gate that rejected everything
# looked identical whether it had been handed a good question or a fifteen-word
# sentence no frame could satisfy. That actually happened — an eleven-word
# subject produced 35 rejects and zero cutaways, and the brief was invisible.
BRIEF = "brief"


class Ledger:
    """Collects verdicts during a render, then prints them as one report.

    Not a logger: entries are kept so the summary can count them. `rejected`
    exists because a caller usually wants its own count back ("8 windows
    refused") without walking the list.
    """

    def __init__(self, stream=None):
        self.entries = []
        self._stream = stream or sys.stderr

    def record(self, checker, target, verdict, reason="", detail=""):
        self.entries.append({
            "checker": str(checker),
            "target": str(target),
            "verdict": str(verdict),
            "reason": str(reason or ""),
            "detail": str(detail or ""),
        })

    def passed(self, checker, target, reason="", detail=""):
        self.record(checker, target, PASS, reason, detail)

    def rejected(self, checker, target, reason="", detail=""):
        self.record(checker, target, REJECT, reason, detail)

    def warned(self, checker, target, reason="", detail=""):
        self.record(checker, target, WARN, reason, detail)

    def briefed(self, checker, target, reason="", detail=""):
        """Record the INPUT a checker was handed, before it decides anything.

        Printed first under its gate and excluded from the pass/reject counts:
        it is the question, not an answer.
        """
        self.record(checker, target, BRIEF, reason, detail)

    def counts(self, checker=None):
        """(pass, reject, warn) for one checker, or for everything."""
        out = {PASS: 0, REJECT: 0, WARN: 0}
        for e in self.entries:
            if checker and e["checker"] != checker:
                continue
            if e["verdict"] in out:
                out[e["verdict"]] += 1
        return out[PASS], out[REJECT], out[WARN]

    def report(self, checkers=()):
        """The report text. `checkers` lists gates that should have run.

        A gate named in `checkers` with no entries is printed as DID NOT RUN
        rather than omitted, because a silent gate is the failure this module
        exists to catch.

        Every verdict is printed, accepts included. An earlier version hid
        accepts once a gate had more than six rows, to keep the report short —
        which removed exactly the line needed to answer "so WHICH frame got
        used?" on the render where seventeen rejects buried six accepts. A
        report you cannot audit is decoration.
        """
        seen = []
        for e in self.entries:
            if e["checker"] not in seen:
                seen.append(e["checker"])
        order = list(checkers) + [c for c in seen if c not in checkers]

        lines = ["", "b-roll & copy review — who checked what"]
        lines.append("-" * 58)
        for checker in order:
            div = DIVISIONS.get(checker, "—")
            rows = [e for e in self.entries if e["checker"] == checker]
            if not rows:
                lines.append(f"{div:<12} {checker:<10} DID NOT RUN")
                continue
            ok, no, warn = self.counts(checker)
            head = f"{div:<12} {checker:<10} {ok} pass · {no} reject"
            if warn:
                head += f" · {warn} warn"
            if not (ok or no or warn):
                # Briefed but never answered. This is the look="" shape: the
                # gate was handed its question and then decided nothing, which
                # the old report showed as an empty but present section.
                head += "  ← BRIEFED, NO VERDICT"
            lines.append(head)
            # The brief first: what this gate was asked. Reading a run of
            # rejects without it cannot distinguish "no footage matched" from
            # "the question was impossible".
            rows = ([e for e in rows if e["verdict"] == BRIEF]
                    + [e for e in rows if e["verdict"] != BRIEF])
            for e in rows:
                mark = {PASS: "ok  ", REJECT: "NO  ", WARN: "warn",
                        BRIEF: "GIVEN"}.get(e["verdict"], "?   ")
                why = e["reason"]
                if e["detail"]:
                    why = f"{why} — {e['detail']}" if why else e["detail"]
                lines.append(f"             {mark} {e['target']}"
                             + (f"  {why}" if why else ""))
        lines.append("-" * 58)
        ok, no, warn = self.counts()
        lines.append(f"total: {ok} pass · {no} reject"
                     + (f" · {warn} warn" if warn else ""))
        return "\n".join(lines)

    def emit(self, checkers=()):
        print(self.report(checkers), file=self._stream, flush=True)


# A render builds one ledger and passes it down. Module-level so the deep
# call sites (vision gate inside a thread pool) can reach it without threading
# an argument through five signatures that do not otherwise care.
_current = None


def start():
    global _current
    _current = Ledger()
    return _current


def current():
    return _current


def record(checker, target, verdict, reason="", detail=""):
    """No-op when no render is active, so library use stays side-effect free."""
    if _current is not None:
        _current.record(checker, target, verdict, reason, detail)


def passed(checker, target, reason="", detail=""):
    record(checker, target, PASS, reason, detail)


def rejected(checker, target, reason="", detail=""):
    record(checker, target, REJECT, reason, detail)


def warned(checker, target, reason="", detail=""):
    record(checker, target, WARN, reason, detail)


def briefed(checker, target, reason="", detail=""):
    record(checker, target, BRIEF, reason, detail)


def stop():
    global _current
    _current = None


if __name__ == "__main__":
    led = start()
    led.rejected("sourcing", "rally Jakarta", "off topic", "shot in Indonesia")
    led.passed("sourcing", "Kompas 1.35M", "verified channel")
    led.rejected("footage", "gbDzBo9w890 @110s", "off topic",
                 "Israeli air force pilot")
    led.rejected("footage", "zgS8aYWWArg @95s", "not the action",
                 "mass funeral, aftermath")
    led.warned("edit", "cutaways", "0 placed", "no footage of the act")

    text = led.report(checkers=("sourcing", "footage", "copy", "sound"))
    assert "RESEARCH" in text
    # A gate that never ran must be visible, not absent.
    assert "copy       DID NOT RUN" in text, text
    assert "sound      DID NOT RUN" in text, text
    # Counts, not just lines.
    assert "1 pass · 1 reject" in text, text
    assert "0 pass · 2 reject" in text, text
    assert "total: 1 pass · 3 reject · 1 warn" in text, text
    # Reason and detail both survive.
    assert "not the action — mass funeral, aftermath" in text, text

    # --- the brief: what a gate was GIVEN, not only what it decided ---------
    led2 = start()
    led2.briefed("footage", "subject = 'korban keracunan MBG'", "3 word(s)",
                 "from context 'Gibran minta maaf ke korban...'")
    led2.rejected("footage", "abc @40s", "not the action", "hospital corridor")
    led2.passed("footage", "abc @65s", "motion 30.3", "collapsed building")
    led2.briefed("copy", "style = 'pr-politik'", "mood inspiring")
    t2 = led2.report(checkers=("footage", "copy"))
    # The brief prints, and prints FIRST — a run of rejects cannot be read
    # without knowing what question produced them.
    assert "GIVEN subject = 'korban keracunan MBG'" in t2, t2
    assert t2.index("GIVEN subject") < t2.index("NO   abc @40s"), t2
    # It is a question, not a verdict, so it must not inflate the counts.
    assert "1 pass · 1 reject" in t2, t2
    # A gate handed its brief and then deciding nothing is the look="" shape:
    # visible, not an empty section.
    assert "BRIEFED, NO VERDICT" in t2, t2

    # Library use outside a render must not accumulate anything.
    stop()
    rejected("footage", "x", "y")
    assert current() is None

    print("audit: self-check ok")
    if os.environ.get("CLIPPER_AUDIT_DEMO"):
        print(text)
