#!/bin/sh
# Run as root from an extracted, verified Kosmo Wi-Fi package.
set -eu
test "$(id -u)" = 0
test "$(uname -r)" = 5.10.0-kosmo-wifi1
cd "$(dirname "$0")"
sha256sum -c SHA256SUMS > /tmp/kosmo-wifi-install.check
backup=/var/lib/kosmo-wifi/files-before
mkdir -p "$backup" /usr/local/sbin /usr/local/libexec /lib/firmware /etc/kosmo-wifi
chmod 700 /etc/kosmo-wifi
for relative in usr/sbin/iw usr/sbin/wpa_supplicant usr/sbin/wpa_cli usr/sbin/wpa_passphrase usr/sbin/usb_modeswitch usr/sbin/udhcpc usr/local/sbin/kosmo-wifi usr/local/libexec/kosmo-wifi-udhcpc etc/init.d/S42kosmo-wifi lib/firmware/regulatory.db lib/firmware/regulatory.db.p7s; do
    if [ -e "/$relative" ] && [ ! -e "$backup/$relative" ]; then
        mkdir -p "$backup/$(dirname "$relative")"
        cp -p "/$relative" "$backup/$relative"
    fi
    cp -p "$relative" "/$relative"
    chown 0:0 "/$relative"
    case "$relative" in
        lib/firmware/*) chmod 644 "/$relative";;
        *) chmod 755 "/$relative";;
    esac
done
mkdir -p /usr/share/licenses/kosmo-wifi
cp usr/share/licenses/kosmo-wifi/* /usr/share/licenses/kosmo-wifi/
for file in /usr/local/sbin/kosmo-wifi /usr/local/libexec/kosmo-wifi-udhcpc /etc/init.d/S42kosmo-wifi; do
    sh -n "$file"
done
test ! -e /etc/kosmo-usb-power.enabled
touch /etc/kosmo-wifi.enabled
sync
echo 'Wi-Fi tools installed; kernel activation is a separate step.'
