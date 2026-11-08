#!/bin/bash
set -euo pipefail
task_root=/home/pango/work/kosmo-wifi
mkdir -p "$task_root/http"
ln -f "$task_root/kosmo-wifi1-test.tar.gz" "$task_root/http/kosmo-wifi1-test.tar.gz"
cd "$task_root/http"
sha256sum kosmo-wifi1-test.tar.gz > SHA256SUMS
if [ -f "$task_root/logs/http.pid" ] && kill -0 "$(cat "$task_root/logs/http.pid")" 2>/dev/null; then
    printf 'Existing package server is running\n'
else
    nohup python3 -m http.server 8765 --bind 0.0.0.0 < /dev/null > "$task_root/logs/http.log" 2>&1 &
    printf '%s\n' "$!" > "$task_root/logs/http.pid"
fi
