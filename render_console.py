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
import hmac
import html
import json
import os
import time

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response, FileResponse

import campaigns as camp
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
    # `==` pada string itu short-circuit: dia balik False di karakter
    # pertama yang beda, jadi lama bandinginnya bocorin berapa karakter
    # depan yang udah bener. Di LAN itu teoretis; begitu console kebuka ke
    # internet lewat tunnel, itu jadi jalan nebak sandi per karakter.
    # compare_digest waktunya tetap.
    benar = USERS.get(nama)
    if benar and hmac.compare_digest(benar, sandi):
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
nav{display:flex; gap:.4rem; margin:0 0 1.5rem; flex-wrap:wrap}
nav a{
  text-decoration:none; padding:.45rem .9rem; border-radius:999px;
  border:1px solid var(--line); color:var(--ink-dim); font-size:.9rem;
}
nav a.on{border-color:var(--teal); color:var(--teal)}
.skor{font-weight:650; color:var(--teal)}
.merah{color:var(--bad)}
td.r,th.r{text-align:right}
.chip{
  display:inline-block; padding:.05rem .45rem; border-radius:4px;
  font-size:.72rem; border:1px solid var(--line); color:var(--ink-dim);
  margin-right:.2rem;
}
.garap{border-color:var(--teal); color:var(--teal)}
.lewat{opacity:.45}
tr.dilewat td{opacity:.4}
.aset li{margin-bottom:.4rem}
input[type=file]{
  width:100%; padding:.5rem; background:#141210; color:var(--ink-dim);
  border:1px dashed var(--line); border-radius:7px; font:inherit;
  font-size:.85rem;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
/* Tombol bawaan browser di file input itu abu terang kotak -- di tema gelap
   dia jadi benda paling mencolok setelah tombol utama dan kelihatan kayak
   CSS gagal muat, bukan kontrol yang disengaja. */
input[type=file]::file-selector-button{
  font:inherit; font-size:.82rem; margin-right:.6rem; cursor:pointer;
  padding:.3rem .7rem; border-radius:5px; color:var(--ink);
  background:#1E1B18; border:1px solid var(--line);
}
input[type=file]::file-selector-button:hover{border-color:var(--teal)}
/* Label preset panjang kepotong TENGAH HURUF di lebar HP (diukur 390px:
   "ending melankoli" langsung nempel chevron). padding-right nyediain ruang
   buat chevron, ellipsis bikin potongnya kebaca sebagai sengaja. */
select{
  text-overflow:ellipsis; white-space:nowrap; overflow:hidden;
  padding-right:2rem;
}
.desc{
  font-size:.88rem; color:var(--ink-dim); white-space:pre-wrap;
  max-height:11rem; overflow:auto;
}
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
    med_form, n_form = q.median_render_sec(conn)
    antrean_nota = (
        '<p class=hint>Antrean kosong, render lu mulai langsung.</p>'
        if nunggu == 0 else
        '<p class=hint>Ada <span class=num>%d</span> job nunggu di depan. '
        'Perkiraan mulai: <span class=num>%s</span>.</p>'
        % (nunggu, _lama(nunggu * med_form))
    )
    err = ('<div class=err>%s</div>' % _e(error)) if error else ""
    return """
<h1>Clipper</h1>
<p class=sub>Masuk sebagai <span class=num>%s</span> · satu render sekali jalan</p>
%s
<form method=post action=/render class=panel enctype="multipart/form-data">
  <h2>Render klip baru</h2>
  <label><span class=lab>Preset</span>
    <select name=preset id=preset>%s</select></label>
  <label><span class=lab>Link isi — video yang dipotong jadi klip</span>
    <input type=url name=content required placeholder="https://..."></label>
  <label><span class=lab>Link hook — b-roll pembuka (optional)</span>
    <input type=url name=opening placeholder="https://..."></label>
  <label id=lbl-outro><span class=lab>Gambar outro (optional)</span>
    <input type=file name=image accept="image/*" id=outro
           aria-describedby=hint-outro>
    <span class=hint id=hint-outro role=status></span></label>
  <label><span class=lab>BGM (optional)</span>
    <input type=file name=bgm accept="audio/*">
    <span class=hint>Kosongin = musik dipilih dari mood klip pakai stok di
    background_music/. File yang lu upload dipakai apa adanya, jadi aturan
    "lagu hype ga boleh di klip duka" cuma bisa ngasih peringatan, ga bisa
    nolak. Mood dibaca dari nama file (<code>emotional_piano.mp3</code>).</span></label>
  <label><span class=lab>Konteks — siapa yang ngomong, soal apa (optional)</span>
    <textarea name=context rows=2></textarea>
    <span class=hint>Dipake buat milih b-roll dan nulis judul. Kosong = diambil dari transkrip.</span></label>
  %s
  <button type=submit>Masukin antrean</button>
</form>
<script>
/* Field gambar outro dulu selalu nyala sambil labelnya nyuruh jangan dipakai.
   Sekarang statusnya ngikut preset, jadi aturannya KELIHATAN bukan dibaca.
   Server TETAP nolak (400): JS bisa mati dan POST bisa dateng tanpa halaman
   ini. Lapis kejelasan, bukan lapis keamanan. */
(function () {
  var PAKAI = %s;
  var sel = document.getElementById("preset");
  var inp = document.getElementById("outro");
  var hint = document.getElementById("hint-outro");
  var lbl = document.getElementById("lbl-outro");
  if (!sel || !inp || !hint || !lbl) return;
  function sync() {
    var boleh = PAKAI[sel.value] === true;
    inp.disabled = !boleh;
    /* Yang diredupin cuma KONTROLnya, bukan hint-nya. Pertama kali gua
       redupin seluruh label dan hasilnya kebalik: satu-satunya kalimat yang
       ngasih tau cara ngidupin field itu jadi teks paling pudar di halaman. */
    inp.style.opacity = boleh ? "" : ".5";
    lbl.querySelector(".lab").style.opacity = boleh ? "" : ".6";
    if (boleh) {
      hint.textContent = "Dipakai jadi frame penutup klip.";
      hint.style.color = "";
    } else {
      hint.textContent = "Preset " + sel.options[sel.selectedIndex].text.split(" — ")[0]
        + " ga pakai gambar outro, jadi field ini mati. Pilih Jedag jedug buat ngisinya.";
      hint.style.color = "var(--gold)";
      inp.value = "";
    }
  }
  sel.addEventListener("change", sync);
  sync();
})();
</script>
""" % (_e(siapa), err, opsi, antrean_nota,
       json.dumps({k: v["pakai_outro"] for k, v in PRESETS.items()}))


def _dasar_median(med, n):
    """Kalimat estimasi yang nyebut DARI BERAPA render angkanya diambil.

    Versi lama nulis "median 2,4 menit dari 257 render" -- dua angka yang
    dua-duanya ga ada di box ini (konstanta dari mesin lain, dan DB cuma
    punya 2 render kelar). Angka yang ngaku punya dasar 257 sampel lebih
    berbahaya daripada ga ngasih angka, karena dia ngundang dipercaya.
    """
    if n == 0:
        return ("Belum ada render kelar di box ini, jadi perkiraannya pakai "
                "angka bawaan %s. Bakal makin akurat sendiri." % _lama(med))
    if n < 3:
        return ("Baru %d render kelar di box ini — belum cukup buat median, "
                "jadi ini masih angka bawaan %s." % (n, _lama(med)))
    return ("Perkiraan pakai median %s dari %d render yang kelar di box ini. "
            "Tiap render baru bikin angka ini makin bener." % (_lama(med), n))


def _tabel(jobs):
    if not jobs:
        # R-27: an empty state names the cause and the one action that fills
        # it. "Belum ada render." passes the letter of "has an empty state"
        # and tells a first-time user nothing: not why the table is empty,
        # not what to do, not how long the thing they start will take.
        return ("<p class=meta>Belum ada render di box ini.</p>"
                "<p class=hint>Isi form di atas dan klik Render — hasilnya "
                "muncul di sini. Halaman ini aman ditinggal: rendernya jalan "
                "di proses terpisah, jadi nutup tab ga ngebatalin.</p>")

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


def _nav(aktif):
    tab = (("render", "/", "Render"), ("campaign", "/campaign", "Campaign"))
    return "<nav>%s</nav>" % "".join(
        '<a class="%s" href="%s">%s</a>'
        % ("on" if k == aktif else "", u, _e(label)) for k, u, label in tab)


def _rp(n):
    return "Rp" + format(int(n or 0), ",d").replace(",", ".")


# ------------------------------------------------------------ papan campaign

def _papan(rows, saring, umur):
    """Tabel campaign. Urutan SKOR = cpm x sisa budget (pilihan operator).

    Kolomnya nyebut `Rp / 1.000 views` dan bukan "CPM", karena field yang
    namanya `rate_per_million` di API itu rupiah per SERIBU views -- udah
    dicek ke halaman campaign-nya. Nulis "CPM" doang di header bikin orang
    ngitung pakai arti yang salah dan kelirunya 1000x.
    """
    if not rows:
        return ("<p class=meta>Belum ada campaign di papan. Klik "
                "<b>Tarik ulang</b> di atas.</p>")
    baris = []
    for r in rows:
        kelas = " class=dilewat" if r["pick"] == "lewat" else ""
        tanda = ""
        if r["pick"] == "garap":
            tanda = "<span class='chip garap'>garap</span>"
        elif r["pick"] == "lewat":
            tanda = "<span class='chip lewat'>lewat</span>"
        aset = ("<span class=chip>%d aset</span>" % r["n_asset"]) if r["n_asset"] else ""
        mv = "?" if r["min_views"] is None else format(r["min_views"], ",d").replace(",", ".")
        baris.append(
            "<tr%s><td class='num r skor'>%s</td>"
            "<td class='num r'>%s</td><td class='num r'>%s</td>"
            "<td class='num r%s'>%s</td>"
            "<td><a href='/campaign/%s'>%s</a><br>"
            "<span class=meta>%s %s %s</span></td></tr>"
            % (kelas, format(r["score"], ",d").replace(",", "."),
               _rp(r["cpm"]),
               "?" if r["budget_left"] is None else "%d%%" % r["budget_left"],
               " merah" if r["min_views_merah"] else "", mv,
               _e(r["slug"]), _e(r["title"][:60]),
               _e(r["brand"][:26]), tanda, aset))
    pil = []
    for nama, nilai in (("Aktif", ""), ("Digarap", "garap"),
                        ("Dilewat", "lewat"), ("Semua status", "semua")):
        on = " class=on" if saring == nilai else ""
        pil.append("<a%s href='/campaign?saring=%s'>%s</a>"
                   % (on, nilai, _e(nama)))
    return (
        "<nav>%s</nav>"
        "<form method=post action=/campaign/refresh style='margin-bottom:1rem'>"
        "<button class=ghost type=submit>Tarik ulang dari marketplace</button>"
        "<span class=hint> terakhir: %s</span></form>"
        "<table><tr><th class=r>Skor</th><th class=r>Rp / 1.000 views</th>"
        "<th class=r>sisa budget</th><th class=r>min views</th>"
        "<th>Campaign</th></tr>%s</table>"
        "<p class=hint>Urutan = <b>skor</b> (Rp/1.000 views × sisa budget). "
        "CPM mentah nipu: campaign dengan rate tertinggi di marketplace "
        "(Rp15.000) sisa budgetnya cuma 6%%, jadi rate-nya ga bisa diambil. "
        "Angka merah di min views = lantai di atas 10.000, klip di bawah itu "
        "ga dibayar sama sekali.</p>"
        "<p class=hint>Rp/1.000 views, BUKAN per sejuta: field API-nya "
        "ketulis <code>rate_per_million</code> tapi halaman campaign-nya "
        "nulis \"Rp10.000 / 1K views\" buat angka yang sama. Namanya bohong, "
        "angkanya per seribu.</p>"
        % ("".join(pil), _e(umur), "".join(baris)))


def _umur_refresh(conn):
    t = camp.last_refresh(conn)
    if not t:
        return "BELUM PERNAH ditarik"
    lalu = time.time() - t
    return "%s lalu (%s)" % (_lama(lalu),
                             time.strftime("%d %b %H:%M", time.localtime(t)))


@app.get("/campaign")
def papan(request: Request, saring: str = ""):
    siapa = _siapa(request)
    if not siapa:
        return _minta_sandi()
    conn = camp.connect()
    rows = camp.board(
        conn,
        hanya_aktif=saring in ("", "garap", "lewat") and saring != "semua",
        state=saring if saring in ("garap", "lewat") else None,
        limit=300)
    if saring == "semua":
        rows = camp.board(conn, hanya_aktif=False, limit=300)
    isi = (_nav("campaign")
           + "<h1>Campaign</h1>"
           + "<p class=sub>Masuk sebagai <span class=num>%s</span> · "
             "%d campaign kelihatan</p>" % (_e(siapa), len(rows))
           + "<div class=panel>%s</div>" % _papan(rows, saring,
                                                  _umur_refresh(conn)))
    return _halaman("Campaign", isi)


@app.post("/campaign/refresh")
def papan_refresh(request: Request):
    siapa = _siapa(request)
    if not siapa:
        return _minta_sandi()
    conn = camp.connect()
    try:
        camp.refresh(conn)
    except Exception as exc:
        # Marketplace ga kebaca itu keadaan yang wajar (mereka bisa down,
        # kotak ini bisa kena rate limit). Papan lama TETEP ditampilin dan
        # umur refresh-nya keliatan basi -- itu jujur. Yang ga boleh:
        # halaman kosong tanpa sebab.
        rows = camp.board(conn, limit=300)
        return _halaman("Campaign", _nav("campaign")
                        + "<h1>Campaign</h1>"
                        + "<div class=err>Marketplace ga kebaca: %s</div>"
                        % _e("%s: %s" % (type(exc).__name__, exc))
                        + "<div class=panel>%s</div>"
                        % _papan(rows, "", _umur_refresh(conn)))
    return RedirectResponse("/campaign", status_code=303)


def _aset_panel(c, aset):
    def daftar(kind, kosong):
        pilih = [a for a in aset if a["kind"] == kind]
        if not pilih:
            return "<p class=meta>%s</p>" % _e(kosong)
        li = []
        for a in pilih:
            if kind == "video_link":
                badan = "<a href='%s' rel=noreferrer>%s</a>" % (
                    _e(a["value"]), _e(a["value"][:70]))
            else:
                badan = "<span class=num>%s</span>" % _e(
                    os.path.basename(a["value"]))
            if not a["ada"]:
                badan += " <span class='chip merah'>file ilang</span>"
            li.append(
                "<li>%s %s<form method=post action=/campaign/%s/aset/hapus "
                "style='display:inline'>"
                "<input type=hidden name=asset_id value=%d>"
                "<button class=ghost type=submit "
                "style='padding:.1rem .5rem;font-size:.75rem'>hapus</button>"
                "</form></li>"
                % (badan,
                   ("<span class=meta>%s</span>" % _e(a["label"]))
                   if a["label"] else "",
                   _e(c["slug"]), a["id"]))
        return "<ul class=aset>%s</ul>" % "".join(li)

    return """
<div class=panel>
  <h2>Bahan buat campaign ini</h2>
  <h3 style="font-size:.85rem;color:var(--ink-dim)">Link video</h3>
  %s
  <h3 style="font-size:.85rem;color:var(--ink-dim)">Gambar</h3>
  %s
  <h3 style="font-size:.85rem;color:var(--ink-dim)">BGM</h3>
  %s
  <form method=post action="/campaign/%s/aset" enctype="multipart/form-data"
        style="margin-top:1.25rem;border-top:1px solid var(--line);padding-top:1rem">
    <label><span class=lab>Tambah link video (YouTube / Google Drive)</span>
      <input type=url name=video_link placeholder="https://..."></label>
    <label><span class=lab>Upload gambar (jpg/png/webp)</span>
      <input type=file name=image accept="image/*"></label>
    <label><span class=lab>Upload BGM (mp3/wav/m4a)</span>
      <input type=file name=bgm accept="audio/*">
      <span class=hint>Mood dibaca dari nama file (misal
      <code>emotional_piano.mp3</code>). Nama tanpa mood tetep kepakai —
      cuma peringatan tabrakan registernya yang ga bisa dikasih.</span></label>
    <label><span class=lab>Catatan (optional)</span>
      <input type=text name=label placeholder="misal: dari brand, wajib dipakai"></label>
    <button type=submit>Simpan bahan</button>
    <p class=hint>Disimpen di <span class=num>assets/campaign/%s/</span> —
    DI LUAR <span class=num>media/</span> dan <span class=num>jobs/</span>
    yang dibersihin auto-clean tiap jam 5 pagi. File yang lu upload sendiri
    ga bisa diunduh ulang, jadi dia ga boleh punya umur 24 jam.</p>
  </form>
</div>""" % (daftar("video_link", "Belum ada link video."),
             daftar("image", "Belum ada gambar."),
             daftar("bgm", "Belum ada BGM. Tanpa ini, musik dipilih dari "
                           "mood klip pakai stok di background_music/."),
             _e(c["slug"]), _e(camp.safe_slug(c["slug"])))


def _render_panel(c, aset):
    """Form render yang bahannya diambil dari aset campaign ini."""
    vids = [a for a in aset if a["kind"] == "video_link"]
    imgs = [a for a in aset if a["kind"] == "image" and a["ada"]]
    bgms = [a for a in aset if a["kind"] == "bgm" and a["ada"]]
    if not vids:
        return ("<div class=panel><h2>Render klip</h2>"
                "<p class=meta>Belum bisa: campaign ini belum punya link "
                "video. Tambahin di panel bahan dulu.</p></div>")
    opsi_preset = "".join(
        '<option value="%s">%s — %s</option>'
        % (k, _e(v["label"]), _e(v["note"])) for k, v in PRESETS.items())
    opsi_vid = "".join(
        '<option value="%s">%s</option>' % (_e(a["value"]), _e(a["value"][:70]))
        for a in vids)
    opsi_img = "<option value=''>— ga pakai gambar outro —</option>" + "".join(
        '<option value="%s">%s</option>'
        % (_e(a["value"]), _e(os.path.basename(a["value"]))) for a in imgs)
    opsi_bgm = ("<option value=''>— pilih otomatis dari mood klip —</option>"
                + "".join(
                    '<option value="%s">%s</option>'
                    % (_e(a["value"]), _e(os.path.basename(a["value"])))
                    for a in bgms))
    return """
<form method=post action=/render class=panel>
  <h2>Render klip buat campaign ini</h2>
  <input type=hidden name=campaign value="%s">
  <label><span class=lab>Preset</span>
    <select name=preset>%s</select></label>
  <label><span class=lab>Link isi — video yang dipotong</span>
    <select name=content>%s</select></label>
  <label><span class=lab>Link hook — b-roll pembuka (optional)</span>
    <input type=url name=opening placeholder="https://..."></label>
  <label><span class=lab>Gambar outro — cuma kepakai di Jedag jedug</span>
    <select name=portrait>%s</select></label>
  <label><span class=lab>BGM</span>
    <select name=bgm_file>%s</select>
    <span class=hint>BGM yang dipilih tangan NGELEWATIN pemilihan lewat
    mood, jadi aturan "lagu hype ga boleh di klip duka" ga bisa nolak
    di sini — kalau nama filenya bentrok sama mood klip, render-nya jalan
    tapi bawa peringatan.</span></label>
  <label><span class=lab>Konteks — siapa yang ngomong, soal apa</span>
    <textarea name=context rows=2>%s</textarea>
    <span class=hint>Udah diisi dari brief campaign. Edit kalau klip ini
    soal bagian lain.</span></label>
  <button type=submit>Masukin antrean</button>
</form>""" % (_e(c["slug"]), opsi_preset, opsi_vid, opsi_img, opsi_bgm,
              _e((c["description"] or "")[:400]))


@app.get("/campaign/{slug}")
def campaign(request: Request, slug: str):
    siapa = _siapa(request)
    if not siapa:
        return _minta_sandi()
    conn = camp.connect()
    c = camp.get(conn, slug)
    if not c:
        return _halaman("Ga ketemo", _nav("campaign")
                        + "<h1>Campaign ga ada di papan</h1>"
                        "<p>Mungkin belum pernah ditarik. "
                        "<a href=/campaign>Balik ke papan</a></p>")
    aset = camp.assets(conn, slug)
    qconn = q.connect()
    jobs = q.for_campaign(qconn, slug, limit=12)

    sisa = "?" if c["budget_left"] is None else "%d%%" % c["budget_left"]
    mv = "?" if c["min_views"] is None else format(c["min_views"], ",d").replace(",", ".")
    kepala = (
        "<h1>%s</h1><p class=sub>%s · <a href='%s' rel=noreferrer>buka di "
        "marketplace</a></p>"
        "<div class=panel><table>"
        "<tr><th>Skor</th><td class=num><span class=skor>%s</span></td></tr>"
        "<tr><th>Rp / 1.000 views</th><td class=num>%s <span class=meta>(%s)"
        "</span></td></tr>"
        "<tr><th>Sisa budget</th><td class=num>%s</td></tr>"
        "<tr><th>Min views</th><td class='num%s'>%s</td></tr>"
        "<tr><th>Min durasi</th><td class=num>%s detik</td></tr>"
        "<tr><th>Platform</th><td>%s</td></tr>"
        "<tr><th>Status</th><td>%s · %s · %s</td></tr>"
        "<tr><th>Hashtag</th><td class=num>%s</td></tr>"
        "</table><h2 style='margin-top:1rem'>Brief</h2>"
        "<div class=desc>%s</div></div>"
        % (_e(c["title"]), _e(c["brand"]), _e(c["url"]),
           format(c["score"], ",d").replace(",", "."),
           _rp(c["cpm"]), _e(c["cpm_source"] or "ga ada rate"),
           sisa,
           " merah" if c["min_views_merah"] else "", mv,
           c["min_seconds"] if c["min_seconds"] is not None else "?",
           _e(", ".join(c["platform"]) or "-"),
           _e(c["status"]), _e(c["campaign_type"]), _e(c["content_type"]),
           _e(" ".join("#" + h for h in c["hashtags"]) or "-"),
           _e(c["description"] or "(brief kosong di daftar API)")))

    pilih = (
        "<form method=post action='/campaign/%s/pick' class=panel>"
        "<h2>Keputusan</h2><p class=meta>Sekarang: <b>%s</b>%s</p>"
        "<label><span class=lab>Catatan (optional)</span>"
        "<input type=text name=note value=\"%s\"></label>"
        "<div class=row>"
        "<button name=state value=garap type=submit>Garap</button>"
        "<button class=ghost name=state value=lewat type=submit>Lewat</button>"
        "<button class=ghost name=state value=batal type=submit>Hapus "
        "tanda</button></div></form>"
        % (_e(slug), _e(c["pick"] or "belum diputusin"),
           (" oleh %s" % _e(c["pick_who"])) if c["pick_who"] else "",
           _e(c["pick_note"] or "")))

    isi = (_nav("campaign") + kepala + pilih + _aset_panel(c, aset)
           + _render_panel(c, aset)
           + "<div class=panel><h2>Render buat campaign ini</h2>%s</div>"
             % _tabel(jobs)
           + "<p><a href=/campaign>Balik ke papan</a></p>")
    return _halaman(c["title"][:40], isi)


@app.post("/campaign/{slug}/pick")
def campaign_pick(request: Request, slug: str,
                  state: str = Form(...), note: str = Form("")):
    siapa = _siapa(request)
    if not siapa:
        return _minta_sandi()
    conn = camp.connect()
    camp.pick(conn, slug, None if state == "batal" else state,
              who=siapa, note=note.strip())
    return RedirectResponse("/campaign/%s" % slug, status_code=303)


# Batas ukuran upload. Gambar outro dan satu track BGM ga pernah segede ini;
# yang ditahan itu orang nyoba naro video lewat kolom gambar.
MAX_UPLOAD_MB = float(os.environ.get("CLIPPER_MAX_UPLOAD_MB", "25"))


@app.post("/campaign/{slug}/aset")
async def campaign_aset(request: Request, slug: str,
                        video_link: str = Form(""),
                        label: str = Form(""),
                        image: UploadFile = File(None),
                        bgm: UploadFile = File(None)):
    siapa = _siapa(request)
    if not siapa:
        return _minta_sandi()
    conn = camp.connect()
    if not camp.get(conn, slug):
        return RedirectResponse("/campaign", status_code=303)

    salah = []
    link = (video_link or "").strip()
    if link:
        # Link yang ga didukung ditolak DI SINI, bukan 3 menit kemudian di
        # dalam render. fetch.py cuma ngerti dua host.
        if not (link.startswith("http://") or link.startswith("https://")):
            salah.append("link video harus mulai http:// atau https://")
        elif not any(h in link for h in ("youtube.com", "youtu.be",
                                         "drive.google.com")):
            salah.append("link video cuma didukung YouTube atau Google Drive "
                         "(fetch.py cuma punya dua jalur itu)")
        else:
            camp.add_asset(conn, slug, "video_link", link,
                           label=label.strip(), who=siapa)

    for f, kind in ((image, "image"), (bgm, "bgm")):
        if not f or not f.filename:
            continue
        isi = await f.read()
        if not isi:
            salah.append("%s: filenya kosong" % kind)
            continue
        if len(isi) > MAX_UPLOAD_MB * 1e6:
            salah.append("%s: %0.1f MB lewat batas %0.0f MB"
                         % (kind, len(isi) / 1e6, MAX_UPLOAD_MB))
            continue
        path = camp.save_upload(slug, kind, f.filename, isi)
        camp.add_asset(conn, slug, kind, path, label=label.strip(), who=siapa)

    if salah:
        c = camp.get(conn, slug)
        return _halaman(
            "Campaign",
            _nav("campaign")
            + "<h1>%s</h1>" % _e(c["title"])
            + "<div class=err>%s</div>" % _e(" · ".join(salah))
            + _aset_panel(c, camp.assets(conn, slug))
            + "<p><a href='/campaign/%s'>Balik ke campaign</a></p>" % _e(slug))
    return RedirectResponse("/campaign/%s" % slug, status_code=303)


@app.post("/campaign/{slug}/aset/hapus")
def campaign_aset_hapus(request: Request, slug: str,
                        asset_id: int = Form(...)):
    siapa = _siapa(request)
    if not siapa:
        return _minta_sandi()
    conn = camp.connect()
    camp.remove_asset(conn, asset_id, slug=slug)
    return RedirectResponse("/campaign/%s" % slug, status_code=303)


@app.get("/")
def index(request: Request):
    siapa = _siapa(request)
    if not siapa:
        return _minta_sandi()
    conn = q.connect()
    q.reap_stale(conn)
    isi = _nav("render") + _form(siapa) + (
        '<div class=panel><h2>Render terakhir</h2>%s</div>' % _tabel(q.recent(conn, limit=12))
    )
    return _halaman("Clipper", isi)


@app.post("/render")
async def mulai(request: Request,
          preset: str = Form(...),
          content: str = Form(...),
          opening: str = Form(""),
          portrait: str = Form(""),
          context: str = Form(""),
          campaign: str = Form(""),
          bgm_file: str = Form(""),
          image: UploadFile = File(None),
          bgm: UploadFile = File(None)):
    siapa = _siapa(request)
    if not siapa:
        return _minta_sandi()
    if preset not in PRESETS:
        return _halaman("Clipper", _form(siapa, "Preset '%s' ga ada." % preset))

    # Form render bisa dapet aset dua jalan: UPLOAD langsung (form utama)
    # atau PILIH aset campaign yang udah ke-upload (halaman campaign).
    # Upload disimpen ke folder aset supaya satu pagar yang sama berlaku
    # buat keduanya, dan supaya auto-clean ga ngebuangnya.
    _slug = campaign.strip() or "_lepas"
    try:
        for f, kind in ((image, "image"), (bgm, "bgm")):
            if not f or not f.filename:
                continue
            isi = await f.read()
            if not isi:
                continue
            if len(isi) > MAX_UPLOAD_MB * 1e6:
                return _halaman("Clipper", _form(
                    siapa, "%s: %0.1f MB lewat batas %0.0f MB."
                           % (kind, len(isi) / 1e6, MAX_UPLOAD_MB)))
            path = camp.save_upload(_slug, kind, f.filename, isi)
            if kind == "image":
                portrait = path
            else:
                bgm_file = path
            if campaign.strip():
                # Aset yang diupload lewat form campaign ikut kecatet, biar
                # render berikutnya buat campaign yang sama bisa milih dia
                # lagi tanpa upload ulang.
                camp.add_asset(camp.connect(), _slug, kind, path, who=siapa)
    except ValueError as exc:
        return _halaman("Clipper", _form(siapa, str(exc)))

    if portrait and not PRESETS[preset]["pakai_outro"]:
        return _halaman("Clipper", _form(
            siapa,
            "Gambar outro cuma kepakai di preset Jedag jedug. Preset "
            "Mengharukan dikasih gambar outro bakal ditolak job.py."))
    # Path aset datang dari form, jadi dia input yang ga dipercaya: tanpa
    # pagar ini sebuah POST bisa nyuruh pekerja baca file mana pun di kotak
    # ini (/etc/passwd sebagai "BGM") dan nempelin isinya ke render.
    # Dibatasin ke folder aset campaign; BGM bawaan tetep bisa dipakai lewat
    # jalur mood otomatis, yang ga ngelewatin form.
    for nama, nilai in (("gambar outro", portrait), ("BGM", bgm_file)):
        if not nilai:
            continue
        p = os.path.abspath(nilai)
        if not p.startswith(os.path.abspath(camp.ASSET_DIR) + os.sep):
            return _halaman("Clipper", _form(
                siapa,
                "%s harus file yang diupload di halaman campaign. Path lain "
                "ditolak: form ga boleh bisa nunjuk file sembarangan di "
                "server." % nama))
        if not os.path.isfile(p):
            return _halaman("Clipper", _form(
                siapa, "%s udah ga ada di disk — mungkin kehapus dari aset "
                       "campaign." % nama))
    params = {"content": content.strip(), "opening": opening.strip(),
              "portrait": portrait.strip(), "context": context.strip(),
              "campaign": campaign.strip(), "bgm_file": bgm_file.strip()}
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
        med, n = q.median_render_sec(conn)
        refresh = 10
        bagian.append(
            "<div class=panel><h2>Nunggu antrean</h2>"
            "<p>Nomor urut <span class=num>%d</span>. "
            "Perkiraan mulai <span class=num>%s</span> lagi.</p>"
            "<p class=hint>%s</p>"
            "<form method=post action=/batal>"
            "<input type=hidden name=job_id value=%d>"
            "<button class=ghost type=submit>Batalin</button></form></div>"
            % (pos, _lama(eta), _dasar_median(med, n), job_id))
    elif st == "running":
        jalan = time.time() - (j["started_at"] or time.time())
        med, n = q.median_render_sec(conn)
        refresh = 10
        bagian.append(
            "<div class=panel><h2>Lagi dirender</h2>"
            "<p>Tahap: <span class=num>%s</span> · udah jalan "
            "<span class=num>%s</span>.</p>"
            "<p class=hint>Ga ada bar persen di sini: job.py ga lapor persen, "
            "jadi bar yang gerak sendiri bakal bohong. %s</p>"
            "<p class=hint>Halaman bisa kerasa lambat sekarang — ffmpeg makan "
            "dua core yang sama.</p></div>"
            % (_e(j["stage"] or "mulai"), _lama(jalan), _dasar_median(med, n)))
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
        bagian.append(_panel_upload(j, job_id))
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
    _p = json.loads(j["params"])
    if _p.get("campaign"):
        kepala += ("<p class=sub>buat campaign <a href='/campaign/%s'>%s</a>"
                   "</p>" % (_e(_p["campaign"]), _e(_p["campaign"])))
    if _p.get("bgm_file"):
        kepala += ("<p class=sub>BGM dipilih tangan: <span class=num>%s"
                   "</span></p>" % _e(os.path.basename(_p["bgm_file"])))
    return _halaman("Job #%d" % job_id,
                    kepala + "".join(bagian) + "<p><a href=/>Balik</a></p>",
                    refresh=refresh)


def _panel_upload(j, job_id):
    """Form upload YouTube, keisi otomatis dari judul/deskripsi hasil render.

    Kenapa field-nya ada walaupun tombolnya bisa mati: judul dan deskripsi
    SUDAH dibikin saat render (job.py manggil model buat itu), jadi
    nyembunyiin field bikin operator ngarang ulang sesuatu yang udah dibayar.
    Field-nya dikasih nilai awal dan boleh diubah -- yang dikirim ke YouTube
    adalah apa yang kelihatan di kotak, bukan versi tersimpan.

    Judul YouTube keras di 100 karakter (API motong tanpa ngasih tau), jadi
    batasnya dipasang di input DAN sisa karakternya ditulis -- orang ga bisa
    nebak batas yang ga kelihatan.

    Tombol bisa mati karena token OAuth belum ada. Kalau mati, field-nya TETAP
    kelihatan dan tetap bisa disunting, karena nyiapin teks itu kerjaan yang
    berguna walaupun pengirimannya nunggu operator.
    """
    meta = {}
    try:
        meta = json.loads(j["meta"] or "{}")
    except Exception:
        meta = {}

    akun = []
    try:
        import preflight
        akun = preflight.upload_accounts() or []
    except Exception:
        akun = []

    judul = (meta.get("title") or "").strip()
    desk = (meta.get("description") or "").strip()
    hook = (meta.get("hook") or "").strip()

    # Render lama (sebelum kolom meta ada) ga punya judul. Itu bukan error,
    # tapi harus dibilang, bukan dibiarin kotaknya kosong tanpa sebab.
    if not judul and not desk:
        asal = ("<p class=hint>Render ini dibikin sebelum console nyimpen "
                "judul dari model, jadi kotaknya kosong. Render ulang kalau "
                "mau judul otomatis.</p>")
    else:
        asal = ("<p class=hint>Judul dan deskripsi di atas dibikin saat "
                "render. Ubah sesuka lu — yang dikirim itu isi kotaknya.</p>")

    if akun:
        pilih = "".join("<option value=\"%s\">%s</option>" % (_e(a), _e(a))
                        for a in akun)
        kontrol = (
            "<label><span class=lab>Akun</span><select name=akun>%s</select>"
            "</label>" % pilih)
        tombol = "<button type=submit>Upload ke YouTube</button>"
        catatan = ("<p class=hint>Diupload sebagai <strong>private</strong> "
                   "dulu, jadi lu bisa cek di YouTube Studio sebelum "
                   "dipublikasikan.</p>")
    else:
        # Dua sebab beda, dua kerjaan beda, dua orang beda. Dulu dua-duanya
        # nulis "nunggu OAuth operator" -- jadi library yang belum keinstall
        # bikin halaman nyuruh operator ngurus OAuth, yang ga akan pernah
        # nolong. Sebabnya sekarang ditanya ke preflight.upload_blocker().
        sebab = preflight.upload_blocker()
        jenis = sebab[0] if sebab else "token"
        rinci = sebab[1] if sebab else ""
        # Kalimat sebab naik ke ATAS tombol: di lebar HP, tombol mati kebaca
        # (dan ketusuk) sebelum alasannya kebaca. Detail teknis tetep di
        # bawah -- itu kerjaan operator, bukan hal yang nahan si pengisi form.
        if jenis == "library":
            tombol = ("<button type=submit disabled>Upload — library Google "
                      "belum keinstall</button>")
            kontrol = ("<p class=hint>Upload belum bisa dijalanin: library "
                       "YouTube-nya belum kepasang di server ini. "
                       "<strong>Ini bukan soal OAuth</strong> — OAuth ga akan "
                       "nolong sampai ini kelar.</p>")
            catatan = (
                "<p class=hint>Yang kurang di server console: "
                "<code>google-api-python-client</code>, "
                "<code>google-auth</code>, <code>google-auth-oauthlib</code> "
                "(udah ke-list di <code>requirements.txt</code>, cuma belum "
                "keinstall di venv-nya). Pesan aslinya: <code>" + _e(rinci) +
                "</code></p>")
        else:
            tombol = "<button type=submit disabled>Upload — nunggu OAuth operator</button>"
            kontrol = ("<p class=hint>Upload belum bisa dijalanin: console ini "
                       "belum punya akun YouTube yang keotorisasi.</p>")
            catatan = (
                "<p class=hint>Yang kurang: file "
                "<code>token_&lt;nama akun YouTube&gt;.pickle</code> di "
                "<code>" + _e(rinci or "tokens/") + "</code>. Butuh satu kali "
                "OAuth Google punya operator; abis token-nya ada, "
                "<strong>refresh halaman ini</strong> dan tombolnya nyala. "
                "Judul &amp; Deskripsi di atas belum kesimpen kalau lu pindah "
                "halaman, jadi buat sekarang pakai Unduh file.</p>")

    return """
<form method=post action=/upload class=panel>
  <h2>Kirim ke YouTube</h2>
  <input type=hidden name=job_id value=%d>
  %s
  <label><span class=lab>Judul <span class=hint id=sisa-judul></span></span>
    <input type=text name=judul maxlength=100 value="%s" id=judul></label>
  <label><span class=lab>Deskripsi</span>
    <textarea name=deskripsi rows=4>%s</textarea></label>
  %s
  %s
  %s
</form>
<script>
/* Label dulu nulis batas 100 tanpa nunjukin posisi lu di dalamnya. YouTube
   motong judul kepanjangan TANPA ngasih tau, jadi angka yang kebaca itu
   bedanya ketahuan sekarang vs ketahuan setelah tayang. */
(function () {
  var i = document.getElementById("judul");
  var out = document.getElementById("sisa-judul");
  if (!i || !out) return;
  function hitung() {
    var n = i.value.length;
    out.textContent = "· " + n + "/100";
    out.style.color = n > 90 ? "var(--gold)" : "";
  }
  i.addEventListener("input", hitung);
  hitung();
})();
</script>""" % (job_id, asal, _e(judul), _e(desk or hook), kontrol, tombol,
                catatan)


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
  makan waktu sama kayak render pertama dan masuk antrean dari belakang.</p>
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


@app.post("/upload")
def upload(request: Request,
           job_id: int = Form(...),
           judul: str = Form(""),
           deskripsi: str = Form(""),
           akun: str = Form("")):
    """Kirim klip yang udah kelar ke YouTube.

    Upload dilakukan di sini, bukan di antrean, karena dia hitungan detik dan
    ga makan CPU kayak render -- tapi error-nya diterjemahin, bukan dilempar
    mentah: kuota harian habis dan token kedaluwarsa itu dua hal beda yang
    butuh dua tindakan beda dari operator.
    """
    siapa = _siapa(request)
    if not siapa:
        return _minta_sandi()
    conn = q.connect()
    j = q.get(conn, job_id)
    if not j:
        return RedirectResponse("/", status_code=303)

    def _tolak(pesan):
        return _halaman("Job #%d" % job_id,
                        "<div class=panel><h2>Upload ga jalan</h2>"
                        "<div class=err>%s</div>"
                        "<p><a href=/job/%d>Balik ke job</a></p></div>"
                        % (_e(pesan), job_id))

    if j["status"] != "done" or not j["out_path"]:
        return _tolak("Job ini belum kelar, jadi ga ada file buat diupload.")
    if not os.path.exists(j["out_path"]):
        return _tolak("File rendernya udah ga ada di disk — mungkin kena "
                      "pembersihan otomatis. Render ulang dulu.")

    judul = judul.strip()
    if not judul:
        return _tolak("Judul ga boleh kosong: YouTube nolak video tanpa "
                      "judul, dan judul otomatis dari render ada di form.")

    try:
        import preflight
        tersedia = preflight.upload_accounts() or []
    except Exception as e:
        return _tolak("Ga bisa baca daftar akun upload: %s" % e)
    if not tersedia:
        return _tolak("Belum ada akun upload di box ini (file "
                      "tokens/token_<nama>.pickle ga ada). Butuh satu kali "
                      "OAuth Google punya operator.")
    pilih = akun.strip() or tersedia[0]
    if pilih not in tersedia:
        return _tolak("Akun %r ga ada di daftar akun yang kepasang." % pilih)

    try:
        import upload_youtube as uy
        hasil = uy.upload(
            conn, j["out_path"],
            {"title": judul, "description": deskripsi.strip(),
             "youtube_tags": []},
            account=pilih)
    except Exception as e:
        pesan = str(e)
        # Dua kegagalan yang paling sering dan paling beda tindakannya.
        if "uploadLimitExceeded" in pesan or "DailyLimit" in type(e).__name__:
            return _tolak("Kuota upload harian akun %s udah habis. Coba besok "
                          "atau pakai akun lain — filenya tetep ada." % pilih)
        if "invalid_grant" in pesan or "RefreshError" in type(e).__name__:
            return _tolak("Token akun %s udah kedaluwarsa. Operator perlu "
                          "OAuth ulang buat akun itu." % pilih)
        return _tolak("Upload gagal: %s" % pesan)

    return _halaman(
        "Job #%d" % job_id,
        "<div class=panel><h2>Udah keupload</h2>"
        "<p>Masuk sebagai <strong>private</strong> ke akun "
        "<span class=num>%s</span>.</p>"
        "<p><a href=\"%s\">Buka di YouTube</a></p>"
        "<p class=hint>Masih private — publikasiin dari YouTube Studio kalau "
        "udah oke.</p>"
        "<p><a href=/job/%d>Balik ke job</a></p></div>"
        % (_e(hasil.get("account") or pilih), _e(hasil.get("url") or ""),
           job_id))


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
def sehat(request: Request):
    """Health check. SENGAJA kebuka tanpa sandi -- systemd dan tunnel
    butuh satu alamat yang bisa dicek tanpa kredensial.

    Tapi yang dibocorin dibatasin. Dia dulu nyetak `user_kepasang`
    (jumlah akun) dan `nunggu` (panjang antrean) ke siapa pun; di LAN itu
    ga ada artinya, tapi console ini sekarang kebuka ke internet lewat
    tunnel, dan jumlah akun itu kabar gratis buat yang mau nebak sandi.
    Angka operasional cuma keluar kalau yang nanya udah login.
    """
    if _siapa(request):
        conn = q.connect()
        return {"ok": True, "nunggu": q.waiting_count(conn),
                "user_kepasang": len(USERS)}
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    if not USERS:
        raise SystemExit(
            "CLIPPER_CONSOLE_USERS kosong. Akun dibikin manual -- ga ada\n"
            "pendaftaran sendiri, dan server ga mau jalan tanpa sandi.\n"
            'Contoh: CLIPPER_CONSOLE_USERS="dalmi:sandi1,oden:sandi2"')
    print("console on http://%s:%d (%d akun)" % (HOST, PORT, len(USERS)))
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
