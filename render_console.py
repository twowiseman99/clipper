"""Console render Clipper buat browser.

Keputusan operator yang ngebentuk file ini:
  - akses: TIM KECIL, akun dibikin manual, GA ADA halaman signup
  - antrean: orang kedua masuk antrean, dikasih nomor urut + perkiraan
  - dua preset: mengharukan (sedih) dan jedag jedug (jamet)
  - gambar outro cuma buat jamet
  - fix: teks bebas + rentang waktu, semua optional, fix = render ulang penuh
  - tombol upload disiapin TAPI MATI sampai ada akun YouTube
  - arah visual: DESIGN.md (gelap, teal #64BBA8, gold HEMAT, font sistem)

Yang ga ada di sini dan itu disengaja:
  - render TIDAK jalan di dalam request. Median 2,4 menit, p90 3,6 --
    lebih lama dari timeout browser mana pun. Request cuma naro job di
    antrean; yang ngerender render_worker.py.
  - ga ada progress bar persen. job.py ga lapor persen, jadi bar yang
    gerak sendiri itu bohong. Yang ditampilin: tahap + udah berapa lama.
  - ga ada JS bundle. Halaman nanya status pakai meta refresh, jadi
    halaman ini tetep ringan pas 2 core-nya dipake ffmpeg.

Jalanin:
    CLIPPER_CONSOLE_USERS="dalmi:rahasia,oden:rahasia2" \
        .venv/bin/python render_console.py
"""
import base64
import html
import json
import os
import time

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, FileResponse

import render_queue as q

HOST = os.environ.get("CLIPPER_CONSOLE_HOST", "127.0.0.1")
PORT = int(os.environ.get("CLIPPER_CONSOLE_PORT", "8001"))

# Akun dibikin manual, sesuai keputusan operator. Format:
#   "nama:sandi,nama2:sandi2"
# Ga ada default -- server nolak jalan kalau kosong, biar ga ada
# kemungkinan kebuka tanpa sandi gara-gara lupa set env.
_RAW_USERS = os.environ.get("CLIPPER_CONSOLE_USERS", "").strip()

PRESETS = {
    "sedih": {
        "label": "Mengharukan",
        "note": "ending melankolis, musik sedih/misterius/chill",
        "pakai_outro": False,
    },
    "jamet": {
        "label": "Jedag jedug",
        "note": "ending hentakan + kilat, musik hype",
        "pakai_outro": True,
    },
}


def _users():
    out = {}
    for bagian in _RAW_USERS.split(","):
        bagian = bagian.strip()
        if not bagian or ":" not in bagian:
            continue
        nama, sandi = bagian.split(":", 1)
        if nama.strip() and sandi:
            out[nama.strip()] = sandi
    return out


USERS = _users()

app = FastAPI(title="Clipper render console")


def _siapa(request: Request):
    """Nama user dari basic auth, atau None.

    Basic auth dipilih karena Caddy di depan udah ngurus HTTPS, dan tim
    kecil dengan akun manual ga butuh session store. Ga ada halaman
    login buat dirawat.
    """
    head = request.headers.get("authorization", "")
    if not head.lower().startswith("basic "):
        return None
    try:
        isi = base64.b64decode(head[6:]).decode("utf-8", "replace")
    except Exception:
        return None
    if ":" not in isi:
        return None
    nama, sandi = isi.split(":", 1)
    if USERS.get(nama) and USERS[nama] == sandi:
        return nama
    return None


def _minta_sandi():
    return Response(
        status_code=401,
        content="Butuh akun. Minta ke operator -- ga ada pendaftaran sendiri.",
        headers={"WWW-Authenticate": 'Basic realm="Clipper"'},
    )


def _e(v):
    return html.escape(str(v or ""), quote=True)


def _lama(detik):
    """Durasi buat dibaca manusia. Ga pernah balik angka palsu."""
    if detik is None:
        return "-"
    detik = int(detik)
    if detik < 60:
        return "%d detik" % detik
    menit = detik // 60
    sisa = detik % 60
    if sisa == 0:
        return "%d menit" % menit
    return "%d menit %d detik" % (menit, sisa)


