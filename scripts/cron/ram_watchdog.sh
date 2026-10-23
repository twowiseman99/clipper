#!/usr/bin/env bash
# Watchdog memori (RAM + Swap) untuk server 43.157.203.118
# Dijalankan via cron no_agent: true ke channel #console-notif.
#
# Pola watchdog:
# - Normal (< 80% RAM terpakai): stdout KOSONG (silent, tidak spam Discord)
# - Bahaya (>= 80% RAM terpakai atau Swap > 70%): cetak alert berisi status RAM,
#   swap, load, dan top 5 proses pemakan RSS terbesar.
set -euo pipefail

THRESHOLD_RAM=${RAM_WATCHDOG_THRESHOLD:-80}
THRESHOLD_SWAP=${SWAP_WATCHDOG_THRESHOLD:-70}

mem_total_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
mem_avail_kb=$(awk '/MemAvailable/ {print $2}' /proc/meminfo)
swap_total_kb=$(awk '/SwapTotal/ {print $2}' /proc/meminfo)
swap_free_kb=$(awk '/SwapFree/ {print $2}' /proc/meminfo)

mem_used_kb=$(( mem_total_kb - mem_avail_kb ))
ram_pct=$(( mem_used_kb * 100 / mem_total_kb ))

swap_used_kb=$(( swap_total_kb - swap_free_kb ))
swap_pct=0
if [ "$swap_total_kb" -gt 0 ]; then
  swap_pct=$(( swap_used_kb * 100 / swap_total_kb ))
fi

# Cek apakah melewati batas
if [ "$ram_pct" -lt "$THRESHOLD_RAM" ] && [ "$swap_pct" -lt "$THRESHOLD_SWAP" ]; then
  # Sehat -> diam
  exit 0
fi

# Jika lewat batas -> cetak alert ke stdout (auto-deliver ke Discord oleh scheduler)
ram_used_gb=$(awk "BEGIN {printf \"%.1f\", $mem_used_kb/1024/1024}")
ram_avail_gb=$(awk "BEGIN {printf \"%.1f\", $mem_avail_kb/1024/1024}")
ram_total_gb=$(awk "BEGIN {printf \"%.1f\", $mem_total_kb/1024/1024}")
swap_used_mb=$(awk "BEGIN {printf \"%.0f\", $swap_used_kb/1024}")
swap_total_gb=$(awk "BEGIN {printf \"%.1f\", $swap_total_kb/1024/1024}")
load_str=$(cat /proc/loadavg | awk '{print $1", "$2", "$3}')

echo "⚠️ MEMORY ALERT — RAM/Swap Tinggi di 43.157.203.118"
echo "• RAM: ${ram_used_gb} GiB used / ${ram_avail_gb} GiB avail (${ram_total_gb} GiB total, ${ram_pct}% used)"
echo "• Swap: ${swap_used_mb} MiB used / ${swap_total_gb} GiB total (${swap_pct}% used)"
echo "• Load average: ${load_str}"
echo "• Top 5 proses pemakan RAM terbesar:"
ps -eo pid,rss,comm --sort=-rss | awk 'NR>1 && $2>1024 {printf "  - %-16s (pid %s): %.0f MB\n", $3, $1, $2/1024}' | head -5
