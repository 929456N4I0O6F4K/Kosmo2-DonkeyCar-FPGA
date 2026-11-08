#!/bin/bash
# Build an isolated USB/Wi-Fi test kernel from the surveyed board config.
set -euo pipefail
task_root=/home/pango/work/kosmo-wifi
task_src="$task_root/src/kernel"
task_out="$task_root/kernel-wifi"
task_cross=/opt/gcc-linaro-7.5.0-2019.12-i686_aarch64-linux-gnu/bin/aarch64-linux-gnu-
mkdir -p "$task_root/src" "$task_out" "$task_root/stage" "$task_root/logs"
if [ ! -d "$task_src" ]; then
    cp -a "$task_root/kosmo2/pango_kernel" "$task_src"
fi
# The vendor HCD source has CRLF endings; normalize only the patched files.
python3 - "$task_src" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
for name in ('drivers/usb/phy/phy-ulpi.c', 'drivers/usb/dwc2/hcd.c'):
    path = root / name
    data = path.read_bytes()
    if b'\r\n' in data:
        path.write_bytes(data.replace(b'\r\n', b'\n'))
PY
if patch -d "$task_src" -p1 --dry-run --forward < "$task_root/kernel-usb-reset.patch" >/dev/null 2>&1; then
    patch -d "$task_src" -p1 --forward < "$task_root/kernel-usb-reset.patch"
else
    patch -d "$task_src" -p1 --dry-run --reverse < "$task_root/kernel-usb-reset.patch"
fi
if [ ! -f "$task_out/.config" ]; then
    cp "$task_root/board-kernel.config" "$task_out/.config"
fi
"$task_src/scripts/config" --file "$task_out/.config" \
    --set-str LOCALVERSION '-kosmo-wifi1' --disable LOCALVERSION_AUTO \
    --enable CFG80211 --enable CFG80211_WEXT --enable RFKILL
make -C "$task_src" O="$task_out" ARCH=arm64 CROSS_COMPILE="$task_cross" olddefconfig
make -C "$task_src" O="$task_out" ARCH=arm64 CROSS_COMPILE="$task_cross" -j2 Image modules
make -C "$task_src" O="$task_out" ARCH=arm64 CROSS_COMPILE="$task_cross" \
    INSTALL_MOD_PATH="$task_root/stage" modules_install
cp "$task_out/arch/arm64/boot/Image" "$task_root/stage/Image-kosmo-wifi1"
sha256sum "$task_root/stage/Image-kosmo-wifi1"
printf 'KOSMO_KERNEL_BUILD_OK\n'