STYLE = """
:root{
  --bg:#12100E; --panel:#1B1815; --line:#2E2A26;
  --ink:#F2EFE9; --ink-dim:#A49C91;
  --teal:#64BBA8; --gold:#FFD24A; --bad:#E2725B;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.55 ui-sans-serif,system-ui,-apple-system,sans-serif;
}
.wrap{max-width:52rem; margin:0 auto; padding:2rem 1.25rem 4rem}
h1{font-size:1.3rem; margin:0 0 .25rem; font-weight:620}
.sub{color:var(--ink-dim); font-size:.9rem; margin:0 0 2rem}
.panel{
  background:var(--panel); border:1px solid var(--line);
  border-radius:10px; padding:1.25rem; margin-bottom:1.25rem;
}
h2{font-size:.95rem; margin:0 0 1rem; font-weight:600; color:var(--teal)}
label{display:block; margin-bottom:1rem}
.lab{display:block; font-size:.85rem; color:var(--ink-dim); margin-bottom:.35rem}
input[type=text],input[type=url],select,textarea{
  width:100%; padding:.6rem .7rem; background:#141210; color:var(--ink);
  border:1px solid var(--line); border-radius:7px; font:inherit;
}
input:focus,select:focus,textarea:focus{
  outline:2px solid var(--teal); outline-offset:1px; border-color:var(--teal);
}
.row{display:flex; gap:.75rem; flex-wrap:wrap}
.row>*{flex:1 1 12rem}
.num{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
button{
  font:inherit; font-weight:560; padding:.65rem 1.1rem; border-radius:7px;
  border:1px solid var(--teal); background:var(--teal); color:#0E1413;
  cursor:pointer;
}
button:hover{background:#7ACBB9}
button.ghost{background:transparent; color:var(--ink); border-color:var(--line)}
button.ghost:hover{border-color:var(--ink-dim)}
button[disabled]{
  opacity:.5; cursor:not-allowed; background:transparent;
  color:var(--ink-dim); border-color:var(--line);
}
button[disabled]:hover{background:transparent}
.hint{font-size:.8rem; color:var(--ink-dim); margin-top:.3rem}
table{width:100%; border-collapse:collapse; font-size:.9rem}
th,td{text-align:left; padding:.5rem .4rem; border-bottom:1px solid var(--line)}
th{color:var(--ink-dim); font-weight:500; font-size:.8rem}
.tag{
  display:inline-block; padding:.1rem .5rem; border-radius:999px;
  font-size:.75rem; border:1px solid var(--line);
}
.tag.run{border-color:var(--gold); color:var(--gold)}
.tag.wait{color:var(--ink-dim)}
.tag.ok{border-color:var(--teal); color:var(--teal)}
.tag.bad{border-color:var(--bad); color:var(--bad)}
.err{
  border:1px solid var(--bad); color:#F6C8BF; background:#241714;
  padding:.75rem 1rem; border-radius:8px; margin-bottom:1.25rem;
  font-size:.9rem;
}
.warn{color:var(--gold); font-size:.85rem; margin:.5rem 0 0}
video{width:100%; max-width:22rem; border-radius:8px; border:1px solid var(--line)}
.meta{color:var(--ink-dim); font-size:.85rem}
a{color:var(--teal)}
@media(max-width:34rem){
  .wrap{padding:1.25rem .9rem 3rem}
  button{width:100%; padding:.8rem}
  .row>*{flex:1 1 100%}
}
"""


def _halaman(judul, isi, refresh=0):
    meta = ('<meta http-equiv="refresh" content="%d">' % refresh) if refresh else ""
    return HTMLResponse(
        "<!doctype html><html lang=id><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        "%s<title>%s</title><style>%s</style></head><body><div class=wrap>%s"
        "</div></body></html>" % (meta, _e(judul), STYLE, isi)
    )


def _form(siapa, error=""):
    opsi = "".join(
        '<option value="%s">%s — %s</option>' % (k, _e(v["label"]), _e(v["note"]))
        for k, v in PRESETS.items()
    )
    conn = q.connect()
    nunggu = q.waiting_count(conn)
    antrean_nota = (
        '<p class=hint>Antrean kosong, render lu mulai langsung.</p>'
        if nunggu == 0 else
        '<p class=hint>Ada <span class=num>%d</span> job nunggu di depan. '
        'Perkiraan mulai: <span class=num>%s</span>.</p>'
        % (nunggu, _lama(nunggu * q.MEDIAN_RENDER_SEC))
    )
    err = ('<div class=err>%s</div>' % _e(error)) if error else ""
    return """
<h1>Clipper</h1>
<p class=sub>Masuk sebagai <span class=num>%s</span> · satu render sekali jalan</p>
%s
<form method=post action=/render class=panel>
  <h2>Render klip baru</h2>
  <label><span class=lab>Preset</span>
    <select name=preset>%s</select></label>
  <label><span class=lab>Link isi — video yang dipotong jadi klip</span>
    <input type=url name=content required placeholder="https://..."></label>
  <label><span class=lab>Link hook — b-roll pembuka (optional)</span>
    <input type=url name=opening placeholder="https://..."></label>
  <label><span class=lab>Gambar outro — cuma kepakai di Jedag jedug</span>
    <input type=text name=portrait placeholder="path gambar di server">
    <span class=hint>Dikasih ke preset Mengharukan bakal ditolak job.py sendiri.</span></label>
  <label><span class=lab>Konteks — siapa yang ngomong, soal apa (optional)</span>
    <textarea name=context rows=2></textarea>
    <span class=hint>Dipake buat milih b-roll dan nulis judul. Kosong = diambil dari transkrip.</span></label>
  %s
  <button type=submit>Masukin antrean</button>
</form>
""" % (_e(siapa), err, opsi, antrean_nota)


