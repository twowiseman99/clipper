#!/usr/bin/env bash
# Deliver each render's division ledger to Discord.
#
# Pairs with job.py, which now writes <clip>.audit.json next to every clip.
# This wrapper exists because the cronjob tool only runs scripts out of
# ~/.hermes/scripts/.
#
# AUDIT_WEBHOOK must hold the channel's webhook URL. Without it the script
# prints the ledger instead of posting, which is useful by hand and useless
# from cron — so the cron job is the thing that needs the variable set.
set -euo pipefail

cd /home/ubuntu/clipper

# Keep the token out of the repo and out of the job definition.
#
# A MISSING webhook file is a failure, not a quiet no-op. This wrapper used to
# shrug and run anyway: audit_watch then printed 70 ledgers to a stdout nobody
# reads, marked them all delivered, and the cron job reported "ok" every 15
# minutes while #agency-agent stayed empty. Say so loudly and exit non-zero so
# the scheduler surfaces it.
WEBHOOK_FILE=/home/ubuntu/.hermes/audit-watch/webhook
if [ ! -s "$WEBHOOK_FILE" ]; then
  echo "audit_watch.sh: $WEBHOOK_FILE kosong atau ga ada." >&2
  echo "Ga ada log yang bisa dikirim. Isi file itu dengan URL webhook" >&2
  echo "channel #agency-agent, lalu jalanin lagi." >&2
  exit 1
fi
AUDIT_WEBHOOK="$(cat "$WEBHOOK_FILE")"
export AUDIT_WEBHOOK

# Phase 2: the short human narration above the facts. Opt-in by design, and
# switched on here rather than in the module default so Phase 1 stays
# provable on its own. If the router is down or the narration fails any of
# its checks it is dropped silently and the ledger still ships -- the log is
# the deliverable, the narration is a courtesy.
export AUDIT_NARRATE=1

exec .venv/bin/python audit_watch.py --once
