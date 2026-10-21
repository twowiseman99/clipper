---
name: verify-clipper
description: "Drive the Clipper render console (FastAPI web UI at /, /job/{id}, /campaign) the way a user does, on an isolated instance, and capture evidence. Use before handing over any change to render_console.py, preflight.py, the queue, or the YouTube upload path."
---

# Verify Clipper

Clipper's primary surface is the **render console**: a FastAPI app (`render_console.py`)
served by uvicorn. A user opens it in a browser behind Basic Auth, fills a form, and
watches a job page. Secondary surfaces exist (`job.py` CLI, the Discord bot) and are
not covered here.

Everything below drives an **isolated instance on port 8042**, never the operator's
live console on `127.0.0.1:8001`. The live one is reverse-proxied to
`https://43-157-203-118.nip.io` and its queue is real: driving it would add real rows
and can start an 800-second render.

The harness is `tools/control_clipper.py`, run with the repo venv:

```
.venv/bin/python tools/control_clipper.py <launch|doctor|browser|http|cleanup>
```

## Launch

```
.venv/bin/python tools/control_clipper.py launch
```

Starts `render_console.py` from an **empty data directory** with every shared path
redirected into a fresh temp dir: `CLIPPER_QUEUE_DB`, `CLIPPER_TOKEN_DIR`,
`CLIPPER_JOB_OUT`, `CLIPPER_JOB_LOCK`, plus its own `CLIPPER_CONSOLE_USERS`
(`verify` / `verify-local-only`) and `CLIPPER_CONSOLE_PORT=8042`.

**Ready means usable, not "a process answers".** `/sehat` is deliberately open without
auth, so it returns `200` while the queue tables may not exist yet. Launch therefore
polls `GET /` **behind Basic Auth** and waits for the rendered page, which is what a
user actually loads. It gives up after 30s and prints the tail of the console log.

Two instances can run side by side: every piece of shared state is env-overridable and
the port is too. Never drive an instance this run did not start.

## Doctor

```
.venv/bin/python tools/control_clipper.py doctor
```

Read-only, zero mutations, seven independent checks — each with its own evidence
rather than one number standing in for all of them:

| Check | Proves |
|---|---|
| state file | this run owns an instance |
| pid hidup | the process is alive |
| port punya kita | `ss -ltnp` shows **our pid** on 8042, not merely "something answers" |
| /sehat jawab | the app is serving |
| tanpa sandi ditolak | auth actually bites (`401` without credentials) |
| halaman kepakai | `/` renders behind auth |
| DB terisolasi | the queue DB is in our temp dir, not the operator's |

Exit `0` when all pass, `1` with a `GAGAL: n` line otherwise. Run it first whenever
anything looks off.

## Drive

```
.venv/bin/python tools/control_clipper.py browser \
  --fitur kirim-render --path / \
  --expect 'Render klip baru' --expect-handle content \
  --snapshot form.txt --screenshot form.png
```

- `--expect` matches **text the user reads** (`body.inner_text()`), not raw HTML.
  Matching HTML source is a trap: `name=opening` appears in the source but
  `page.content()` serialises it as `name="opening"`, so a source match goes red while
  the feature is healthy.
- `--expect-handle` asks the **DOM** for a form control by `name`, for handles that
  are not visible text.
- `--fill name=value` (repeatable) and `--click '<button label>'` drive by ARIA role
  and accessible name, never coordinates or tab order.
- `http --path /sehat --expect ...` for endpoints with no UI.

Stable handles in this app: form field names `preset`, `content`, `opening`, `image`,
`bgm`, `context`; routes `/`, `/render`, `/job/{id}`, `/upload`, `/fix`, `/batal`,
`/campaign`, `/sehat`; button label `Masukin antrean`.

## Evidence

Artifacts go to `artifacts/<fitur>/` in the repo. Capture **the action and the
resulting state**, not just the final screen, and pair what is visible with the side
effect:

- UI proof: a `--snapshot` text dump plus a `--screenshot` full-page PNG.
- Mutation proof: read the queue DB directly and compare row counts **before and
  after** the user action. The DB path is in `/tmp/verify-clipper.json` → `data`.
- Rejection proof: a form that should be refused must leave the row count **unchanged**
  — and you must separately show the submit was actually attempted, or "0 rows" only
  proves your click missed.

Drive the real user path. Never POST to an internal helper or flip a DB row to
simulate a state the UI is supposed to produce.

## Cleanup

```
.venv/bin/python tools/control_clipper.py cleanup
```

Kills **the pid recorded in the state file**, then removes the temp data dir. Never
`pkill -f render_console.py`: the operator's live console runs from the exact same
file and would die with it.

`artifacts/` is **not** touched. Proof outlives the teardown. Run cleanup after a
failed attempt too, so broken runs do not strand port 8042.

## Helpers

`tools/control_clipper.py` is executable and every invocation above is shown in full.
`tools/potret_ui.py` is a different tool: it screenshots the **live** console over
HTTPS for showing the operator, and is not part of verification.
