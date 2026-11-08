#!/bin/bash
# Small static ARM64 tools; leaves the existing board rootfs in place.
set -euo pipefail
task_root=/home/pango/work/kosmo-wifi
task_cross=/opt/gcc-linaro-7.5.0-2019.12-i686_aarch64-linux-gnu/bin/aarch64-linux-gnu-
task_deps="$task_root/wifi-deps"
task_stage="$task_root/stage"
mkdir -p "$task_root/downloads" "$task_root/src" "$task_deps" "$task_stage/usr/sbin" "$task_stage/usr/share/licenses/kosmo-wifi"

fetch() {
    local task_name=$1 task_hash=$2 task_url=$3 task_package=$4
    if [ ! -f "$task_root/downloads/$task_name" ]; then
        curl -fL --connect-timeout 10 --max-time 90 "$task_url" -o "$task_root/downloads/$task_name.partial" || \
            curl -fL --connect-timeout 10 --max-time 90 "https://sources.buildroot.net/$task_package/$task_name" -o "$task_root/downloads/$task_name.partial"
        mv "$task_root/downloads/$task_name.partial" "$task_root/downloads/$task_name"
    fi
    printf '%s  %s\n' "$task_hash" "$task_root/downloads/$task_name" | sha256sum -c -
}
fetch libnl-3.6.0.tar.gz 532155fd011e5a805bd67121b87a01c757e2bb24112ac17e69cb86013b970009 \
    https://github.com/thom311/libnl/releases/download/libnl3_6_0/libnl-3.6.0.tar.gz libnl
fetch iw-5.16.tar.xz 4c44e42762f903f9094ba5a598998c800a97a62afd6fd31ec1e0a799e308659c \
    https://www.kernel.org/pub/software/network/iw/iw-5.16.tar.xz iw
fetch wpa_supplicant-2.10.tar.gz 20df7ae5154b3830355f8ab4269123a87affdea59fe74fe9292a91d0d7e17b2f \
    https://w1.fi/releases/wpa_supplicant-2.10.tar.gz wpa_supplicant
fetch libusb-1.0.26.tar.bz2 12ce7a61fc9854d1d2a1ffe095f7b5fac19ddba095c259e6067a46500381b5a5 \
    https://github.com/libusb/libusb/releases/download/v1.0.26/libusb-1.0.26.tar.bz2 libusb
fetch usb-modeswitch-2.6.1.tar.bz2 5195d9e136e52f658f19e9f93e4f982b1b67bffac197d0a455cd8c2cd245fa34 \
    https://www.draisberghof.de/usb_modeswitch/usb-modeswitch-2.6.1.tar.bz2 usb_modeswitch
for task_name in libnl-3.6.0 iw-5.16 wpa_supplicant-2.10 libusb-1.0.26 usb-modeswitch-2.6.1; do
    if [ ! -d "$task_root/src/$task_name" ]; then
        tar -xf "$task_root/downloads/$task_name".tar.* -C "$task_root/src" --no-same-owner
    fi
done

cd "$task_root/src/libnl-3.6.0"
if [ ! -f Makefile ]; then
    CC="${task_cross}gcc" AR="${task_cross}ar" RANLIB="${task_cross}ranlib" \
        ./configure --host=aarch64-linux-gnu --prefix="$task_deps" --disable-shared --enable-static --disable-cli
fi
make -j2
make install

export PKG_CONFIG_LIBDIR="$task_deps/lib/pkgconfig"
cd "$task_root/src/iw-5.16"
make -j2 CC="${task_cross}gcc" PKG_CONFIG='pkg-config --static' LDFLAGS=-static
install -m 0755 iw "$task_stage/usr/sbin/iw"

cd "$task_root/src/wpa_supplicant-2.10/wpa_supplicant"
cat > .config <<EOF
CONFIG_DRIVER_NL80211=y
CONFIG_DRIVER_WEXT=y
CONFIG_LIBNL32=y
CONFIG_CTRL_IFACE=y
CONFIG_BACKEND=file
CONFIG_TLS=internal
CONFIG_INTERNAL_LIBTOMMATH=y
CONFIG_INTERNAL_LIBTOMMATH_FAST=y
CONFIG_DEBUG_FILE=y
CONFIG_NO_CONFIG_WRITE=y
CC=${task_cross}gcc
CFLAGS += -I$task_deps/include/libnl3
LDFLAGS += -static -L$task_deps/lib
LIBS += -lnl-3 -lm -lpthread
EOF
make -j2 wpa_supplicant wpa_cli wpa_passphrase
install -m 0755 wpa_supplicant wpa_cli wpa_passphrase "$task_stage/usr/sbin/"

cd "$task_root/src/libusb-1.0.26"
if [ ! -f Makefile ]; then
    CC="${task_cross}gcc" AR="${task_cross}ar" RANLIB="${task_cross}ranlib" \
        ./configure --host=aarch64-linux-gnu --prefix="$task_deps" --disable-shared --enable-static --disable-udev
fi
make -j2
make install
cd "$task_root/src/usb-modeswitch-2.6.1"
"${task_cross}gcc" -Os -static $(pkg-config --cflags libusb-1.0) usb_modeswitch.c -o usb_modeswitch \
    $(pkg-config --libs --static libusb-1.0) -lrt
install -m 0755 usb_modeswitch "$task_stage/usr/sbin/usb_modeswitch"

for task_name in iw-5.16 libnl-3.6.0 libusb-1.0.26 usb-modeswitch-2.6.1; do
    cp "$task_root/src/$task_name/COPYING" "$task_stage/usr/share/licenses/kosmo-wifi/$task_name.COPYING"
done
cp "$task_root/src/wpa_supplicant-2.10/README" "$task_stage/usr/share/licenses/kosmo-wifi/wpa_supplicant.README"
"${task_cross}strip" "$task_stage/usr/sbin/iw" "$task_stage/usr/sbin/wpa_supplicant" \
    "$task_stage/usr/sbin/wpa_cli" "$task_stage/usr/sbin/wpa_passphrase" "$task_stage/usr/sbin/usb_modeswitch"
file "$task_stage"/usr/sbin/*
sha256sum "$task_stage"/usr/sbin/*
printf 'KOSMO_USERSPACE_BUILD_OK\n'
