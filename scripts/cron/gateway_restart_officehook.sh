#!/usr/bin/env bash
# Restart gateway supaya display.blok hooks: office_bridge BENERAN berlaku.
#
# Kenapa restart perlu: gateway/run.py:6769 baca mode itu SEKALI pas start lalu
# nyimpen di self._busy_input_mode, dan _effective_busy_input_mode() nyebut
# dirinya "startup snapshot". Jadi config.yaml yang udah ketulis queue TIDAK
# ngubah perilaku gateway yang sedang jalan. File di disk dan nilai yang
# berlaku itu dua hal beda.
#
# Kenapa systemd transient unit, BUKAN cron Hermes: cron Hermes jalan DI DALAM
# proses gateway, jadi dia bakal matiin interpreternya sendiri di tengah jalan
# dan ga ada yang bisa lapor hasilnya. systemd-run dapet cgroup sendiri, jadi
# dia selamat dari restart yang dia picu.
set -u

MARKER=/home/ubuntu/.hermes/logs/.gateway-restart-officehook.done
LOG=/home/ubuntu/.hermes/logs/gateway-restart-officehook-$(date +%Y%m%d-%H%M%S).log
exec >>"$LOG" 2>&1

# Idempoten: timer yang kebetulan berulang jadi ga berbahaya. Guard ini bukan
# hiasan -- percobaan sebelumnya bikin unit HARIAN karena kalender
# '*-*-* HH:MM:SS' itu recurring, dan perintah buat ngehapusnya ditolak dari
# dalam gateway. Jadi scriptnya yang dibikin aman diulang.
if [ -e "$MARKER" ]; then
    echo "$(date '+%F %T %Z') SKIP: udah pernah jalan ($(cat "$MARKER"))."
    exit 0
fi

echo "=== $(date '+%F %T %Z') restart buat blok hooks: office_bridge ==="

before_pid=$(systemctl --user show -p MainPID --value hermes-gateway.service)
echo "PID sebelum  : $before_pid"
echo "config disk  : $(grep -o 'busy_input_mode: [a-z]*' /home/ubuntu/.hermes/config.yaml)"

# Marker ditulis SEBELUM restart: `systemctl restart` matiin pohon proses
# script ini sendiri, jadi marker yang ditulis SESUDAH bisa ga pernah
# kesampe -- dan timer berikutnya bakal restart lagi.
date '+%F %T %Z' > "$MARKER"

systemctl --user restart hermes-gateway.service
echo "exit restart : $?"

# Kesiapan diukur dari PID BARU, bukan sleep buta.
for i in $(seq 1 30); do
    sleep 2
    state=$(systemctl --user is-active hermes-gateway.service)
    after_pid=$(systemctl --user show -p MainPID --value hermes-gateway.service)
    if [ "$state" = "active" ] && [ -n "$after_pid" ] && [ "$after_pid" != "0" ] \
       && [ "$after_pid" != "$before_pid" ]; then
        echo "PID sesudah  : $after_pid  (naik setelah ${i} polling)"
        echo "state        : $state"
        echo "OK: proses baru, jadi snapshot start baca queue."
        exit 0
    fi
done

echo "GAGAL: unit ga nyampe active dengan PID baru dalam 60s."
systemctl --user status hermes-gateway.service --no-pager | head -20
exit 1
