#!/bin/bash
set -eu
task_root=/home/pango/work/kosmo-wifi
grep -n -A 8 -B 10 -- '-EALREADY' "$task_root/src/kernel/net/wireless/sme.c" "$task_root/src/kernel/net/wireless/nl80211.c" "$task_root/src/RTL8188GU-master/8188gu-1.0.1/os_dep/linux/ioctl_cfg80211.c" || true
