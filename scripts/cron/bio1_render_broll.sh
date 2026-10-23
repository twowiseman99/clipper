#!/bin/bash
# Make a 720p proxy for every oversized source, then render from the proxy.
#
# WHY: rendering M02 straight from its 1080p/390MB source was killed by the
# OOM killer -- measured, not guessed:
#   bio1render.service: killed by the OOM killer
#   Consumed 1min 21s CPU, 6.9G memory peak, 1.1G swap peak
# on a 7.6GB box. M05 (720p/106MB) rendered in 66s at 460MB peak. Same 300s
# span, same filter chain; the only difference is pixels per frame.
#
# Three earlier attempts read as "the render fails" because the evidence was
# missing, not because the renderer was broken:
#   * batch calls returned exit -9 with NO output while M01 and M05 were in
#     fact written to disk -- the harness wrapper was dying, ffmpeg was fine
#   * so I blamed a time limit and split the batch, which was also wrong
#   * even the probe I wrote to time the phases got killed, and THAT was the
#     clue: a measuring script has no business dying, so the constraint had
#     to be memory
# Only systemd-run gave a cause instead of a disappearance, because its cgroup
# is what journald records against. Keep running this under systemd-run.
#
# The proxy is written once and reused: scaling 1080p->720p costs one cheap
# pass and takes every later stage (window probing, split/blur/overlay,
# grading) down to the footprint that is already proven to fit.
set -u
cd /home/ubuntu/projects/stockstory/work/bio1
PY=/home/ubuntu/clipper/.venv/bin/python
LOG=/tmp/render_broll.log
MARK=/tmp/render_broll_done
PROXY=src_video/proxy
mkdir -p "$MARK" "$PROXY"

# PAGAR MEMORI + LOCK GLOBAL, dipasang 23 Okt 2026.
#
# Komentar di atas sudah menulis "Keep running this under systemd-run" sejak
# render M02 dibunuh OOM — tapi tidak satu pun systemd-run pernah dipasang di
# skrip ini. Pagar yang sudah diketahui perlu, tidak pernah terpasang; 23 Okt
# ffmpeg OOM empat kali dan menarik hermes-gateway mati bersamanya tiga kali.
#
# ffmpeg di skrip ini (pembuatan proxy) dan ffmpeg di dalam
# build_video_scenes.py dua-duanya lewat shim yang sama, jadi:
#   * MemoryMax -> yang mati cuma ffmpeg, bukan box
#   * flock di SATU path -> render bio1 dan render clipper tidak bisa jalan
#     bersamaan. Sebelum ini bio1 pakai /tmp/render_broll.lock sendiri
#     sementara clipper cuma mengandalkan claim() di SQLite: dua mekanisme
#     berbeda, nol eksklusi antar-job, memori bisa berlipat.
export CLIPPER_FFMPEG=/home/ubuntu/clipper/scripts/ffmpeg_guarded.sh
export FFGUARD_MEMMAX=${FFGUARD_MEMMAX:-3G}
# FFGUARD_THREADS SENGAJA TIDAK DISET. Diukur 23 Okt 2026: render yang sama
# tanpa pagar dua kali menghasilkan md5 IDENTIK (8a70bc4d, dua kali),
# sementara lewat pagar yang menyuntik -threads jadi 6e4e2c6b dengan ukuran
# byte SAMA PERSIS (13.849.191). Jadi renderer ini deterministik dan satu
# argumen suntikan sudah cukup menggeser bit keluaran. Operator minta hasil
# render tidak berubah, jadi pagar hanya membatasi MEMORI -- nol sentuhan ke
# argumen ffmpeg. Batas thread sudah ada di edit.py lewat CLIPPER_THREADS,
# dan box ini cuma 2 vCPU sehingga default cpu_count() memang sudah 2.
FFG=/home/ubuntu/clipper/scripts/ffguard.sh

SCENES="M01 M02 M03 M04 M05 M06 M07 M08 M09 M10 M11 M12 M13 M14 M15 M16 M17 M18 M19 M20"

