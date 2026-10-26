"""Gaya caption "podcast" (referensi operator 26 Okt 2026, reel DewmIstz-Tu).

Diukur dari frame referensi, bukan ditebak:
- satu kata kunci per layar dibikin 3-4x lebih gede
- 3 tingkat: kata kecil di kanan atas, kata gede di tengah,
  sisa kalimat kecil rata kiri di bawah; sekitar 5 kata per layar
- putih tebal, TANPA garis tepi, cuma bayangan lembut
- tiap kata masuk dari buram+transparan ke tajam, ~0,3 detik
- ganti layar = semua teks hilang sekaligus (tanpa animasi keluar)
- posisi tengah layar (area dagu/dada), bukan bawah

Modul terpisah biar gaya lain (bold/phrase/karaoke/editorial) nol sentuh.
"""
import os
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont

_HERE = os.path.dirname(os.path.abspath(__file__))
FONT_BIG = os.path.join(_HERE, "assets", "fonts", "Montserrat-ExtraBold.ttf")
FONT_SMALL = os.path.join(_HERE, "assets", "fonts", "Montserrat-SemiBold.ttf")

# Ukuran: kata gede ~3.3x kata kecil (referensi 3-4x), kanvas lebar 1080.
SIZE_BIG = int(os.environ.get("CLIPPER_POD_BIG", "150"))
SIZE_SMALL = int(os.environ.get("CLIPPER_POD_SMALL", "54"))
COLOR = (255, 255, 255, 255)
SHADOW_ALPHA = 225      # latar terang (slide putih) bikin teks tenggelam di v3
SHADOW_BLUR = 12
SHADOW_OFF = (0, 4)
PAD = 30                # ruang buat blur bayangan di tiap ubin
Y_CENTER = 0.56         # tengah blok di 56% tinggi (area dagu/dada)
MAX_WORDS = 5           # ~5 kata per layar seperti referensi
GAP_SPLIT = 0.45        # jeda segini = ganti layar
FADE_IN = 0.20          # buram -> tajam (referensi 15fps: ~130-200 ms)
FADE_STEPS = 4          # berapa tahap animasi masuk per kata
MARGIN_X = 40           # baris kecil ga boleh lewat tepi layar (render v3 kepotong)
HOLD_GAP = 0.60         # jeda < ini: layar lama nahan sampai layar baru, ga kosong
LINE_TIGHT = 0.68       # rapatnya tingkat; 0.80 kebaca "mepet" di render v3
STOP = {"yang", "dan", "di", "ke", "itu", "ini", "aja", "sih", "kan",
        "ya", "gua", "gue", "lu", "lo", "aku", "kamu", "dia", "jadi",
        "tapi", "kalau", "kalo", "udah", "ada", "mau", "kayak", "gitu"}


def _clean(w):
    return re.sub(r"[^\w'\-]", "", w, flags=re.UNICODE)


