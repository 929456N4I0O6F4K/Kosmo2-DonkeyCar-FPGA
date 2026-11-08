#!/bin/sh
# Restore the original kernel from the backup made on this Kosmo board.
# Takes effect on the next reboot; does not seize USB resources while running.
set -eu
test "$(id -u)" = 0
mkdir -p /mnt/kosmo-boot
grep -q ' /mnt/kosmo-boot ' /proc/mounts || mount /dev/mmcblk0p1 /mnt/kosmo-boot
mount -o remount,rw /mnt/kosmo-boot
echo 'e88ee74708d950bbfc2aad10188d036afef00d86507f672bff3272bb5aed4bbe  /mnt/kosmo-boot/Image.pre-wifi1' | sha256sum -c -
cp /mnt/kosmo-boot/Image.pre-wifi1 /mnt/kosmo-boot/Image.restore
sync
echo 'e88ee74708d950bbfc2aad10188d036afef00d86507f672bff3272bb5aed4bbe  /mnt/kosmo-boot/Image.restore' | sha256sum -c -
mv /mnt/kosmo-boot/Image.restore /mnt/kosmo-boot/Image
rm -f /etc/kosmo-wifi.enabled
# This board used the power-only service before the Wi-Fi migration.
touch /etc/kosmo-usb-power.enabled
sync
echo 'Original kernel and power-only boot mode restored. Reboot when ready.'
