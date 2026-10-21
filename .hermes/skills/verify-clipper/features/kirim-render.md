# Submit a render

Submit a render lets a user pick one of two presets, paste the link of the video to be
cut, optionally add a hook link, an outro image, custom BGM and context, and put the
job in the queue — then watch it on the job page.

## Sub-features

- `kirim-form` renders the form with both presets and every optional field.
- `kirim-preset-mati` disables the outro image field when the Mengharukan preset is
  selected, and says why.
- `kirim-validasi` refuses a submit with no content link and creates no queue row.
- `kirim-antrean` creates exactly one queue row for a valid submit.
- `kirim-estimasi` states the queue wait honestly, including "not enough samples yet".

## How to get to it (user POV)

- Open `/` in a browser after Basic Auth and use the `Render klip baru` panel.
- Choose the `Masukin antrean` button to submit.

## Driving it with control_clipper

Preconditions:

- `control_clipper.py doctor` passes all seven checks.
- The queue is empty (a fresh `launch` guarantees this).
- No render is running on the verification instance.

- **Form loads.** Open the console. Run
  `.venv/bin/python tools/control_clipper.py browser --fitur kirim-render --path / --expect 'Render klip baru' --expect 'Mengharukan' --expect-handle content --expect-handle opening --expect-handle preset --snapshot form.txt --screenshot form.png`.
  Exit `0`, and the snapshot names both presets.
- **Disabled outro is explained.** Read the same snapshot. It contains
  `Preset Mengharukan ga pakai gambar outro, jadi field ini mati. Pilih Jedag jedug buat ngisinya.`
  The hint must be present as text, not conveyed by colour alone.
- **Queue state is honest.** The same snapshot contains `Antrean kosong, render lu mulai langsung.`
  on an empty queue.
- **Reject a missing link.** Count rows, submit with the content field untouched, count
  again. Read the DB path from `/tmp/verify-clipper.json` → `data` + `/queue.db`, then
  `select count(*) from jobs` before and after
  `.venv/bin/python tools/control_clipper.py browser --fitur kirim-render --click 'Masukin antrean' --snapshot abis-klik.txt`.
  The count stays `0` **and** `abis-klik.txt` still shows the form, proving the page did
  not advance.
- **Prove the rejection came from the server.** `POST /render` with an empty `content`
  field directly. The response is `422` with
  `{"detail":[{"type":"missing","loc":["body","content"],...}]}`. This separates "the
  server refused" from "the click never landed" — an unchanged row count alone cannot.
- **A valid submit creates exactly one row.** Fill the content link and submit. Run
  `.venv/bin/python tools/control_clipper.py browser --fitur kirim-render --path / --fill 'content=https://www.youtube.com/watch?v=dQw4w9WgXcQ' --click 'Masukin antrean' --snapshot abis-submit.txt`.
  The queue DB goes from `0` to `1`, and the snapshot shows `Job #1` with
  `Mengharukan · waiting · punya verify` and `Nomor urut 1`. The visible page change and
  the DB row must both be checked: either one alone can lie.
- **Proof.** Keep `artifacts/kirim-render/form.png`, `form.txt`, `abis-klik.txt`, and
  `abis-submit.txt`. They survive `cleanup`.

## Gotchas

- **The browser never submits an empty form, so an unchanged row count proves nothing
  on its own.** The `content` field is `required`, so Chromium blocks the submit client
  side and the page never navigates. Always pair the click with a direct `POST /render`
  to show the server also refuses.
- **`POST /render` with a missing field returns a raw FastAPI `422` JSON body**, not an
  HTML page with a readable message. A user who reaches that path sees
  `{"detail":[{"type":"missing",...}]}`. Recorded as an observation, not fixed here:
  verification does not silently patch what it measures.
- Matching `name=content` against HTML source goes red while the field is healthy —
  `page.content()` serialises it as `name="content"`. Use `--expect-handle`.
- `/sehat` answers `200` before the queue tables exist. It is not a readiness signal;
  `launch` waits on `/` behind auth instead.
- Row counts assume an empty queue. A second submit in the same session shifts them.
- The outro field is disabled by JavaScript for clarity; the server-side refusal in
  `job.py` is the real guard. Do not treat the disabled attribute as the enforcement.
