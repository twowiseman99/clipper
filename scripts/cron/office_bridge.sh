#!/usr/bin/env bash
# Jembatan nama event: Hermes -> Claude-Office (W17ant/Claude-Office).
#
# KENAPA PERLU (diukur 23 Okt 2026, bukan dugaan):
# Payload stdin Hermes dan Claude Code SATU STRUKTUR — hook_event_name,
# tool_name, tool_input, session_id, cwd. Yang beda cuma NILAI event-nya:
#
#   Hermes       pre_tool_call   post_tool_call   on_session_start  subagent_stop
#   Claude Code  PreToolUse      PostToolUse      SessionStart      SubagentStop
#
# Dibuktikan dengan penangkap HTTP di 127.0.0.1:3334:
#   payload "PreToolUse"     -> tracker POST {"type":"agent_working", ...}
#   payload "pre_tool_call"  -> NOL POST, RC=0, diam total
#
# RC=0 dua-duanya, jadi exit code TIDAK bisa dipakai membedakan "diterima"
# dari "ditolak". Pembuktian wajib lewat efek samping (POST yang benar-benar
# keluar), bukan lewat status keluar.
#
# tool_name TIDAK diterjemahkan: tracker menerima nama apa pun dan menulis
# "using <nama>" untuk yang tidak dikenalnya (diukur: tool_name=terminal
# tembus sebagai {"tool":"terminal","status":"using terminal"}). Memetakan
# terminal->Bash cuma akan memalsukan nama tool yang sebenarnya dipakai.
#
# Dipakai dari ~/.hermes/config.yaml:
#   hooks:
#     pre_tool_call:
#       - command: "/home/ubuntu/.hermes/scripts/office_bridge.sh"
#     post_tool_call:
#       - command: "/home/ubuntu/.hermes/scripts/office_bridge.sh"
#
# Hook ini OBSERVER: tidak pernah mencetak JSON keputusan, jadi tidak bisa
# memblokir atau mengubah tool call. Keluaran selalu kosong, exit 0.
set -u

TRACKER="${OFFICE_TRACKER:-$HOME/skill-sources/Claude-Office/hooks/agent-tracker.sh}"
[ -f "$TRACKER" ] || exit 0

# JEBAKAN yang sudah dibayar sekali: `python3 - <<'PY'` memakai heredoc
# sebagai STDIN, jadi payload yang dipipe ke hook ini tidak pernah sampai --
# json.load(sys.stdin) membaca kode Python-nya sendiri, gagal parse, exit 0.
# Diam, RC=0, nol POST: persis seperti "payload ditolak". Dua sebab berbeda,
# satu gejala. Jadi kodenya ditaruh di file terpisah dan stdin dibiarkan utuh.
BRIDGE_PY="${OFFICE_BRIDGE_PY:-$HOME/.hermes/scripts/office_bridge.py}"
[ -f "$BRIDGE_PY" ] || exit 0
exec python3 "$BRIDGE_PY" "$TRACKER"