#!/usr/bin/env python3
"""Every division must be watched by the render's audit emit().

The bug this guards: job.py typed the checker list out by hand, so the two
divisions added later ("freeze", "caption") were never named and therefore
could never print DID NOT RUN. A gate that is never asked cannot report being
dead -- warnings:[] stayed clean while two gates were unwatched for a release.

This asserts the PROPERTY (the list equals DIVISIONS), not the count, so adding
a ninth division does not break the test -- which is the whole point: a test
pinned to "8" would have to be edited by the same hand that forgets the list.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

import audit  # noqa: E402

ok = 0
bad = []


def check(name, cond, detail=""):
    global ok
    if cond:
        ok += 1
    else:
        bad.append(f"{name}: {detail}")


# --- 1. the source line must derive from DIVISIONS, not a literal tuple ---
src = open(os.path.join(REPO, "job.py"), encoding="utf-8").read()
m = re.search(r"led\s*=\s*audit\.current\(\).*?led\.emit\(checkers=(\w+)\)",
              src, re.S)
check("emit() ada di job.py", m is not None, "pola emit(checkers=..) ga ketemu")
if m:
    var = m.group(1)
    block = src[m.start():m.end()]
    assign = re.search(rf"{var}\s*=\s*(.+)", block)
    check("checkers diturunkan dari DIVISIONS",
          assign is not None and "audit.DIVISIONS" in assign.group(1),
          f"checkers = {assign.group(1).strip() if assign else '?'}")
    check("checkers BUKAN daftar literal",
          assign is not None and '"' not in assign.group(1),
          "masih ada nama gate yang ditulis tangan")

# --- 2. save() must use the same list as emit(), or the json loses gates ---
check("save() pakai daftar yang sama",
      re.search(r"led\.save\([^)]*checkers=checkers", src, re.S) is not None,
      "save() pakai daftar lain -> ledger file beda dari yang dicetak")

# --- 3. behaviour: a division that records nothing must print DID NOT RUN ---
# Read report() directly. emit() writes to the stream captured when the ledger
# was created, so swapping sys.stdout afterwards captures NOTHING -- the first
# version of this test "failed" on all 8 gates while the report was plainly on
# screen, which is a broken instrument, not a broken gate.
audit.start()
audit.passed("sourcing", "kontrol", "satu gate nyatet")
led = audit.current()
out = led.report(tuple(audit.DIVISIONS))

for name in audit.DIVISIONS:
    check(f"gate '{name}' muncul di laporan", name in out,
          "ga disebut sama sekali")

silent = [n for n in audit.DIVISIONS if n != "sourcing"]
missing = [n for n in silent
           if not re.search(rf"{n}\s+DID NOT RUN", out)]
check("semua gate diam dilaporkan DID NOT RUN", not missing,
      f"diam tapi ga dilaporkan: {missing}")
check("gate yang nyatet TIDAK dilaporkan DID NOT RUN",
      not re.search(r"sourcing\s+DID NOT RUN", out),
      "sourcing nyatet 1 pass tapi dibilang DID NOT RUN")

# --- 4. negative control: the OLD hand-typed list must FAIL this property ---
old_list = ("sourcing", "footage", "copy", "language", "sound", "edit")
audit.start()
audit.passed("sourcing", "kontrol", "x")
old_out = audit.current().report(old_list)
unwatched = [n for n in audit.DIVISIONS if n not in old_list]
check("kontrol negatif: daftar lama memang MELEWATKAN gate",
      unwatched and all(n not in old_out for n in unwatched),
      f"daftar lama ternyata menyebut {unwatched} -- kontrol ga valid")

print(f"{ok} ok, {len(bad)} gagal")
for b in bad:
    print("  GAGAL", b)
sys.exit(1 if bad else 0)