def _tile(text, size, font_path, alpha=255, blur=0.0):
    """Satu kata/frasa putih tanpa outline + bayangan lembut, PNG transparan."""
    font = ImageFont.truetype(font_path, size)
    tmp = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    b = tmp.textbbox((0, 0), text, font=font)
    w, h = b[2] - b[0] + 2 * PAD, b[3] - b[1] + 2 * PAD
    org = (PAD - b[0], PAD - b[1])
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((org[0] + SHADOW_OFF[0], org[1] + SHADOW_OFF[1]),
                            text, font=font, fill=(0, 0, 0, SHADOW_ALPHA))
    sh = sh.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
    fg = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(fg).text(org, text, font=font, fill=COLOR)
    img = Image.alpha_composite(sh, fg)
    if blur > 0:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    if alpha < 255:
        a = img.getchannel("A").point(lambda v: v * alpha // 255)
        img.putalpha(a)
    return img


def pick_key(words, accent=()):
    """Index kata kunci, satu per layar.

    Urutan: (1) kata yang diflag model (accent), (2) kata yang paling DITEKAN
    pas ngomong (`stress` dari emphasis.score_words, dihitung dari audio),
    (3) kata terpanjang yang bukan pengisi. Render 1 milih "Berbentuk" (cuma
    panjang) sementara "nombor"/angka yang bermakna jadi kecil.
    """
    acc = {a.lower().strip(".,!?") for a in accent if a}
    for i, w in enumerate(words):
        if _clean(w["word"]).lower() in acc:
            return i
    best, score = 0, -1e9
    for i, w in enumerate(words):
        c = _clean(w["word"])
        if c.lower() in STOP or len(c) < 3:
            s = -100.0
        else:
            s = float(w.get("stress", 0.0)) * 10 + len(c) * 0.3
        if s > score:
            best, score = i, s
    return best


def group_screens(words):
    """Pecah transkrip jadi layar: putus di jeda atau tiap MAX_WORDS kata."""
    out, cur = [], []
    for w in words:
        if cur and (w["start"] - cur[-1]["end"] >= GAP_SPLIT
                    or len(cur) >= MAX_WORDS):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def layout(screen, key, canvas_w=1080):
    """Posisi tetap tiap kata di layar ini (relatif ke tengah-atas blok).

    pre  = kata SEBELUM kunci: satu baris kecil, rata KANAN ke ujung kunci,
           nempel di atasnya (referensi: "gua" di kanan atas "ENGGAK").
    key  = kata kunci, gede, di tengah.
    post = kata SESUDAH kunci: satu baris kecil rata KIRI ke awal kunci.
    Return [(idx_kata, text, size, font, x, y)] + tinggi blok.
    """
    fb = ImageFont.truetype(FONT_BIG, SIZE_BIG)
    fs = ImageFont.truetype(FONT_SMALL, SIZE_SMALL)
    d = ImageDraw.Draw(Image.new("RGBA", (8, 8)))

    def wid(t, f):
        b = d.textbbox((0, 0), t, font=f)
        return b[2] - b[0]

    words = [_clean(w["word"]) or w["word"] for w in screen]
    kt = words[key]
    kt = kt.upper() if len(kt) <= 6 else kt[:1].upper() + kt[1:]
    big_size = SIZE_BIG
    while wid(kt, ImageFont.truetype(FONT_BIG, big_size)) > canvas_w * 0.86:
        big_size -= 6
    fb = ImageFont.truetype(FONT_BIG, big_size)
    kw = wid(kt, fb)
    kx0 = (canvas_w - kw) // 2
    kb = d.textbbox((0, 0), kt, font=fb)
    kh = kb[3] - kb[1]
    sb = d.textbbox((0, 0), "Ag", font=fs)
    sh = sb[3] - sb[1]
    gap = int(sh * (1 - LINE_TIGHT))
    # jarak ke baris bawah diukur dari TINTA kunci (kb[3]), bukan dari tinggi
    # kotaknya: kotak teks punya ruang kosong di atas huruf (kb[1] > 0), jadi
    # pakai kh doang bikin baris bawah mepet sementara baris atas lega.
    space = wid("a a", fs) - 2 * wid("a", fs)

    placed = []
    # _tile() sudah motong ruang kosong textbbox: tinta tiap ubin MULAI di
    # y+0 dan setinggi (bbox[3]-bbox[1]). Jadi susunan cukup pakai TINGGI TINTA,
    # tanpa offset bbox lagi -- dua versi sebelumnya ngitung offset itu dua kali
    # dan kunci nimpa baris atas (diukur: 942 px tinta numpuk).
    h_small = sb[3] - sb[1]
    h_key = kb[3] - kb[1]
    y_key = h_small + gap
    # Baris kecil bisa lebih lebar dari kata kunci. Rata kanan/kiri ke kunci
    # bikin "tertangani dengan baik ya" keluar tepi KIRI layar (render v3,
    # 26 Okt) -- rencana bilang x=106 padahal ubin baris atas mulai minus.
    # Tiap baris dijepit ke margin, tetap rapat ke kunci kalau muat.
    lo, hi = MARGIN_X, canvas_w - MARGIN_X

    def clamp(row):
        if not row:
            return row
        x0 = min(r[4] for r in row)
        x1 = max(r[4] + wid(r[1], fs) for r in row)
        dx = 0
        if x1 - x0 > hi - lo:
            dx = lo - x0
        elif x0 < lo:
            dx = lo - x0
        elif x1 > hi:
            dx = hi - x1
        return [r[:4] + (r[4] + dx,) + r[5:] for r in row]

    # baris atas (pre): disusun dari kanan ke kiri, ujung kanannya = ujung kunci
    x = kx0 + kw
    row = []
    for i in reversed(range(0, key)):
        t = words[i].lower()
        x -= wid(t, fs)
        row.append((i, t, SIZE_SMALL, FONT_SMALL, x, 0))
        x -= space
    placed += clamp(row)
    # kunci
    placed.append((key, kt, big_size, FONT_BIG, kx0, y_key))
    # baris bawah (post): rata kiri ke awal kunci
    x = kx0
    y_post = y_key + h_key + gap
    row = []
    for i in range(key + 1, len(words)):
        t = words[i].lower()
        row.append((i, t, SIZE_SMALL, FONT_SMALL, x, y_post))
        x += wid(t, fs) + space
    placed += clamp(row)
    placed.sort()
    return placed, y_post + h_small


def build_overlays(words, clip_start, tmp_dir, Overlay, name_fn,
                   accent_words=(), canvas_w=1080, canvas_h=1920,
                   y_center=Y_CENTER, censor=None):
    """List Overlay buat render_clip. Satu PNG per TAHAP layar.

    Kata baru masuk dalam FADE_STEPS tahap (buram+pudar -> tajam) selama
    FADE_IN detik; kata yang udah tampil tetap diam di posisinya. Ganti layar =
    semua hilang sekaligus. Jumlah PNG = kata x FADE_STEPS, jauh lebih kecil
    dari per-frame, dan posisi ga pernah geser.
    """
    mask = censor or (lambda s: s)
    out = []
    screens = group_screens(words)
    for si, screen in enumerate(screens):
        key = pick_key(screen, accent_words)
        placed, block_h = layout(screen, key, canvas_w)
        top = int(y_center * canvas_h - block_h / 2)
        # crop horizontal blok supaya PNG kecil
        x_min = max(0, min(p[4] for p in placed) - PAD)
        tiles = {}
        for (i, t, size, font, x, y) in placed:
            tiles[i] = (mask(t), size, font, x - x_min, y)
        bw = canvas_w - x_min
        bh = block_h + 2 * PAD
        scr_end = screen[-1]["end"] - clip_start
        # Layar ini nahan sampai layar berikut mulai kalau jedanya pendek
        # (< HOLD_GAP). Render 1: blok ilang ~170ms sebelum blok baru = kedip.
        if si + 1 < len(screens):
            nxt = screens[si + 1][0]["start"] - clip_start
            if nxt - scr_end < HOLD_GAP:
                scr_end = nxt
        for n, w in enumerate(screen):
            t0 = max(0.0, w["start"] - clip_start)
            t_next = (screen[n + 1]["start"] - clip_start
                      if n + 1 < len(screen) else scr_end)
            t_next = max(t_next, t0 + 0.08)
            # tahap animasi kata ke-n, lalu tahan sampai kata berikut
            step = min(FADE_IN / FADE_STEPS, (t_next - t0) / (FADE_STEPS + 1))
            for s in range(FADE_STEPS + 1):
                k = s / FADE_STEPS                 # 0 -> 1
                a0 = t0 + s * step
                a1 = t_next if s == FADE_STEPS else t0 + (s + 1) * step
                if a1 <= a0:
                    continue
                img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
                for j in range(n + 1):
                    text, size, font, x, y = tiles[j]
                    if j < n:
                        im = _tile(text, size, font)
                    else:
                        # Referensi: kata baru masuk abu-abu & buram kuat
                        # (kunci lebih buram dari kata kecil), 2-3 frame ke
                        # tajam. ease-out: cepet di awal, halus di akhir.
                        e = 1 - (1 - k) ** 2
                        big = (j == key)
                        im = _tile(text, size, font,
                                   alpha=int(255 * (0.45 + 0.55 * e)),
                                   blur=(12.0 if big else 6.0) * (1 - e))
                    img.alpha_composite(im, (int(x) - PAD, int(y)))  # ubin bawa margin PAD
                path = os.path.join(tmp_dir, name_fn("pod"))
                img.save(path)
                out.append(Overlay(path, x_min, top - PAD, a0, a1))
    return out


def bake(overlays, tmp_dir, Overlay, name_fn, canvas_w=1080, fps=30):
    """Gabung semua ubin jadi SATU video transparan (1 input ffmpeg).

    Kenapa: klip 78s = 870 PNG = 870 input ffmpeg -> dibunuh MemoryMax=3G
    setelah 11s (26 Okt). Ubin-ubin podcast ga pernah tumpang tindih waktunya
    (tahap per kata berurutan, layar nahan sampai layar berikut), jadi bisa
    dijejer jadi satu timeline lewat concat demuxer.
    """
    import subprocess
    if not overlays:
        return []
    ovs = sorted(overlays, key=lambda o: o.t_start)
    y0 = min(o.y for o in ovs)
    y1 = max(o.y + Image.open(o.path).size[1] for o in ovs)
    band_h = (y1 - y0 + 1) // 2 * 2
    blank = os.path.join(tmp_dir, name_fn("podblank"))
    Image.new("RGBA", (canvas_w, band_h), (0, 0, 0, 0)).save(blank)
    lines, t = [], 0.0
    for o in ovs:
        t0 = max(o.t_start, t)          # jaga-jaga kalau ada tumpang tindih
        if o.t_end <= t0:
            continue
        if t0 - t > 1e-3:
            lines += [f"file '{blank}'", f"duration {t0 - t:.4f}"]
        band = Image.new("RGBA", (canvas_w, band_h), (0, 0, 0, 0))
        band.alpha_composite(Image.open(o.path).convert("RGBA"), (int(o.x), int(o.y - y0)))
        p = os.path.join(tmp_dir, name_fn("podband"))
        band.save(p)
        lines += [f"file '{p}'", f"duration {o.t_end - t0:.4f}"]
        t = o.t_end
    lines += [f"file '{blank}'"]        # concat demuxer: entri terakhir tanpa durasi
    lst = os.path.join(tmp_dir, "podcast_concat.txt")
    open(lst, "w").write("\n".join(lines) + "\n")
    out = os.path.join(tmp_dir, "podcast_band.mov")
    ff = os.environ.get("CLIPPER_FFMPEG") or "ffmpeg"
    r = subprocess.run([ff, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
                        "-vf", f"fps={fps},format=argb", "-c:v", "qtrle", out],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError(f"podcast bake gagal: {r.stderr.strip()[:400]}")
    return [Overlay(out, 0, y0, 0.0, t)]
