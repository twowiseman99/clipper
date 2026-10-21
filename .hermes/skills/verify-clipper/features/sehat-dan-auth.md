# Health and auth

The console sits behind Basic Auth with manually created accounts and no signup. One
endpoint, `/sehat`, is deliberately open so systemd and the reverse proxy can check
liveness without credentials — but it withholds operational numbers from anonymous
callers.

## Sub-features

- `sehat-anonim` answers without credentials and reveals only `{"ok":true}`.
- `sehat-login` adds the queue length and account count for an authenticated caller.
- `auth-tolak` refuses any page except `/sehat` without credentials.
- `auth-terima` serves `/` with valid credentials.

## How to get to it (user POV)

- Open any console URL in a browser; the browser prompts for username and password.
- Fetch `/sehat` from a monitoring tool with no credentials.

## Driving it with control_clipper

Preconditions:

- The verification instance is running on `127.0.0.1:8042`.
- The instance has exactly one account (`verify`), injected by the harness.

- **Anonymous health is minimal.** Fetch without credentials. Run
  `curl -sS http://127.0.0.1:8042/sehat`. The body is exactly `{"ok":true}` — no
  `nunggu`, no `user_kepasang`.
- **Authenticated health adds numbers.** Run
  `curl -sS -u verify:verify-local-only http://127.0.0.1:8042/sehat`. The body is
  `{"ok":true,"nunggu":0,"user_kepasang":1}`.
- **Anonymous page access is refused.** Run
  `.venv/bin/python tools/control_clipper.py doctor` and read the
  `tanpa sandi ditolak` line: `GET /` with no credentials returns `401`.
- **Valid credentials work.** The same doctor run's `halaman kepakai` line shows `/`
  returning `200` with credentials.
- **Proof.** `doctor` output is the artifact for this feature; it names each check and
  its observed status.

## Gotchas

- **`/sehat` returning `200` does not mean the app is ready.** It answers before the
  queue tables exist, which is why `launch` waits on `/` behind auth instead. A health
  check passing while init work continues is the classic false-ready signal.
- The account count is withheld from anonymous callers on purpose: the console is
  reachable from the internet through the reverse proxy, and the number of accounts is
  a free hint for anyone guessing passwords. If a change starts leaking
  `user_kepasang` anonymously, that is a security regression.
- The live console binds `127.0.0.1` and is only reachable through Caddy. Never change
  it to `0.0.0.0` to make verification easier — that removes a layer and leaves Basic
  Auth as the only fence.
- `/sehat` is the **only** route exempt from auth. Do not add exemptions for
  convenience during verification.
- Credentials for the live console live in `~/.hermes/clipper-console.env`, mode 600.
  Verification must never read them; it injects its own throwaway account instead.
