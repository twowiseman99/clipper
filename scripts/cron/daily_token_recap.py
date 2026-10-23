#!/usr/bin/env python3
"""Daily token + cost recap for the Discord #token channel.

Read-only query against the Hermes session DB. Sums token usage and
estimated cost for everything since local midnight, and prints a short
plain-text recap. Stdout is delivered verbatim by the no_agent cron job;
empty stdout would mean silence, so we always print at least one line.
"""
import os
import sqlite3
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

# The recap summarizes the calendar day in this timezone (Jakarta, UTC+07:00).
# The cron schedule is expressed in the SERVER's local time (UTC+08:00), which
# is 1 hour ahead of Jakarta — so 00:30 server time == 23:30 Jakarta time.
RECAP_TZ = os.environ.get("RECAP_TZ", "Asia/Jakarta")


def _fmt_int(n):
    return f"{n:,}"


def _fmt_cost(v):
    if v >= 0.01:
        return f"${v:.2f}"
    return f"${v:.4f}"


def _gib(kb):
    return kb / 1024.0 / 1024.0


def _sistem():
    """Blok kesehatan sistem: RAM, swap, load, disk, proses terbesar.

    Ditambahkan 23 Okt 2026 atas permintaan operator, setelah satu ffmpeg
    memegang 7,4 GB dari RAM 7,4 GB dan membunuh hermes-gateway tiga kali.
    Angka harian ini yang membuat tren naik kelihatan SEBELUM jadi insiden.
    """
    baris = []
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for l in f:
                p = l.split()
                if len(p) >= 2:
                    mem[p[0].rstrip(":")] = int(p[1])
        tot = _gib(mem.get("MemTotal", 0))
        avail = _gib(mem.get("MemAvailable", 0))
        used = tot - avail
        pct = int(used / tot * 100) if tot else 0
        baris.append(f"• RAM: {used:.1f} / {tot:.1f} GiB terpakai ({pct}%)")

        sw_t = _gib(mem.get("SwapTotal", 0))
        sw_u = sw_t - _gib(mem.get("SwapFree", 0))
        if sw_t:
            baris.append(
                f"• Swap: {sw_u:.2f} / {sw_t:.1f} GiB "
                f"({int(sw_u / sw_t * 100)}%)")
    except OSError as e:
        baris.append(f"• RAM: tidak terbaca ({e})")

    try:
        with open("/proc/loadavg") as f:
            baris.append("• Load: " + ", ".join(f.read().split()[:3]))
    except OSError:
        pass

    try:
        st = os.statvfs("/")
        d_tot = st.f_blocks * st.f_frsize / 1024 ** 3
        d_pakai = (st.f_blocks - st.f_bfree) * st.f_frsize / 1024 ** 3
        baris.append(f"• Disk /: {d_pakai:.1f} / {d_tot:.1f} GiB "
                     f"({int(d_pakai / d_tot * 100)}%)")
    except OSError:
        pass

    # Tiga proses RSS terbesar — kalau besok ada yang menggelembung, ini yang
    # menunjukkan siapa, tanpa perlu buka SSH.
    procs = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/status") as f:
                nama = rss = None
                for l in f:
                    if l.startswith("Name:"):
                        nama = l.split()[1]
                    elif l.startswith("VmRSS:"):
                        rss = int(l.split()[1])
                        break
            if nama and rss:
                procs.append((rss, nama, pid))
        except (OSError, ValueError, IndexError):
            continue
    if procs:
        procs.sort(reverse=True)
        atas = ", ".join(f"{n} {r // 1024} MB" for r, n, _ in procs[:3])
        baris.append(f"• Terbesar: {atas}")

    return baris


def main() -> int:
    home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
    db_path = os.path.join(home, "state.db")

    if not os.path.exists(db_path):
        print("📊 Daily token recap — no session DB found yet.")
        return 0

    # Midnight in the recap timezone (default Asia/Jakarta).
    now = datetime.now(ZoneInfo(RECAP_TZ))
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    cutoff = midnight.timestamp()

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error as e:
        print(f"⚠️ Daily token recap failed to open DB: {e}")
        return 1

    try:
        has_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='session_model_usage'"
        ).fetchone()
        if not has_table:
            print("📊 Daily token recap — no usage table yet.")
            return 0

        # Dipilih berdasar u.last_seen, BUKAN s.started_at. Diukur 23 Okt 2026:
        # dua sesi yang dipakai sepanjang hari ini dimulai 21 Agu dan 18 Okt,
        # jadi filter s.started_at >= midnight mengembalikan NOL baris dan
        # recap melaporkan "no activity recorded" padahal ada 1,3 miliar token
        # terpakai hari itu. Sesi panjang di Discord memang begitu: dibuka
        # sekali, dipakai berminggu-minggu. Yang menandai aktivitas HARI INI
        # adalah last_seen pada baris usage-nya.
        rows = conn.execute(
            """
            SELECT u.model, u.input_tokens, u.output_tokens,
                   u.cache_read_tokens, u.cache_write_tokens,
                   u.estimated_cost_usd, u.actual_cost_usd
            FROM session_model_usage u
            WHERE u.last_seen >= ?
            """,
            (cutoff,),
        ).fetchall()
    except sqlite3.Error as e:
        print(f"⚠️ Daily token recap query failed: {e}")
        return 1
    finally:
        conn.close()

    if not rows:
        # Blok sistem tetap dicetak walau nol token: justru hari sepi yang
        # bikin tren RAM kelihatan bersih.
        lines = [f"📊 Daily recap — {now:%Y-%m-%d}: nol aktivitas token.",
                 "", "🧠 Sistem:"] + _sistem()
        print("\n".join(lines))
        return 0

    tot_in = sum(r["input_tokens"] or 0 for r in rows)
    tot_out = sum(r["output_tokens"] or 0 for r in rows)
    tot_cache_read = sum(r["cache_read_tokens"] or 0 for r in rows)
    tot_cache_write = sum(r["cache_write_tokens"] or 0 for r in rows)
    est = sum(r["estimated_cost_usd"] or 0.0 for r in rows)
    act = sum(r["actual_cost_usd"] or 0.0 for r in rows)
    total = tot_in + tot_out + tot_cache_read + tot_cache_write

    lines = [f"📊 Daily token recap — {now:%Y-%m-%d}"]
    lines.append(f"• Input tokens:  {_fmt_int(tot_in)}")
    lines.append(f"• Output tokens: {_fmt_int(tot_out)}")
    if tot_cache_read or tot_cache_write:
        lines.append(
            f"• Cache read/write: {_fmt_int(tot_cache_read)} / {_fmt_int(tot_cache_write)}"
        )
    lines.append(f"• Total tokens:  {_fmt_int(total)}")
    cost_line = f"• Estimated cost: ~{_fmt_cost(est)}"
    if act > 0:
        cost_line += f" (actual {_fmt_cost(act)})"
    lines.append(cost_line)

    # Per-model breakdown only when more than one model was used.
    per_model = {}
    for r in rows:
        m = (r["model"] or "unknown").split("/")[-1]
        per_model[m] = per_model.get(m, 0) + (
            (r["input_tokens"] or 0)
            + (r["output_tokens"] or 0)
            + (r["cache_read_tokens"] or 0)
            + (r["cache_write_tokens"] or 0)
        )
    if len(per_model) > 1:
        lines.append("")
        lines.append("By model:")
        for m, t in sorted(per_model.items(), key=lambda kv: -kv[1]):
            lines.append(f"• {m} — {_fmt_int(t)} tokens")

    lines.append("")
    lines.append("🧠 Sistem:")
    lines.extend(_sistem())

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
