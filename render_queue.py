"""Antrean render buat console web.

Kenapa ada: job.py cuma bisa satu render sekali jalan (fcntl.flock di
.job.lock, attempt kedua ditolak). Diukur di kotak ini dari 257 render
nyata: median 2,4 menit, p90 3,6 menit. Jadi request HTTP TIDAK BOLEH
nungguin render -- lebih lama dari timeout browser mana pun.

Bentuknya: satu proses pekerja ngambil job satu-satu dari daftar, halaman
web cuma baca status. Operator milih "masuk antrean, dikasih nomor urut +
perkiraan nunggu", jadi posisi dan perkiraan itu bagian dari kontrak, bukan
hiasan.

Keadaan sebuah job:
    waiting  -> belum mulai, punya nomor urut
    running  -> lagi dirender
    done     -> ada file hasilnya
    failed   -> ada pesan error
    canceled -> dibatalin sebelum mulai

State disimpen di SQLite, bukan di memori: kalau prosesnya mati, antrean
ga ilang. Itu juga yang bikin halaman web dan pekerja bisa jadi dua proses.
"""
import json
import os
import sqlite3
import time

DB_PATH = os.environ.get(
    "CLIPPER_QUEUE_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "queue.db"),
)

# Perkiraan nunggu pakai angka hasil ukur, bukan tebakan. Dari 257 render:
# median 2,4 menit. Dipakai buat ngali jumlah job di depan.
MEDIAN_RENDER_SEC = 144.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner       TEXT NOT NULL,
    preset      TEXT NOT NULL,
    params      TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'waiting',
    stage       TEXT NOT NULL DEFAULT '',
    error       TEXT NOT NULL DEFAULT '',
    out_path    TEXT NOT NULL DEFAULT '',
    warnings    TEXT NOT NULL DEFAULT '[]',
    -- Hasil render yang BUKAN file: judul, deskripsi, tag, mood, durasi.
    -- job.py sudah membuat semua ini (title/description dari model), tapi
    -- dulu worker membuangnya dan hanya menyimpan out_path -- jadi panel
    -- upload tidak punya apa pun untuk diisikan ke form dan operator harus
    -- mengarang ulang judul yang sudah dibayar.
    meta        TEXT NOT NULL DEFAULT '{}',
    created_at  REAL NOT NULL,
    started_at  REAL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, id);
