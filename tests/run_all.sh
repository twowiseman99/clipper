#!/usr/bin/env bash
# Every regression test, plus each module's own self-check.
#
# Run from the repo root:  bash tests/run_all.sh
#
# These are not unit tests of pure functions. Most of them invoke ffmpeg or the
# vision router for real, because the bugs they cover all passed string-level
# assertions: `hue` has no `eval` option and ffmpeg rejected the whole filter
# graph mid-render, while a test asserting on the filter string was green.
# Expect a few minutes and a working router for the b-roll gate tests.
set -u

cd "$(dirname "$0")/.." || exit 1
PY=.venv/bin/python
fail=0

# Drop stale bytecode before anything imports. Python decides a .pyc is valid by
# comparing the source's mtime, and a file restored with `cp` (reverting an
# experiment, checking out a branch) can land with a timestamp the cache already
# matches -- measured here as edit.py and edit.cpython-311.pyc sharing mtime
# 1791700879 exactly. The symptom is a test reading a constant the source file
# does not contain, which looks like a plumbing bug and is not one.
find . -maxdepth 2 -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null

echo "== module self-checks =="
# audit/audit_fmt/audit_watch were missing from this list while all three had
# self-checks, so the ledger's own tests only ran when someone remembered to
# invoke them by hand.
for m in segments edit broll_place broll censor language glossary metadata bgm \
         audit audit_fmt; do
    printf '%-14s ' "$m"
    if timeout 240 $PY "$m.py" >/dev/null 2>&1; then echo ok; else echo FAIL; fail=1; fi
done

printf '%-14s ' "audit_watch"
if $PY audit_watch.py --selftest >/dev/null 2>&1; then echo ok; else echo FAIL; fail=1; fi

printf '%-14s ' "session_import"
if $PY session_import.py selfcheck >/dev/null 2>&1; then echo ok; else echo FAIL; fail=1; fi

printf '%-14s ' "konten"
if $PY konten.py selfcheck >/dev/null 2>&1; then echo ok; else echo FAIL; fail=1; fi

printf '%-14s ' "job --selftest"
if $PY job.py --selftest >/dev/null 2>&1; then echo ok; else echo FAIL; fail=1; fi

echo
echo "== regression tests =="
for t in tests/_v*.py; do
    printf '%-14s ' "$(basename "$t" .py)"
    if timeout 300 $PY "$t" >/dev/null 2>&1; then echo ok; else echo FAIL; fail=1; fi
done

echo
if [ "$fail" -eq 0 ]; then echo "all green"; else echo "FAILURES above"; fi
exit "$fail"
