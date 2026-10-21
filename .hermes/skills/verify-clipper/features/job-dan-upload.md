# Job page and upload blocker

The job page shows one render's state, its warnings, the rendered file, and a
`Kirim ke YouTube` panel whose submit button is disabled until the console actually has
a usable YouTube account — with the reason stated in words above the button.

## Sub-features

- `job-ada` renders state, warnings and the output file for an existing job.
- `job-hilang` reports a job id that does not exist.
- `upload-sebab-token` disables the upload button and names the missing OAuth token
  path when the Google libraries are installed but no token exists.
- `upload-sebab-library` disables it with a different message when the Google client
  libraries are missing, stating explicitly that this is not an OAuth problem.
- `upload-judul-counter` shows a live `n/100` counter on the YouTube title field.

## How to get to it (user POV)

- Open `/job/{id}` after submitting a render, or follow a row in `Render terakhir`.
- Fill the title/description fields in `Kirim ke YouTube` and choose the submit button.

## Driving it with control_clipper

Preconditions:

- `control_clipper.py doctor` passes all seven checks.
- `CLIPPER_TOKEN_DIR` points at the instance's empty temp `tokens/` directory, which
  `launch` guarantees. Confirm with
  `.venv/bin/python -c "import preflight; print(preflight.upload_blocker())"` run with
  that env — expect `('token', '<temp>/tokens')`.

- **Missing job reports itself.** Open a job id that does not exist. Run
  `.venv/bin/python tools/control_clipper.py browser --fitur job-dan-upload --path /job/999 --expect 'Job #999 ga ada' --snapshot hilang.txt`.
  The page body reads `Job #999 ga ada` and offers a `Balik` link.
- **Create a real job through the user path first.** A fresh instance has an empty
  queue, so `/job/1` is also "ga ada" until a job exists. Submit the form the way a user
  does — never insert a queue row directly:
  `.venv/bin/python tools/control_clipper.py browser --fitur kirim-render --path / --fill 'content=https://www.youtube.com/watch?v=dQw4w9WgXcQ' --click 'Masukin antrean' --snapshot abis-submit.txt`.
  The queue DB goes from `0` to `1` row and the page becomes `Job #1`, reading
  `Mengharukan · waiting · punya verify`.
- **Upload blocked by a missing token.** The upload panel only renders for a job whose
  state is `done` — `render_console.py` appends `_panel_upload` in the `done` branch
  only. A freshly submitted job is `waiting`, so this step **cannot be reached on a
  fresh instance** without letting a render finish, which takes minutes and needs real
  footage. Report it as unreached rather than asserting against a `waiting` page:
  `.venv/bin/python tools/control_clipper.py browser --fitur job-dan-upload --path /job/1 --expect 'Kirim ke YouTube' --snapshot job.txt --screenshot job.png`
  exits `1` with `GA ADA` on a `waiting` job, which is the honest result.
  Until a `done` job exists on the verification instance, the blocker wording is covered
  by `tests/_v89.py` and by calling `preflight.upload_blocker()` directly, not by this
  page recipe.
- **The two blockers are distinguishable.** Hide the Google libraries and re-read the
  blocker, which must change category rather than repeat the OAuth wording:
  `PYTHONPATH=<dir with a googleapiclient.py that raises ImportError> .venv/bin/python -c "import preflight; print(preflight.upload_blocker())"`
  returns `('library', 'googleapiclient.discovery: ImportError: ...')`. `tests/_v89.py`
  locks this with its own negative controls.
- **Proof.** Keep `artifacts/job-dan-upload/job.png`, `job.txt`, and `hilang.txt`.

## Gotchas

- **The upload panel does not exist until a job is `done`.** `_panel_upload` is only
  appended in the `done` branch, so every upload assertion needs a finished render as a
  precondition. A fresh verification instance cannot satisfy that without a real render.
  This journey therefore **reports the step as unreached**; it was not weakened into
  something a `waiting` job can pass.
- **The page `<title>` is not the page body.** `/job/999` renders a `<title>` of
  `Ga ketemu` while the body reads `Job #999 ga ada`. The first recipe written here
  asserted the title text and went red against a healthy app. Assert what
  `body.inner_text()` contains, which is what the user reads.
- **`/job/{id}` returns HTTP `200` for a job that does not exist**, with the "ga ada"
  message in the body. Measured on `/job/1` and `/job/999` against an empty queue. So a
  status-code assertion cannot test this path — assert on the body text. Recorded as an
  observation; verification does not silently change what it measures.
- `upload_accounts()` used to swallow `ImportError` into `[]`, making "libraries not
  installed" and "no OAuth token" produce the identical page. `upload_blocker()` exists
  precisely to keep them apart; if both messages ever read the same again, that is a
  regression, not cosmetics.
- Checking the libraries with `import upload_youtube` is **blind**: that module imports
  `googleapiclient` inside its functions, so the import succeeds with the libraries
  absent. Import exactly what `upload()` calls.
- `TOKEN_DIR` defaults to `/home/ubuntu/tokens`, **outside the repo**. A real token
  parked there changes what this page says. The harness isolates it; tests must too
  (`_v81`, `_v85`, `_v87` all went red once from a single dummy token).
- A dummy token makes the button clickable but the upload still fails at Google with
  `401`. A clickable button is not proof of a working upload.
