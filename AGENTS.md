# Agents

Start with `README.md`. It has the clone command, the two setup paths and what
each one actually needs.

The short version for an agent asked to make a clip:

1. `python edit.py` renders two clips from footage it generates itself. No
   network, no keys, no footage on disk. If this fails, nothing else will work,
   and the output says why.
2. `python job.py --list` prints the catalogue as JSON: caption styles, hook
   styles, frame modes and the music moods available on this box.
3. `python job.py --opening URL --content URL` renders and prints a JSON result
   holding the output path. The opening link is optional and carries the hook;
   with neither it nor `--hook "text"`, the clip has no hook, which is the
   intended result rather than a fallback.

`job.py` is the contract. It prints JSON on stdout and progress on stderr, so
you never parse a traceback to tell the user what happened. Exit `3` with
`{"busy": true}` means another job is already running on this host: say so and
retry later rather than starting a second one. Any other non-zero exit prints
`{"ok": false, "error": ...}` along with the path of a diagnostic report.

Posting the file, reading the chat message and holding the conversation are
yours. `job.py` deliberately stops at the file.

Two limits worth telling a user about before they wait:

- Without `cookies.txt` the download is capped at 360p and the clip looks soft.
- Without `NINEROUTER_API_KEY` the hook and title come from the transcript
  rather than a model. The clip still renders.

`python preflight.py` reports which of those are missing on this box.

If you are being set up as a Discord bot, `hermes-prompt.md` is the prompt to
use, and it covers the upload-size problem this repo's default bitrate creates.

`CLAUDE.md` holds the working notes, the house rules and the antislop pointer.
Read it before changing code.

## Verification is mandatory

Operator rule, 21 Oct 2026: *"WAJIB pakai di semua workflow development kita"*.

Before you hand over development work on this repo, load the
`create-verification-skill` skill and follow it. It generates a project-local
verification skill that drives the app the way a user does. Keep it honest with
`maintain-verification-skill`. Both are installed verbatim from
`cursor/plugins` (`pstack/skills/`), with only the skills path adapted.

These three are different layers, not substitutes for one another:

- `verification-before-completion` gates the *claim*: no completion claim
  without fresh evidence.
- `dogfood` is a *one-off QA sweep* for finding bugs in a session.
- `create-verification-skill` builds a *durable asset*: `verify-<app>/` plus a
  maintained `features/` map that outlives the session.

The rules that bite hardest here, each one a bug this repo has already shipped:

- Proof drives the **real user path**, never an internal setter or a test-only
  endpoint.
- Capture the **action and the resulting state**, not just the final screen.
- Check **side effects** (files written, rows inserted, messages sent), not only
  what is visible.
- `ready` means **usable**, not "a process answers". A health check can pass
  while init scripts are still running.
- Cleanup **never eats the evidence**; proof artifacts outlive the teardown.
- Never kill by process name. Kill **what you started**.
- For a dry-run, **measure what it actually skips** instead of trusting its name.
- A missing precondition makes the journey **report failure**, and the reason
  goes in that feature's `Gotchas`. Never weaken the journey to make it pass.
- A generated skill that was never executed is a **draft, not a deliverable**.

