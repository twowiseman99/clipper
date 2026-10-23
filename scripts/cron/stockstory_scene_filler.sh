#!/bin/bash
# One tick: top up missing scene stills, then build the short if the set is
# complete and consistent. Both steps are idempotent and silent when idle, so
# this is safe to run every 10 minutes forever.

# PAGAR MEMORI + LOCK GLOBAL, dipasang 23 Okt 2026 sesudah empat kali OOM.
#
# Diukur: ffmpeg memegang 7,0-7,4 GB dari RAM 7,4 GB, dan cgroup-nya
# hermes-gateway.service -- jadi ffmpeg jebol = gateway mati = SSH timeout.
#
# build_short.py memanggil literal "ffmpeg" lewat sh([...]) tanpa env hook
# apa pun (beda dari clipper/edit.py yang punya CLIPPER_FFMPEG di baris 43).
# Jadi pagarnya dipasang lewat PATH: direktori shim berisi file bernama
# "ffmpeg" yang meneruskan ke ffguard. NOL baris kode render yang berubah --
# syarat operator "asal hasil clip ga berubah".
#
# Angka yang relevan buat job INI (terukur di box ini):
#   upscale 1440x2560          79 MB
#   zoompan satu scene        298 MB
#   xfade 10 klip 1080x1920  1026 MB   <- naik ~51 MB per input tambahan
# Jadi makin banyak scene, makin dekat ke plafon. MemoryMax yang memotong
# lebih baik daripada box yang mati.
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

cd /home/ubuntu/projects/stockstory/work/short1 || exit 1
/usr/bin/python3 filler_tick.py
/usr/bin/python3 build_short.py 2>&1 | grep -v '^WAITING:' || true