def _tabel(jobs):
    if not jobs:
        return "<p class=meta>Belum ada render.</p>"
        
    baris = []
    for j in jobs:
        st = j["status"]
        kelas = {"running": "run", "waiting": "wait", "done": "ok",
                 "failed": "bad", "canceled": "wait"}.get(st, "wait")
        baris.append(
            "<tr><td class=num><a href=/job/%d>#%d</a></td>"
            "<td>%s</td><td>%s</td>"
            "<td><span class='tag %s'>%s</span></td></tr>"
            % (j["id"], j["id"], _e(PRESETS.get(j["preset"], {}).get("label", j["preset"])),
               _e(j["owner"]), kelas, _e(st))
        )
    return (
        "<table><tr><th>Job</th><th>Preset</th><th>Siapa</th><th>Keadaan</th></tr>"
        + "".join(baris) + "</table>"
    )


@app.get("/")
def index(request: Request):
    siapa = _siapa(request)
    if not siapa:
        return _minta_sandi()
    conn = q.connect()
    q.reap_stale(conn)
    isi = _form(siapa) + (
        '<div class=panel><h2>Render terakhir</h2>%s</div>' % _tabel(q.recent(conn, limit=12))
    )
    return _halaman("Clipper", isi)


@app.post("/render")
def mulai(request: Request,
          preset: str = Form(...),
          content: str = Form(...),
          opening: str = Form(""),
          portrait: str = Form(""),
          context: str = Form("")):
    siapa = _siapa(request)
    if not siapa:
        return _minta_sandi()
    if preset not in PRESETS:
        return _halaman("Clipper", _form(siapa, "Preset '%s' ga ada." % preset))
    if portrait and not PRESETS[preset]["pakai_outro"]:
        return _halaman("Clipper", _form(
            siapa,
            "Gambar outro cuma kepakai di preset Jedag jedug. Preset "
            "Mengharukan dikasih gambar outro bakal ditolak job.py."))
    params = {"content": content.strip(), "opening": opening.strip(),
              "portrait": portrait.strip(), "context": context.strip()}
    conn = q.connect()
    job_id = q.submit(conn, siapa, preset, params)
    return RedirectResponse("/job/%d" % job_id, status_code=303)


@app.get("/job/{job_id}")
def lihat(request: Request, job_id: int):
    siapa = _siapa(request)
    if not siapa:
        return _minta_sandi()
    conn = q.connect()
    q.reap_stale(conn)
    j = q.get(conn, job_id)
    if not j:
        return _halaman("Ga ketemu", "<h1>Job #%d ga ada</h1>"
                        "<p><a href=/>Balik</a></p>" % job_id)

    st = j["status"]
    refresh = 0
    bagian = []

    if st == "waiting":
        pos = q.position(conn, job_id)
        eta = q.eta_seconds(conn, job_id)
        refresh = 10
        bagian.append(
            "<div class=panel><h2>Nunggu antrean</h2>"
            "<p>Nomor urut <span class=num>%d</span>. "
            "Perkiraan mulai <span class=num>%s</span> lagi.</p>"
            "<p class=hint>Perkiraan pakai median 2,4 menit dari 257 render. "
            "Render terlama yang pernah keukur 6,6 menit, jadi ini bisa "
            "lebih lama.</p>"
            "<form method=post action=/batal>"
            "<input type=hidden name=job_id value=%d>"
            "<button class=ghost type=submit>Batalin</button></form></div>"
            % (pos, _lama(eta), job_id))
    elif st == "running":
        jalan = time.time() - (j["started_at"] or time.time())
        refresh = 10
        bagian.append(
            "<div class=panel><h2>Lagi dirender</h2>"
            "<p>Tahap: <span class=num>%s</span> · udah jalan "
            "<span class=num>%s</span>.</p>"
            "<p class=hint>Ga ada bar persen di sini: job.py ga lapor persen, "
            "jadi bar yang gerak sendiri bakal bohong. Median 2,4 menit.</p>"
            "<p class=hint>Halaman bisa kerasa lambat sekarang — ffmpeg makan "
            "dua core yang sama.</p></div>"
            % (_e(j["stage"] or "mulai"), _lama(jalan)))
    elif st == "done":
        warn = json.loads(j["warnings"] or "[]")
        wbox = ""
        if warn:
            wbox = "<p class=warn>%d catatan dari render:</p><ul class=warn>%s</ul>" % (
                len(warn), "".join("<li>%s</li>" % _e(w) for w in warn))
        bagian.append(
            "<div class=panel><h2>Kelar</h2>"
            "<video controls preload=metadata src=/file/%d></video>"
            "<p class=meta>Lama render: <span class=num>%s</span></p>%s"
            "<p><a href=/file/%d download>Unduh file</a></p></div>"
            % (job_id, _lama((j["finished_at"] or 0) - (j["started_at"] or 0)),
               wbox, job_id))
        bagian.append(_panel_fix(j))
        bagian.append(
            "<div class=panel><h2>Kirim ke YouTube</h2>"
            "<button disabled>Upload — belum ada akun</button>"
            "<p class=hint>Tombol ini mati karena preflight.upload_accounts() "
            "masih kosong. Dinyalain pas akun YouTube udah kepasang.</p></div>")
    elif st == "failed":
        bagian.append(
            "<div class=panel><h2>Gagal</h2><div class=err>%s</div>"
            "<p><a href=/>Coba lagi dari form</a></p></div>" % _e(j["error"]))
    else:
        bagian.append("<div class=panel><h2>Dibatalin</h2>"
                      "<p><a href=/>Balik ke form</a></p></div>")

    kepala = ("<h1>Job #%d</h1><p class=sub>%s · %s · punya "
              "<span class=num>%s</span></p>"
              % (job_id, _e(PRESETS.get(j["preset"], {}).get("label", j["preset"])),
                 _e(st), _e(j["owner"])))
    return _halaman("Job #%d" % job_id,
                    kepala + "".join(bagian) + "<p><a href=/>Balik</a></p>",
                    refresh=refresh)