"""


def connect(path=None):
    conn = sqlite3.connect(path or DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    _migrasi(conn)
    return conn


def _migrasi(conn):
    """Tambah kolom yang belum ada di DB yang sudah terbentuk.

    `CREATE TABLE IF NOT EXISTS` TIDAK menambah kolom baru ke tabel yang
    sudah ada, jadi menambah kolom di _SCHEMA saja membuat DB produksi
    tertinggal dan setiap pembacaan kolom itu melempar OperationalError.
    Dicek dengan PRAGMA, bukan dengan try/except di sekitar ALTER, supaya
    kesalahan lain tidak ikut tertelan.
    """
    ada = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
    for nama, definisi in (("meta", "TEXT NOT NULL DEFAULT '{}'"),):
        if nama not in ada:
            conn.execute("ALTER TABLE jobs ADD COLUMN %s %s" % (nama, definisi))
    conn.commit()


def submit(conn, owner, preset, params):
    """Taro job baru di belakang antrean. Balik id-nya."""
    cur = conn.execute(
        "INSERT INTO jobs (owner, preset, params, created_at) VALUES (?,?,?,?)",
        (owner, preset, json.dumps(params, ensure_ascii=False), time.time()),
    )
    conn.commit()
    return cur.lastrowid


def claim(conn, paksa=False):
    """Ambil job paling depan buat dikerjain. None kalau ga ada yang bisa.

    Dipanggil pekerja. Penandaan running dilakukan dalam satu transaksi
    supaya dua pekerja ga bisa ngambil job yang sama.

    TAHAN SATU RENDER SEKALI JALAN: kalau masih ada job status running,
    fungsi ini balik None walaupun antreannya panjang. Alasannya bukan
    teori -- kotak ini 2 vCPU dan job.py punya flock sendiri, jadi render
    kedua yang dipaksa jalan bikin dua-duanya lambat lalu yang kedua
    ditolak di level file lock, padahal statusnya udah running, jadi
    nyangkut sampai reap_stale.

    Ketemu pas nyiapin cron per-tick: tick kedua datang beberapa menit
    setelah yang pertama, render pertama masih jalan, dan claim() tetep
    ngasih job kedua.

    `paksa=True` cuma buat tes yang perlu nyiapin dua job running.
    """
    conn.execute("BEGIN IMMEDIATE")
    if not paksa:
        jalan = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0]
        if jalan:
            conn.rollback()
            return None
    row = conn.execute(
        "SELECT * FROM jobs WHERE status='waiting' ORDER BY id LIMIT 1"
    ).fetchone()
    if row is None:
        conn.rollback()
        return None
    conn.execute(
        "UPDATE jobs SET status='running', started_at=?, stage=? WHERE id=?",
        (time.time(), "mulai", row["id"]),
    )
    conn.commit()
    return dict(row)


def set_stage(conn, job_id, stage):
    conn.execute("UPDATE jobs SET stage=? WHERE id=?", (stage, job_id))
    conn.commit()


def finish(conn, job_id, out_path, warnings=None, meta=None):
    conn.execute(
        "UPDATE jobs SET status='done', out_path=?, warnings=?, meta=?, "
        "finished_at=?, stage='' WHERE id=?",
        (out_path, json.dumps(warnings or [], ensure_ascii=False),
         json.dumps(meta or {}, ensure_ascii=False), time.time(), job_id),
    )
    conn.commit()


def fail(conn, job_id, message):
    conn.execute(
        "UPDATE jobs SET status='failed', error=?, finished_at=?, stage='' "
        "WHERE id=?",
        (str(message)[:2000], time.time(), job_id),
    )
    conn.commit()


def cancel(conn, job_id, owner):
    """Batalin job yang BELUM mulai. Balik True kalau beneran kebatalin.

    Job yang lagi jalan ga bisa dibatalin dari sini: ffmpeg-nya udah
    jalan, dan matiin di tengah ninggalin file setengah jadi. Jujur
    nolak lebih baik daripada tombol yang kelihatan kerja tapi engga.
    """
    cur = conn.execute(
        "UPDATE jobs SET status='canceled', finished_at=? "
        "WHERE id=? AND owner=? AND status='waiting'",
        (time.time(), job_id, owner),
    )
    conn.commit()
    return cur.rowcount > 0


def position(conn, job_id):
    """Nomor urut job yang masih nunggu. 0 kalau udah ga nunggu.

    1 = paling depan, bakal diambil pekerja berikutnya.
    """
    row = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None or row["status"] != "waiting":
        return 0
    return conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status='waiting' AND id <= ?", (job_id,)
    ).fetchone()[0]


def median_render_sec(conn, minimal=3):
    """Median durasi render dari job yang BENERAN kelar di box ini.

    Konstanta 144,0 detik itu tebakan dari mesin lain, dan di box ini dia
    salah 3x: dua render pertama yang keukur 481 dan 405 detik (median 443).
    Estimasi antrean yang ngaku 2,4 menit buat kerjaan 7,4 menit bukan
    "kira-kira", itu ngasih angka yang salahnya searah terus -- selalu
    bikin orang nungguin layar lebih lama dari yang dijanjiin.

    Di bawah `minimal` sampel, median dari 1-2 render gampang kebawa satu
    video aneh, jadi balikin konstanta. Fungsi ini sengaja ga nyimpen cache:
    query-nya satu baris di tabel yang isinya puluhan.
    """
    rows = conn.execute(
        "SELECT finished_at - started_at AS lama FROM jobs "
        "WHERE status='done' AND started_at IS NOT NULL "
        "AND finished_at IS NOT NULL"
    ).fetchall()
    d = sorted(r["lama"] for r in rows if r["lama"] and r["lama"] > 0)
    if len(d) < minimal:
        return MEDIAN_RENDER_SEC, len(d)
    n = len(d)
    med = d[n // 2] if n % 2 else (d[n // 2 - 1] + d[n // 2]) / 2
    return med, n


def eta_seconds(conn, job_id):
    """Perkiraan nunggu dalam detik. None kalau ga bisa diperkirakan.

    Hitungannya: sisa job yang lagi jalan + jumlah job di depan dikali
    median NYATA box ini (lihat median_render_sec). Ini PERKIRAAN dan
    halamannya harus bilang begitu.
    """
    pos = position(conn, job_id)
    if pos == 0:
        return None
    med, _ = median_render_sec(conn)
    ahead = pos - 1
    total = ahead * med
    running = conn.execute(
        "SELECT started_at FROM jobs WHERE status='running' LIMIT 1"
    ).fetchone()
    if running and running["started_at"]:
        sisa = med - (time.time() - running["started_at"])
        total += max(sisa, 15.0)
    return total


def get(conn, job_id):
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def recent(conn, owner=None, limit=20):
    if owner:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE owner=? ORDER BY id DESC LIMIT ?",
            (owner, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def waiting_count(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status='waiting'"
    ).fetchone()[0]


def for_campaign(conn, slug, limit=50):
    """Job yang dirender buat sebuah campaign, terbaru dulu.

    Slug-nya nempel di `params` JSON, bukan di kolom sendiri: tabel ini
    udah dipakai antrean yang jalan, dan `json_extract` bawaan SQLite
    cukup buat jumlah job segini. Kalau nanti papannya butuh urutan per
    campaign di SQL, baru pantes jadi kolom + index.
    """
    rows = conn.execute(
        "SELECT * FROM jobs WHERE json_extract(params,'$.campaign')=? "
        "ORDER BY id DESC LIMIT ?", (slug, limit)).fetchall()
    return [dict(r) for r in rows]


def reap_stale(conn, max_age_sec=3600):
    """Job 'running' yang ketinggalan karena pekerjanya mati.

    Render terlama yang keukur 6,6 menit, jadi apa pun yang running lebih
    dari sejam itu sisa proses yang udah ga ada. Tanpa ini, satu crash
    bikin antrean keliatan sibuk selamanya.
    """
    batas = time.time() - max_age_sec
    cur = conn.execute(
        "UPDATE jobs SET status='failed', error=? , finished_at=? "
        "WHERE status='running' AND started_at < ?",
        ("pekerja berhenti di tengah jalan (proses hilang)", time.time(), batas),
    )
    conn.commit()
    return cur.rowcount
