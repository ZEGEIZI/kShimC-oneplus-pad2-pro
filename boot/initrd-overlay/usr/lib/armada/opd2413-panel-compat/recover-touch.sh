#!/bin/sh
# Run as the existing desktop user before KWin reads its device preferences.
set -eu
umask 077
[ "$#" -eq 0 ] || exit 2
[ "$(id -u)" = 1000 ] || exit 2
grep -azFxq oneplus,opd2413 /sys/firmware/devicetree/base/compatible || exit 2
[ "$(uname -r)" = 7.2.6-opd2413-full-system03 ] || exit 2
[ -e /run/ostree-booted ] && [ ! -e /etc/initrd-release ] || exit 2
config=/var/home/armada/.config/kcminputrc
if [ ! -e "$config" ]; then
    echo 'OPD2413_TOUCH_RECOVERY no-user-setting; default-enabled'
    exit 0
fi
[ -f "$config" ] && [ ! -L "$config" ] && [ "$(stat -c %u "$config")" = 1000 ] || exit 2
before=$(/usr/bin/kreadconfig6 --file "$config" --group Libinput --group 0 --group 0 \
    --group NVTCapacitiveTouchScreen --key Enabled --default true)
case "$before" in
    true|True|TRUE|1) echo 'OPD2413_TOUCH_RECOVERY already-enabled'; exit 0 ;;
    false|False|FALSE|0) ;;
    *) echo 'OPD2413_TOUCH_RECOVERY unknown-value; no change'; exit 2 ;;
esac
boot_id=$(cat /proc/sys/kernel/random/boot_id)
case "$boot_id" in *[!0-9a-f-]*|'') exit 2 ;; esac
backup="$config.opd2413-touch-$boot_id.bak"
[ ! -e "$backup" ] && [ ! -L "$backup" ] || exit 2
cp -p "$config" "$backup"
chmod 0600 "$backup"
/usr/bin/kwriteconfig6 --file "$config" --group Libinput --group 0 --group 0 \
    --group NVTCapacitiveTouchScreen --key Enabled --type bool true
after=$(/usr/bin/kreadconfig6 --file "$config" --group Libinput --group 0 --group 0 \
    --group NVTCapacitiveTouchScreen --key Enabled --default false)
[ "$after" = true ] || exit 2
echo 'OPD2413_TOUCH_RECOVERY changed-disabled-to-enabled'
printf 'backup=%s\n' "$backup"
