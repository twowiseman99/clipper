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

## Who writes the code

Operator rule, 22 Oct 2026: *"selama argon high dan gemini flash 3.8 high bisa
coding, pake itu dulu sampai habis, kalian dan agency agent tugasnya review
semua sampai clear baru claude turun tangan tapi ttp pakai agency agent buat
saling review"*.

Coding capacity is spent in order. Load the `foreman` skill for the full
procedure; the rungs are:

1. `gemini-4-argon-high` — **through the `agy` CLI only**.
2. `gemini-3.8-flash-high`.
3. Claude — only after rungs 1 and 2 are exhausted.

**A rung change needs a quoted limit error from the worker, in the report.**
"Argon seemed slow", "this task is too hard for flash" and "faster if I write
it myself" are not conditions, they are violations. A wrong diff is a FAIL that
earns a revision brief (three rounds at most), not an escalation.

**Review never escalates with the coding.** Whoever wrote the diff, it is
reviewed by the lead plus the agency agents per `audit.DIVISIONS` — and that
includes Claude's own output at rung 3. Claude writing the code does not make
the code trusted. An agent never reviews what it wrote.

*Clear* means every division that should have run **returned a verdict**. A
division that recorded nothing prints DID NOT RUN and blocks the ship; a silent
division is not a pass.

Two measurements that already cost a wrong report on this box:

- **`agy` is the working path for both workers — verified, not assumed.**
  Measured 22 Oct 2026 with `agy 1.4.3` (login held in the `agylogin` tmux
  session): `gemini-4-argon-high` and `gemini-3.8-flash-high` both exit 0 and
  return code that **runs and gives the right answer**. Invoke it with the flags
  in front and the prompt glued to `--print`:
  `agy --model gemini-4-argon-high --print="$(cat brief.txt)"`. A bare `--print`
  swallows the next token as its prompt, `--model` is dropped, and the task
  silently runs on the default model.
- **`/v1/models` on 9router is a catalogue, not an entitlement check.** On
  0.5.104 `ag/gemini-4-argon-high` is listed yet returns upstream `404 Requested
  entity was not found` (same for `ag/gemini-3.7-flash-high`) — so the router is
  the wrong instrument for argon, not evidence that argon is unavailable. Never
  call a model available *or* dead from the list alone: send one real request
  through the path production uses and run what comes back.
- The router **answers with streaming SSE even when `stream=False`**, so
  `json.loads(body)` fails at `line 1 column 1` and a healthy model looks
  broken. Assemble the content from the `data:` lines before judging it.

Argon's known failure mode is not laziness, it is **collateral edits**: it has
rewritten files the brief told it not to touch. Run `git diff --stat` and revert
anything outside the target file before accepting the work, and re-measure its
reported numbers yourself.

## Akses Server

Server: `43.157.203.118` (Sumopod, Ubuntu 24.04 LTS, user `ubuntu`).
**Nol password di file ini.** Kalau butuh sandi, minta ke operator langsung —
jangan pernah ditulis di sini atau di channel grup.

**Kalau Kelvin minta cara masuk server, tanya dulu dia pakai Mac atau PC.**
Jawabannya beda, dan ngasih yang salah bikin dia stuck di prompt password.

### Dari Mac

SSH key udah terpasang, jadi tanpa password:

```bash
ssh sumo                  # masuk shell
ssh sumo 'perintah'       # jalanin langsung tanpa masuk shell
```

`sumo` itu alias di `~/.ssh/config` **di Mac-nya**, bukan di server. Jadi
perintah ini **tidak bisa** diverifikasi dari dalam box — ini instruksi buat
mesin klien, bukan klaim terukur.

### Dari PC (Windows)

Pakai password:

```powershell
ssh ubuntu@43.157.203.118
```

Biar ga ditanya password terus, setup key **sekali** di PowerShell:

```powershell
ssh-keygen -t ed25519
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh ubuntu@43.157.203.118 "cat >> ~/.ssh/authorized_keys"
```

### Fakta server ini — diukur 23 Okt 2026, bukan diasumsikan

- **`sudo` tanpa password**, tapi pakai `sudo -n` biar gagal terang-terangan
  kalau ternyata dia minta sandi (diukur: `sudo -n true` → sukses).