def _panel_fix(j):
    """Form fix: teks bebas + rentang waktu, semua optional.

    Fix = render ulang penuh, bukan tambal. Itu keputusan operator dan
    labelnya harus bilang begitu, biar ga ada yang ngira ini cepet.
    """
    p = json.loads(j["params"])
    return """
<form method=post action=/fix class=panel>
  <h2>Ada yang ngaco? Render ulang</h2>
  <input type=hidden name=job_id value=%d>
  <label><span class=lab>Apa yang mau dibenerin (optional)</span>
    <textarea name=catatan rows=2 placeholder="misal: b-roll menit 1 ga nyambung"></textarea></label>
  <div class=row>
    <label><span class=lab>Dari menit (optional)</span>
      <input type=text name=dari class=num placeholder="1:20"></label>
    <label><span class=lab>Sampai menit (optional)</span>
      <input type=text name=sampai class=num placeholder="1:45"></label>
  </div>
  <button class=ghost type=submit>Render ulang</button>
  <p class=hint>Ini render ULANG penuh, bukan tambal bagian itu aja — jadi
  makan waktu sama kayak render pertama (median 2,4 menit) dan masuk antrean
  dari belakang.</p>
</form>""" % j["id"]


@app.post("/fix")
def fix(request: Request,
        job_id: int = Form(...),
        catatan: str = Form(""),
        dari: str = Form(""),
        sampai: str = Form("")):
    siapa = _siapa(request)
    if not siapa:
        return _minta_sandi()
    conn = q.connect()
    lama = q.get(conn, job_id)
    if not lama:
        return RedirectResponse("/", status_code=303)
    params = json.loads(lama["params"])
    params["fix_catatan"] = catatan.strip()
    params["fix_dari"] = dari.strip()
    params["fix_sampai"] = sampai.strip()
    baru = q.submit(conn, siapa, lama["preset"], params)
    return RedirectResponse("/job/%d" % baru, status_code=303)


@app.post("/batal")
def batal(request: Request, job_id: int = Form(...)):
    siapa = _siapa(request)
    if not siapa:
        return _minta_sandi()
    conn = q.connect()
    q.cancel(conn, job_id, siapa)
    return RedirectResponse("/job/%d" % job_id, status_code=303)


@app.get("/file/{job_id}")
def file(request: Request, job_id: int):
    siapa = _siapa(request)
    if not siapa:
        return _minta_sandi()
    conn = q.connect()
    j = q.get(conn, job_id)
    if not j or not j["out_path"] or not os.path.exists(j["out_path"]):
        return Response(status_code=404, content="File ga ada")
    return FileResponse(j["out_path"], media_type="video/mp4")


@app.get("/sehat")
def sehat():
    conn = q.connect()
    return {"nunggu": q.waiting_count(conn), "user_kepasang": len(USERS)}


if __name__ == "__main__":
    import uvicorn

    if not USERS:
        raise SystemExit(
            "CLIPPER_CONSOLE_USERS kosong. Akun dibikin manual -- ga ada\n"
            "pendaftaran sendiri, dan server ga mau jalan tanpa sandi.\n"
            'Contoh: CLIPPER_CONSOLE_USERS="dalmi:sandi1,oden:sandi2"')
    print("console on http://%s:%d (%d akun)" % (HOST, PORT, len(USERS)))
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
