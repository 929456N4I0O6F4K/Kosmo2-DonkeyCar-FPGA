#!/bin/bash
set -eu
python3 /home/pango/work/kosmo-wifi/vm_boot.py \
    --port /dev/ttyUSB0 --output /home/pango/work/kosmo-wifi/logs/wifi1-boot.log \
    --uboot-command 'setenv bootargs console=ttyS0,115200 earlycon=ns16550a,mmio32,0xe5000000 root=/dev/mmcblk0p2 rootwait rw; if fatload mmc 0:1 0x6000000 Image-kosmo-wifi1; then if fatload mmc 0:1 0x4000000 kosmo2-pg2k100-400pin-demo.dtb; then booti 0x6000000 - 0x4000000; fi; fi' \
    --wait-linux