- **Hermes jalan sebagai service USER, bukan sistem.** Ini diukur dua arah:
  `systemctl --user is-active hermes-gateway` → `active`, sementara
  `systemctl is-active hermes-gateway` (sistem) → `inactive`. Jadi lewat SSH
  non-login, set dulu runtime dir-nya:

  ```bash
  export XDG_RUNTIME_DIR=/run/user/$(id -u)
  systemctl --user status|start|stop hermes-gateway
  ```

  Tanpa `XDG_RUNTIME_DIR`, `systemctl --user` ga nemu bus-nya dan errornya
  kelihatan kayak service-nya ga ada.
- **CLI hermes** di `~/.hermes/hermes-agent/venv/bin` (diukur: `hermes` ada di
  situ). Lewat `ssh` langsung dia **ga ada di PATH** — tambahin dulu atau pakai
  path penuh.
- **Kalau login biasa langsung "Connection closed", jangan pakai `-t`.** Kirim
  perintahnya langsung: `ssh sumo 'perintah'`.

Satu aturan dari dalam: **restart/stop `hermes-gateway` dari dalam sesi Hermes
diblokir guard, dan itu benar** — prosesnya bunuh interpreter-nya sendiri, jadi
nol yang bisa mengonfirmasi hasilnya. Dari SSH luar aman; dari dalam sesi pakai
`systemd-run --user --on-calendar='<tanggal jam absolut>'` manggil script
idempotent di `~/.hermes/scripts/`.

### Pitfall

- **`pkill -f` dengan kata yang muncul di perintahnya sendiri bikin shell bunuh
  diri** — pola `-f` dicocokkan ke seluruh command line, termasuk command line
  shell yang sedang mengetik pola itu. Pakai trik kurung:

  ```bash
  pkill -f [f]fmpeg
  pkill -f [h]ermes_cli
  ```

  `[f]fmpeg` cocok ke string `ffmpeg`, tapi **tidak** cocok ke teks
  `[f]fmpeg` di command line sendiri. Buat sekadar menghitung, pakai
  `pgrep -x ffmpeg` (nama proses persis, bukan command line).
- **Jangan suruh Kelvin ketik password sebelum prompt `password:` muncul.**
  Karakter yang diketik sebelum prompt siap ditelan terminal, bukan dikirim —
  jadi kelihatan seperti sandinya salah padahal sandinya benar.

### Darurat: server macet (SSH timeout / banner exchange)

Penyebab terakhir (23 Okt 2026): satu proses `ffmpeg` makan **~7,4 GB** dari
RAM 7,4 GB, swap 2 GB habis, server OOM. Kernel log:

```
Out of memory: Killed process (ffmpeg) anon-rss:7422720kB, UID:1000
Out of memory: Killed process (ffmpeg) anon-rss:7430644kB
```

1. **Kalau SSH tidak tembus, restart dari dashboard Sumopod.** Box yang sudah
   OOM tidak bisa menerima SSH baru — tunggu di SSH itu sia-sia.
2. **Dari Mac**, tunggu SSH siap lalu matikan pemicunya:

   ```bash
   until ssh-keyscan -T 5 43.157.203.118 2>/dev/null | grep -q ssh; do sleep 5; done
   ssh sumo 'export XDG_RUNTIME_DIR=/run/user/$(id -u); pkill -f [f]fmpeg; systemctl --user stop hermes-gateway; free -h; uptime'
   ```

   `ssh-keyscan` dipakai sebagai probe karena dia balik begitu port 22 jawab,
   tanpa perlu otentikasi.
3. **Lakukan dalam 9 menit setelah boot** — render jebol sekitar menit 9–10,
   jadi itu jendela waktu yang ada sebelum box tidak bisa dimasuki lagi.

### Status job render (per 23 Okt 2026)

Di-pause sampai fix memori `ffmpeg` terbukti (diukur lewat `cronjob list`,
ketiganya `state: paused`, `paused_at` 17:26):

| job_id | nama | catatan |
|---|---|---|
| `4688dbed4c44` | `clipper-render-tick` | tiap 3 menit |
| `455ebcd2fa17` | `bio1-render-broll` | tiap 30 menit, `last_status: error` |
| `8cc06f546710` | `stockstory-scene-filler` | tiap 10 menit |

**Resume satu per satu**, dan hanya setelah render percobaan dengan
`/usr/bin/time -v` menunjukkan **Max RSS di bawah 1,5 GB**.

Cron sistem juga sedang dihentikan (diukur: `systemctl is-active cron` →
`inactive`, tapi masih `enabled` jadi dia nyala lagi sendiri kalau box reboot —
ini bukan pagar permanen). Nyalakan lagi setelah fix: `sudo -n systemctl start cron`.

