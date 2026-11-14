#!/bin/sh
# Keep bounded wake error observations in kmsg instead of per-IRQ DRM debug spam.
opd2413_quiet_drm() {
    [ -r /etc/initrd-release ] || return 0
    grep -azFxq oneplus,opd2413 /sys/firmware/devicetree/base/compatible || return 0
    [ "$(uname -r)" = 7.2.6-opd2413-full-system03 ] || return 0
    [ "$(tr -d '\000' < /sys/firmware/devicetree/base/chosen/armada,rootfs-profile)" = opd2413-bootc-rootfs-v1 ] || return 0
    [ "$(stat -f -c %T /run)" = tmpfs ] || return 1
    [ -f /sys/module/drm/parameters/debug ] || return 1
    [ ! -e /run/opd2413-drm-observation ] && [ ! -L /run/opd2413-drm-observation ] || return 1
    (umask 077; set -C; cat /sys/module/drm/parameters/debug > /run/opd2413-drm-observation) || return 1
    printf '0\n' > /sys/module/drm/parameters/debug || return 1
    [ "$(cat /sys/module/drm/parameters/debug)" = 0 ] || return 1
    info 'OPD2413_DRM_VERBOSE_DISABLED bounded DSI wake observations remain enabled'
}
opd2413_quiet_drm
