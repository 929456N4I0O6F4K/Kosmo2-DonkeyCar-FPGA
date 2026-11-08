#!/bin/bash
set -eu
task_root=/home/pango/work/kosmo-wifi
"$task_root/kernel-wifi/scripts/dtc/dtc" -I dtb -O dts \
    -o "$task_root/board-live.dts" "$task_root/board-live.dtb" 2> "$task_root/logs/dtc-board.log"
grep -A 24 -B 4 -E 'ulpi-phy|usb@f004|usb0|skip-phy|drv-vbus' "$task_root/board-live.dts"
grep -n -E 'MODULE_IMPORT_NS|MODULE_LICENSE' "$task_root/src/RTL8188GU-master/8188gu-1.0.1/os_dep/linux/os_intfs.c"
grep -n -E 'MODULE_NAME|CONFIG_PLATFORM_ARM64|CONFIG_PLATFORM_I386_PC|CONFIG_POWER_SAVING|CONFIG_USB_AUTOSUSPEND' "$task_root/src/RTL8188GU-master/8188gu-1.0.1/Makefile"
grep -n -E 'usb/|gpio/|phy/' "$task_root/src/kernel/drivers/Makefile"
grep -n -E 'phy/|dwc2/' "$task_root/src/kernel/drivers/usb/Makefile"
command -v qemu-aarch64 || true
