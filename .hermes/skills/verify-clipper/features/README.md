# Clipper verification map

This directory is the maintained source for verifying the user-facing behavior of the
Clipper render console. Read this index before driving the app, then use the matching
feature file as the recipe.

## Baseline preconditions

- Launch the console at `http://127.0.0.1:8042` with a disposable data directory:
  `.venv/bin/python tools/control_clipper.py launch`.
- Never drive `127.0.0.1:8001`. That is the operator's live console behind
  `https://43-157-203-118.nip.io`, with a real queue and real renders.
- Credentials for the verification instance are `verify` / `verify-local-only`,
  injected via `CLIPPER_CONSOLE_USERS` by the harness.
- The queue starts **empty**. Row counts in these recipes assume that.
- Run `.venv/bin/python tools/control_clipper.py doctor` and require all seven checks
  before driving anything.
- Never drive an instance this run did not start.

## Driving conventions

- Start every recipe from the baseline state unless its preconditions say otherwise.
- Assert on text the user reads (`--expect`) or a DOM handle (`--expect-handle`).
  Never on raw HTML source.
- Prefer accessible names and form `name` attributes over CSS position or tab order.
- Treat every command as literal. Keep quoted labels and flags unchanged.
- Run browser actions through `control_clipper.py browser`.
- Run no-UI endpoints through `control_clipper.py http`.
- Do not remove proof artifacts during cleanup.

## Proof and skip reporting

- Capture the user action and the resulting state, not only the final screen.
- UI proof includes a text snapshot and a full-page screenshot.
- Mutation proof includes a queue-DB row count taken **before and after** the action.
- A rejection proof must also show the submit was attempted. An unchanged row count
  alone is equally consistent with "the click never landed".
- Report an unreachable path with the attempted command and the unmet precondition.
- Do not report a skipped entry point as verified through a different path.

## Feature entry contract

Each feature file starts with an H1 title and one paragraph describing the user-visible
behavior. It then uses exactly four H2 sections in this order.

1. `Sub-features` lists short IDs with one line for each behavior.
2. `How to get to it (user POV)` lists every user entry point.
3. `Driving it with control_clipper` starts with `Preconditions:` and uses labeled
   bullets that pair each user action with an exact command and observable result.
4. `Gotchas` lists traps that can waste or invalidate a verification run.

Keep implementation details out of the map. Name only user paths, stable handles,
required state, commands, and observable proof.

## Features

- [Submit a render](./kirim-render.md) covers the render form, preset-driven field
  enabling, validation of a missing link, and the queue row it creates.
- [Job page and upload blocker](./job-dan-upload.md) covers the job page, the honest
  reason the YouTube upload button is disabled, and the library-vs-token distinction.
- [Health and auth](./sehat-dan-auth.md) covers the open health endpoint, what it
  withholds from anonymous callers, and Basic Auth enforcement.

## Not yet mapped

These are user-facing but have no recipe yet. Absence here means unverified, not
working:

- `/campaign` and the campaign asset flow (`/campaign/{slug}/pick`, `/aset`).
- `/fix` (re-render with corrections) and `/batal` (cancel a queued job).
- `/file/{job_id}` download of the rendered clip.
