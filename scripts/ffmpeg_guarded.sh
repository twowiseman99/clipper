#!/usr/bin/env bash
# Shim untuk CLIPPER_FFMPEG: dipanggil PERSIS seperti ffmpeg, tapi jalan di
# dalam cgroup berbatas dan di bawah satu lock render global.
#
# KENAPA SHIM, BUKAN EDIT edit.py: edit.py:43 sudah punya titik sisip resmi
#   FFMPEG = os.environ.get("CLIPPER_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"
# jadi pagar bisa dipasang TANPA menyentuh satu baris pun logika render. Itu
# syarat operator: "asal hasil clip ga berubah". Argumen diteruskan utuh,
# exit code diteruskan utuh, stdout/stderr tidak disentuh.
#
# Pemakaian:
#   export CLIPPER_FFMPEG=/home/ubuntu/clipper/scripts/ffmpeg_guarded.sh
#
# Semua alasan angka (4x OOM, 7,4 GB, cgroup gateway, nol lock antar-job) ada
# di ffguard.sh — file ini cuma adaptor nama.
exec /home/ubuntu/clipper/scripts/ffguard.sh ffmpeg "$@"
