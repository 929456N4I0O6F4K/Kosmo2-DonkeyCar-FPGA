#!/bin/bash
set -eu
task_root=/home/pango/work/kosmo-wifi
if [ -f "$task_root/logs/http.pid" ]; then
    task_pid=$(cat "$task_root/logs/http.pid")
    if [ "$(readlink "/proc/$task_pid/cwd" 2>/dev/null || true)" = "$task_root/http" ] && \
       tr '\0' ' ' < "/proc/$task_pid/cmdline" | grep -q 'python3 -m http.server 8765'; then
        kill "$task_pid"
        rm "$task_root/logs/http.pid"
        printf 'Temporary HTTP server stopped\n'
    fi
fi
test -z "$(find "$task_root/private" -maxdepth 1 -type f -print -quit)"
printf 'No temporary Wi-Fi credential files remain on the VM\n'
