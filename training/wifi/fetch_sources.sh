#!/bin/bash
set -euo pipefail
task_root=/home/pango/work/kosmo-wifi
mkdir -p "$task_root/downloads" "$task_root/src"
cd "$task_root/downloads"
# Retain the downloaded snapshot and its hash for reproducibility.
if [ ! -s rtl8188gu.tar.gz ]; then
    curl --fail --location --connect-timeout 15 --max-time 180 \
        https://codeload.github.com/wandercn/RTL8188GU/tar.gz/refs/heads/master \
        -o rtl8188gu.tar.gz.partial
    mv rtl8188gu.tar.gz.partial rtl8188gu.tar.gz
fi
printf '%s  %s\n' 73fb24554639877cdc5a18b7190ac9a406db714faa0b2eb273f4bd702b741dc5 rtl8188gu.tar.gz | sha256sum -c -
if [ ! -d "$task_root/src/RTL8188GU-master" ]; then
    tar -xzf rtl8188gu.tar.gz -C "$task_root/src" --no-same-owner
fi
head -n 180 "$task_root/src/RTL8188GU-master/8188gu-1.0.1/Makefile"
