#!/usr/bin/env bash
# Pekerja render Clipper, satu tick = satu job terus exit.
#
# Kenapa cron dan bukan proses yang jalan terus: di kotak ini sudah terukur
# proses yang dimiliki chat jadi anak gateway, jadi gateway restart / sesi
# tutup bikin pekerjanya mati diam-diam dan antrean berhenti tanpa bilang
# apa-apa. Cron yang pegang kontinuitas.
#
# Keluaran KOSONG kalau antrean kosong -> cron no_agent diem. Itu yang
# diinginkan: pekerja yang lapor "antrean kosong" tiap 2 menit = spam.
set -euo pipefail
cd /home/ubuntu/clipper

# PAGAR MEMORI, dipasang 23 Okt 2026 sesudah empat kali OOM dalam satu jam.
# Diukur dari kernel log: satu proses ffmpeg memegang 7,0-7,4 GB dari RAM
# 7,4 GB, dan journald mencatat cgroup-nya
#   task_memcg=/user.slice/.../hermes-gateway.service, task=ffmpeg
# jadi ffmpeg jalan DI DALAM cgroup gateway dan membawa gateway mati bersama
# dirinya tiga kali ("hermes-gateway.service: Failed with result 'oom-kill'").
# Itu sebab SSH timeout, bukan efek samping.
#
# Jalur sisipnya resmi: edit.py:43 sudah baca CLIPPER_FFMPEG, jadi pagar
# masuk TANPA menyentuh satu baris pun logika render — syarat operator "asal
# hasil clip ga berubah". Shim-nya menjalankan ffmpeg di scope sendiri
# (MemoryMax, MemorySwapMax=0) dan di bawah SATU lock render global.
#
# Lock global perlu karena tiap job dulu punya pagar sendiri yang tidak saling
# kenal: bio1 pakai /tmp/render_broll.lock, tick ini cuma mengandalkan claim()
# di SQLite. Dua mekanisme berbeda = nol eksklusi antar-job.
export CLIPPER_FFMPEG=/home/ubuntu/clipper/scripts/ffmpeg_guarded.sh
export PATH=/home/ubuntu/clipper/scripts/shim:$PATH

export FFGUARD_MEMMAX=${FFGUARD_MEMMAX:-3G}
# FFGUARD_THREADS SENGAJA TIDAK DISET. Diukur 23 Okt 2026: render yang sama
# tanpa pagar dua kali menghasilkan md5 IDENTIK (8a70bc4d, dua kali),
# sementara lewat pagar yang menyuntik -threads jadi 6e4e2c6b dengan ukuran
# byte SAMA PERSIS (13.849.191). Jadi renderer ini deterministik dan satu
# argumen suntikan sudah cukup menggeser bit keluaran. Operator minta hasil
# render tidak berubah, jadi pagar hanya membatasi MEMORI -- nol sentuhan ke
# argumen ffmpeg. Batas thread sudah ada di edit.py lewat CLIPPER_THREADS,
# dan box ini cuma 2 vCPU sehingga default cpu_count() memang sudah 2.

# render_worker.py nyetak "antrean kosong" kalau ga ada kerjaan. Dibuang ke
# /dev/null biar cron diem; baris lain (job mulai/kelar/GAGAL) tetep lewat.
keluaran="$(.venv/bin/python render_worker.py 2>&1 || true)"
if [ "$keluaran" != "antrean kosong" ] && [ -n "$keluaran" ]; then
  echo "$keluaran"
fi
