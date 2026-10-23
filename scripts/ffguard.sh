#!/usr/bin/env bash
# ffguard — jalanin ffmpeg di dalam cgroup berbatas, satu render sekali waktu.
#
# KENAPA ADA (diukur 23 Okt 2026, bukan dugaan):
#
# 1. PAGAR MEMORI. Empat kali OOM dalam satu jam, tiap kali satu proses ffmpeg
#    memegang ~7,4 GB dari RAM 7,4 GB:
#      16:14:14 anon-rss 7.430.644 kB
#      16:27:46 anon-rss 7.411.308 kB
#      16:29:58 anon-rss 7.418.008 kB
#      17:19:18 anon-rss 7.345.500 kB
#    Yang bikin ini insiden server, bukan render gagal: journald mencatat
#      task_memcg=/user.slice/.../hermes-gateway.service, task=ffmpeg
#    ffmpeg jalan DI DALAM cgroup gateway, jadi
#      hermes-gateway.service: Failed with result 'oom-kill'
#    muncul tiga kali — SSH timeout dan Hermes mati itu akibat langsungnya.
#    Di dalam scope sendiri, yang kena batas cuma ffmpeg: dia mati, box hidup.
#
# 2. SATU RENDER SEKALI WAKTU. Sebelum ini tiap job punya pagar sendiri yang
#    tidak saling kenal: bio1_render_broll.sh pakai /tmp/render_broll.lock,
#    sementara clipper render tick cuma mengandalkan claim() di SQLite. Dua
#    mekanisme berbeda = nol eksklusi antar-job, dan render-tick (tiap 3 menit)
#    bisa overlap dengan broll (tiap 30 menit) lalu memorinya berlipat.
#    flock di SATU path dipakai SEMUA job render.
#
# 3. BATAS THREAD. Box ini 2 vCPU; load average sempat 33 lalu 63. Tiap thread
#    x264 memegang buffer frame sendiri, jadi thread berlebih itu memori DAN
#    rebutan CPU sekaligus.
#
# PEMAKAIAN
#   ffguard.sh ffmpeg -v error -i in.mp4 ... out.mp4
#   ffguard.sh --no-lock ffmpeg ...     # untuk ffprobe/grab frame yang cepat
#
# Keluar dengan kode asli perintahnya. Kalau dibunuh karena batas memori,
# tulis baris ❌ ke stderr DAN ke log — jangan diam, karena "hilang tanpa
# pesan" itu persis yang bikin tiga tebakan pertama salah sasaran.
set -u

LOG=${FFGUARD_LOG:-/tmp/ffguard.log}
LOCK=${FFGUARD_LOCK:-/tmp/render_global.lock}
MEMMAX=${FFGUARD_MEMMAX:-3G}
THREADS=${FFGUARD_THREADS-}
PAKAI_LOCK=1

