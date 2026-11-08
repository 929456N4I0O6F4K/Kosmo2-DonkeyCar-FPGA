#!/bin/bash
set -euo pipefail
task_root=/home/pango/work/kosmo-wifi
task_src="$task_root/src/RTL8188GU-master/8188gu-1.0.1"
task_out="$task_root/kernel-wifi"
task_cross=/opt/gcc-linaro-7.5.0-2019.12-i686_aarch64-linux-gnu/bin/aarch64-linux-gnu-
test -s "$task_out/Module.symvers"
task_release=$(cat "$task_out/include/config/kernel.release")
test "$task_release" = 5.10.0-kosmo-wifi1
make -C "$task_src" -j2 ARCH=arm64 CROSS_COMPILE="$task_cross" \
    KSRC="$task_out" KVER="$task_release" modules
install -D -m 644 "$task_src/8188gu.ko" "$task_root/stage/lib/modules/$task_release/extra/8188gu.ko"
depmod -b "$task_root/stage" -F "$task_out/System.map" "$task_release"
modinfo "$task_root/stage/lib/modules/$task_release/extra/8188gu.ko"
sha256sum "$task_root/stage/lib/modules/$task_release/extra/8188gu.ko"
printf 'KOSMO_DRIVER_BUILD_OK\n'