LOCK=/tmp/render_broll.lock
if [ -e "$LOCK" ] && kill -0 "$(cat "$LOCK" 2>/dev/null)" 2>/dev/null; then
    echo "$(date +%H:%M:%S) sudah ada yang jalan (pid $(cat "$LOCK")), keluar" >> "$LOG"
    exit 0
fi
echo $$ > "$LOCK"
trap 'rm -f "$LOCK"' EXIT

echo "tick $(date +%H:%M:%S)" >> "$LOG"
ok=0; fail=0; skip=0
for s in $SCENES; do
    if [ -f "$MARK/$s" ]; then skip=$((skip+1)); continue; fi
    src="src_video/$s.mp4"
    [ -f "$src" ] || { echo "$s LEWAT: sumber ga ada" >> "$LOG"; fail=$((fail+1)); continue; }

    # Downscale anything above 720p. Sources already at or below 720p are used
    # as-is: re-encoding them would only add a generation of loss.
    h=$(ffprobe -v error -select_streams v:0 -show_entries stream=height \
        -of csv=p=0 "$src" 2>/dev/null | head -1)
    use="$src"
    if [ -n "$h" ] && [ "$h" -gt 720 ] 2>/dev/null; then
        p="$PROXY/$s.mp4"
        if [ ! -f "$p" ]; then
            t0=$(date +%s)
            "$FFG" ffmpeg -v error -y -i "$src" -vf scale=-2:720 \
                   -c:v libx264 -preset veryfast -crf 20 \
                   -c:a copy "$p" 2>>"$LOG"
            if [ ! -s "$p" ]; then
                echo "$s GAGAL bikin proxy" >> "$LOG"; fail=$((fail+1)); continue
            fi
            echo "$s proxy ${h}p->720p $(( $(date +%s) - t0 ))s" >> "$LOG"
        fi
        use="$p"
    fi

    # Hand the renderer the proxy by swapping it in as the scene source.
    # Keeping the original is what lets a re-run go back to full resolution
    # if the memory ceiling ever changes.
    #
    # TRAP, terukur 23 Okt 2026: pemulihan di bawah hanya jalan kalau loop ini
    # SELESAI. Waktu ffmpeg dibunuh OOM mid-render, src_video/M02.mp4.full
    # (1920x1080, 390 MB) tertinggal dan src_video/M02.mp4 tetap berisi proxy
    # 720p — jadi sumber asli "hilang" dari sudut pandang renderer berikutnya,
    # dan ukuran file tidak lagi cocok dengan namanya. Pulihkan lewat trap,
    # supaya SIGKILL/SIGTERM pun tetap mengembalikan nama file.
    if [ "$use" != "$src" ]; then
        mv "$src" "$src.full" && cp "$use" "$src"
        trap 'if [ -f "'"$src"'.full" ]; then rm -f "'"$src"'" && mv "'"$src"'.full" "'"$src"'"; fi; rm -f "$LOCK"' EXIT HUP INT TERM
    fi

    before=$(stat -c %Y "scenes_16x9/$s.mp4" 2>/dev/null || echo 0)
    t0=$(date +%s)
    out=$("$PY" build_video_scenes.py "$s" 2>&1 | tail -3)
    rc=$?
    after=$(stat -c %Y "scenes_16x9/$s.mp4" 2>/dev/null || echo 0)
    took=$(( $(date +%s) - t0 ))

    if [ -f "$src.full" ]; then rm -f "$src" && mv "$src.full" "$src"; fi

    # mtime moved = the renderer wrote the file THIS run. md5 is the wrong
    # instrument: the render is deterministic, so re-rendering the same window
    # is byte-identical and an md5 check called M01 "GAGAL" seconds after it
    # had been written.
    if [ "$rc" -eq 0 ] && [ "$after" -gt "$before" ]; then
        touch "$MARK/$s"
        echo "$s OK ${took}s" >> "$LOG"; ok=$((ok+1))
    else
        echo "$s GAGAL rc=$rc ${took}s mtime $before->$after :: $out" >> "$LOG"
        fail=$((fail+1))
    fi
done
echo "selesai $(date +%H:%M:%S) ok=$ok gagal=$fail dilewati=$skip" >> "$LOG"
