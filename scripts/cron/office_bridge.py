#!/usr/bin/env python3
"""Terjemahkan nama event hook Hermes ke nama Claude Code, lalu teruskan.

Dipanggil oleh office_bridge.sh dengan path tracker sebagai argv[1] dan
payload hook di stdin. Lihat office_bridge.sh untuk alasan dan bukti ukurnya.
"""
import json
import subprocess
import sys

# Hanya event yang office-nya benar-benar pakai. Event Hermes yang tidak ada
# padanannya dibiarkan lewat tanpa diterjemahkan -- lebih baik diam daripada
# mengarang nama event yang tidak dikenal penerimanya.
PETA = {
    "pre_tool_call": "PreToolUse",
    "post_tool_call": "PostToolUse",
    "on_session_start": "SessionStart",
    "on_session_end": "SessionEnd",
    "subagent_stop": "SubagentStop",
    "pre_llm_call": "UserPromptSubmit",
}


def main():
    if len(sys.argv) < 2:
        return 0
    tracker = sys.argv[1]

    try:
        d = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(d, dict):
        return 0

    baru = PETA.get(d.get("hook_event_name", ""))
    if not baru:
        return 0
    d["hook_event_name"] = baru

    # cwd wajib ada: office memakai basename(cwd) sebagai nama project pada
    # kartu sesi. Tanpa itu kartunya muncul tanpa nama.
    if not d.get("cwd"):
        extra = d.get("extra") if isinstance(d.get("extra"), dict) else {}
        d["cwd"] = extra.get("cwd") or "/home/ubuntu"

    try:
        subprocess.run(["bash", tracker], input=json.dumps(d).encode(),
                       timeout=5, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())