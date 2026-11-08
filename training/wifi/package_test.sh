#!/bin/bash
set -euo pipefail
task_root=/home/pango/work/kosmo-wifi
task_stage="$task_root/stage"
task_release=5.10.0-kosmo-wifi1
test "$(cat "$task_root/kernel-wifi/include/config/kernel.release")" = "$task_release"
test -s "$task_stage/Image-kosmo-wifi1"
test -s "$task_stage/lib/modules/$task_release/extra/8188gu.ko"
for task_tool in iw wpa_supplicant wpa_cli wpa_passphrase usb_modeswitch udhcpc; do
    test -x "$task_stage/usr/sbin/$task_tool"
done
mkdir -p "$task_stage/build-info"
install -D -m 0755 "$task_root/kosmo-wifi" "$task_stage/usr/local/sbin/kosmo-wifi"
install -D -m 0755 "$task_root/kosmo-wifi-udhcpc" "$task_stage/usr/local/libexec/kosmo-wifi-udhcpc"
install -D -m 0755 "$task_root/S42kosmo-wifi" "$task_stage/etc/init.d/S42kosmo-wifi"
install -m 0755 "$task_root/install_runtime.sh" "$task_stage/install_runtime.sh"
install -m 0755 "$task_root/rollback_wifi.sh" "$task_stage/rollback_wifi.sh"
for task_script in "$task_stage/usr/local/sbin/kosmo-wifi" "$task_stage/usr/local/libexec/kosmo-wifi-udhcpc" "$task_stage/etc/init.d/S42kosmo-wifi" "$task_stage/install_runtime.sh" "$task_stage/rollback_wifi.sh"; do
    sh -n "$task_script"
done
cp "$task_root/kernel-wifi/.config" "$task_stage/build-info/kernel.config"
cp "$task_root/kernel-usb-reset.patch" "$task_stage/build-info/"
cp "$task_root/dhcp-build/.config" "$task_stage/build-info/udhcpc.config"
cp "$task_root/src/wpa_supplicant-2.10/wpa_supplicant/.config" "$task_stage/build-info/wpa_supplicant.config"
cp "$task_root/src/RTL8188GU-master/README.md" "$task_stage/build-info/rtl8188gu.README.md"
sha256sum "$task_root"/downloads/*tar.* > "$task_stage/build-info/source-SHA256SUMS"
modinfo "$task_stage/lib/modules/$task_release/extra/8188gu.ko" > "$task_stage/build-info/8188gu.modinfo"
depmod -e -b "$task_stage" -F "$task_root/kernel-wifi/System.map" "$task_release" 2> "$task_root/logs/depmod-check.log"
test ! -s "$task_root/logs/depmod-check.log"
cd "$task_stage"
find . -type f ! -name SHA256SUMS -print0 | LC_ALL=C sort -z | xargs -0 sha256sum > SHA256SUMS
sha256sum -c SHA256SUMS >/dev/null
tar --exclude='./lib/modules/*/build' --exclude='./lib/modules/*/source' \
    -czf "$task_root/kosmo-wifi1.tar.gz" .
sha256sum "$task_root/kosmo-wifi1.tar.gz"
du -h "$task_root/kosmo-wifi1.tar.gz"
printf 'KOSMO_PACKAGE_OK\n'
