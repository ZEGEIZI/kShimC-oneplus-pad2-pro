#!/bin/sh
# Fixed, explicit diagnostic entry point. No caller arguments or disk writes.
set -eu
umask 077
[ "$#" -eq 0 ] || exit 2
[ "$(id -u)" = 0 ] || exit 2
[ "$(stat -f -c %T /run)" = tmpfs ] || exit 2
grep -azFxq oneplus,opd2413 /sys/firmware/devicetree/base/compatible || exit 2
[ "$(tr -d '\000' < /sys/firmware/devicetree/base/chosen/armada,rootfs-profile)" = opd2413-bootc-rootfs-v1 ] || exit 2
[ "$(uname -r)" = 7.2.6-opd2413-full-system03 ] || exit 2
[ -e /run/ostree-booted ] && [ ! -e /etc/initrd-release ] || exit 2
[ "$(id -u armada)" = 1000 ] && [ "$(id -g armada)" = 1000 ] || exit 2
archive=/run/opd2413-gdb-upload.tar.gz
base=/run/opd2413-gdb
[ -f "$archive" ] && [ ! -L "$archive" ] || exit 2
[ "$(stat -c %s "$archive")" = 5675279 ] || exit 2
printf '%s  %s\n' 21dcc8fa6b6b0290bf91ab46257cd701690b8df2da11c37f974d07d6ee252fb7 "$archive" | /usr/bin/sha256sum -c --status || exit 2
[ ! -e "$base" ] && [ ! -L "$base" ] || exit 2
[ -S /run/user/1000/bus ] || exit 2
wayland_socket=
for socket in /run/user/1000/wayland-*; do
    [ -S "$socket" ] || continue
    [ -z "$wayland_socket" ] || { echo 'Multiple Wayland sockets; no debug process started.'; exit 2; }
    wayland_socket=$socket
done
[ -n "$wayland_socket" ] || { echo 'Wayland is not ready; no debug process started.'; exit 2; }
printf 'OPD2413_DESKTOP_RUN_V1\n'
# Extraction is permitted only after verifying the complete fixed archive.
mkdir -m 0700 "$base"
/usr/bin/tar -xzf "$archive" -C "$base" --no-same-owner --no-same-permissions
chmod 0700 "$base/bin/gdb" "$base/bin/run-plasmashell-once.sh"
chown -R 1000:1000 "$base"
export XDG_RUNTIME_DIR=/run/user/1000
export HOME=/var/home/armada USER=armada LOGNAME=armada
export XDG_CONFIG_HOME=/var/home/armada/.config
export XDG_DATA_HOME=/var/home/armada/.local/share
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
export WAYLAND_DISPLAY=${wayland_socket##*/}
export QT_QPA_PLATFORM=wayland
export XDG_SESSION_TYPE=wayland
export XDG_CURRENT_DESKTOP=KDE
# Only this existing user's known shell is stopped; KWin and Welcome stay up.
/usr/bin/timeout --signal=TERM --kill-after=2s 15s /usr/bin/setpriv --reuid=1000 --regid=1000 --init-groups \
    /usr/bin/systemctl --user stop plasma-plasmashell.service
echo 'Existing Plasma shell service stopped; running one bounded user debugger.'
status=0
# The user manager holds the active Mobile session environment. A direct
# setpriv child would inherit this root helper's minimal environment and could
# start the desktop shell instead of the mobile shell being diagnosed.
/usr/bin/setpriv --reuid=1000 --regid=1000 --init-groups \
    /usr/bin/systemd-run --user --wait --pipe --collect \
    --unit=opd2413-desktop-gdb.service \
    --property=RuntimeMaxSec=140s --property=TimeoutStopSec=5s \
    --setenv=WAYLAND_DISPLAY="$WAYLAND_DISPLAY" \
    --setenv=PLASMA_DEFAULT_SHELL=org.kde.plasma.mobileshell \
    "$base/bin/run-plasmashell-once.sh" || status=$?
printf 'OPD2413_DESKTOP_RUN_FINISHED exit=%s\n' "$status"
exit "$status"
