#!/bin/bash
set -euo pipefail
task_root=/home/pango/work/kosmo-wifi
task_cross=/opt/gcc-linaro-7.5.0-2019.12-i686_aarch64-linux-gnu/bin/aarch64-linux-gnu-
task_archive="$task_root/downloads/busybox-1.35.0.tar.bz2"
if [ ! -f "$task_archive" ]; then
    cp "$task_root/kosmo2/pango_rootfs/dl/busybox/busybox-1.35.0.tar.bz2" "$task_archive"
fi
printf '%s  %s\n' faeeb244c35a348a334f4a59e44626ee870fb07b6884d68c10ae8bc19f83a694 "$task_archive" | sha256sum -c -
if [ ! -d "$task_root/src/busybox-1.35.0" ]; then
    tar -xf "$task_archive" -C "$task_root/src" --no-same-owner
fi
task_out="$task_root/dhcp-build"
mkdir -p "$task_out"
make -C "$task_root/src/busybox-1.35.0" O="$task_out" ARCH=arm64 CROSS_COMPILE="$task_cross" allnoconfig
python3 - "$task_out/.config" <<'PY'
from pathlib import Path
import re, sys
p = Path(sys.argv[1])
config = p.read_text()
for key, value in (
    ('STATIC', 'y'), ('UDHCPC', 'y'), ('LONG_OPTS', 'y'),
    ('FEATURE_PIDFILE', 'y'), ('SHOW_USAGE', 'y'), ('FEATURE_VERBOSE_USAGE', 'y'),
    ('FEATURE_UDHCPC_SANITIZEOPT', 'y'),
    ('UDHCPC_DEFAULT_SCRIPT', '"/usr/local/libexec/kosmo-wifi-udhcpc"'),
):
    pattern = r'^(?:# CONFIG_' + key + r' is not set|CONFIG_' + key + r'=.*)$'
    config, count = re.subn(pattern, 'CONFIG_' + key + '=' + value, config, flags=re.M)
    if count != 1:
        raise RuntimeError('Missing/duplicate config: ' + key)
p.write_text(config)
PY
make -C "$task_out" ARCH=arm64 CROSS_COMPILE="$task_cross" oldconfig </dev/null
make -C "$task_out" ARCH=arm64 CROSS_COMPILE="$task_cross" -j2
install -m 0755 "$task_out/busybox" "$task_root/stage/usr/sbin/udhcpc"
cp "$task_root/src/busybox-1.35.0/LICENSE" "$task_root/stage/usr/share/licenses/kosmo-wifi/busybox.LICENSE"
file "$task_root/stage/usr/sbin/udhcpc"
sha256sum "$task_root/stage/usr/sbin/udhcpc"
printf 'KOSMO_DHCP_BUILD_OK\n'
