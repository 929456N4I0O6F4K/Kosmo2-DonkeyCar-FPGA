#!/bin/bash
set -eu
task_root=/home/pango/work/kosmo-wifi
grep -n -E 'KSRC|modules:|modules_install|MODULE_IMPORT_NS' \
    "$task_root/src/RTL8188GU-master/8188gu-1.0.1/Makefile" \
    "$task_root/src/RTL8188GU-master/8188gu-1.0.1/os_dep/linux/os_intfs.c" | tail -n 12
for task_package in libnl libusb usb_modeswitch; do
    head -n 18 "$task_root/kosmo2/pango_rootfs/package/$task_package/$task_package.mk"
    cat "$task_root/kosmo2/pango_rootfs/package/$task_package/$task_package.hash"
done
cat "$task_root/kosmo2/pango_rootfs/package/iw/iw.hash"
cat "$task_root/kosmo2/pango_rootfs/package/wpa_supplicant/wpa_supplicant.hash"
command -v pkg-config autoconf automake libtoolize