if [ "${1:-}" = "--no-lock" ]; then PAKAI_LOCK=0; shift; fi
if [ $# -eq 0 ]; then
  echo "ffguard: nol perintah" >&2
  exit 64
fi

catat() { printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOG" 2>/dev/null || true; }

# -threads disuntik HANYA kalau pemanggil belum menyetelnya sendiri, supaya
# tuning yang sudah ada (edit.py:3904 pakai THREADS dari env) tidak ketimpa.
#
# DAN hanya kalau FFGUARD_THREADS tidak kosong. Diukur 23 Okt 2026: render
# yang sama tanpa pagar dua kali menghasilkan md5 IDENTIK (8a70bc4d, dua
# kali) sementara lewat pagar jadi 6e4e2c6b dengan ukuran byte yang SAMA
# persis. Jadi renderer ini deterministik dan pagarlah yang menggeser bit-nya
# -- lewat satu argumen yang disuntik. Operator minta hasil render tidak
# berubah, jadi suntikan ini harus bisa dimatikan: FFGUARD_THREADS= (kosong)
# berarti jangan sentuh argumen sama sekali.
cmd=("$@")
if [ -n "$THREADS" ] && { [ "${cmd[0]}" = "ffmpeg" ] || [ "${cmd[0]##*/}" = "ffmpeg" ]; }; then
  ada_threads=0
  for a in "${cmd[@]}"; do [ "$a" = "-threads" ] && ada_threads=1 && break; done
  if [ "$ada_threads" -eq 0 ]; then
    cmd=("${cmd[0]}" -threads "$THREADS" "${cmd[@]:1}")
  fi
fi

jalan() {
  # systemd-run --scope: prosesnya dapat cgroup sendiri, jadi MemoryMax
  # mengenai ffmpeg saja. MemorySwapMax=0 supaya dia tidak menyeret box ke
  # swap-thrash dulu sebelum mati (insiden kemarin menghabiskan swap 2 GB dan
  # ITU yang membuat SSH tidak bisa masuk).
  systemd-run --user --scope -q \
    -p MemoryMax="$MEMMAX" -p MemorySwapMax=0 \
    -- "${cmd[@]}"
}

t0=$(date +%s)
if [ "$PAKAI_LOCK" -eq 1 ]; then
  # fd 9 + flock: antre, jangan tolak. Render yang dilempar ke tong sampah
  # karena ada render lain itu kerjaan hilang, bukan pagar.
  exec 9>"$LOCK"
  flock 9
  jalan
  rc=$?
  flock -u 9
else
  jalan
  rc=$?
fi
took=$(( $(date +%s) - t0 ))

if [ "$rc" -ne 0 ]; then
  # 137 = SIGKILL (yang dipakai cgroup OOM killer), 9 kalau shell melaporkan
  # sinyal mentah. Bedakan "kena batas memori" dari "ffmpeg menolak argumen",
  # karena dua-duanya rc bukan nol tapi obatnya berbeda jauh.
  #
  # TRAP, terukur saat render pembuktian pertama: `ffmpeg -i FILE` TANPA
  # output selalu keluar rc=1 — itu cara broll_place._duration() membaca
  # banner durasi, dan sepenuhnya normal. Versi pertama logger ini menulis
  # ❌ untuk panggilan itu, jadi log penuh kegagalan palsu di render yang
  # sehat. Satu ❌ palsu merusak nilai seluruh log: kalau pembaca harus
  # menebak mana yang nyata, dia berhenti membaca.
  probe=0
  if [ "$rc" -eq 1 ]; then
    # Bentuk probe `ffmpeg -i FILE` tanpa output: argumen terakhir adalah
    # NILAI dari -i, bukan path keluaran. Deteksinya harus dari POSISI, bukan
    # dari isi: versi pertama memeriksa apakah argumen terakhir diawali "-"
    # dan itu gagal, karena argumen terakhir di sini justru nama file masukan.
    #
    # Kontrol dua arah yang memaksa perbaikan ini:
    #   A `ffmpeg -i fgtest.mp4`         -> harus "probe"  (dulu ❌, salah)
    #   B `ffmpeg -i GAADA.mp4 -c copy x.mp4` -> harus ❌   (rc=254)
    #   C `MemoryMax=200M` + encode besar -> harus ❌ DIBUNUH (rc=137)
    n=${#cmd[@]}
    terakhir="${cmd[n-1]}"
    sebelum="${cmd[n-2]:-}"
    if [ "$sebelum" = "-i" ]; then
      probe=1              # ffmpeg ... -i FILE   (nol keluaran)
    elif [ "$terakhir" = "-" ]; then
      probe=1              # keluaran ke stdout
    fi
    case " ${cmd[*]} " in
      *" -f null "*) probe=1 ;;
    esac
  fi

  if [ "$probe" -eq 1 ]; then
    catat "probe rc=1 (baca banner, normal) ${took}s :: ${cmd[*]:0:8} ..."
  else
    sebab="rc=$rc"
    if [ "$rc" -eq 137 ] || [ "$rc" -eq 9 ]; then
      sebab="DIBUNUH batas memori (MemoryMax=$MEMMAX)"
    fi
    catat "❌ ffguard $sebab ${took}s :: ${cmd[*]:0:12} ..."
    echo "❌ ffguard: $sebab setelah ${took}s — MemoryMax=$MEMMAX, log $LOG" >&2
  fi
else
  catat "ok ${took}s :: ${cmd[*]:0:8} ..."
fi
exit "$rc"
