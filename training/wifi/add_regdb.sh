#!/bin/bash
set -euo pipefail
task_root=/home/pango/work/kosmo-wifi
task_name=wireless-regdb-2022.02.18
if [ ! -f "$task_root/downloads/$task_name.tar.xz" ]; then
    curl -fL --connect-timeout 10 --max-time 90 \
        "https://www.kernel.org/pub/software/network/wireless-regdb/$task_name.tar.xz" \
        -o "$task_root/downloads/$task_name.tar.xz.partial"
    mv "$task_root/downloads/$task_name.tar.xz.partial" "$task_root/downloads/$task_name.tar.xz"
fi
printf '%s  %s\n' 8828c25a4ee25020044004f57374bb9deac852809fad70f8d3d01770bf9ac97f "$task_root/downloads/$task_name.tar.xz" | sha256sum -c -
tar -xf "$task_root/downloads/$task_name.tar.xz" -C "$task_root/src" --no-same-owner
install -D -m 644 "$task_root/src/$task_name/regulatory.db" "$task_root/stage/lib/firmware/regulatory.db"
install -D -m 644 "$task_root/src/$task_name/regulatory.db.p7s" "$task_root/stage/lib/firmware/regulatory.db.p7s"
cp "$task_root/src/$task_name/LICENSE" "$task_root/stage/usr/share/licenses/kosmo-wifi/wireless-regdb.LICENSE"
sha256sum "$task_root/stage/lib/firmware/"*
