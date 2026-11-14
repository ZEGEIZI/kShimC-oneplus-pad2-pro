#!/bin/sh
# This exact kernel has CONFIG_ZRAM disabled. Do not generate an absent device.
opd2413_no_zram() {
    [ -r /etc/initrd-release ] || return 0
    grep -azFxq oneplus,opd2413 /sys/firmware/devicetree/base/compatible || return 0
    [ "$(uname -r)" = 7.2.6-opd2413-full-system03 ] || return 0
    [ "$(tr -d '\000' < /sys/firmware/devicetree/base/chosen/armada,rootfs-profile)" = opd2413-bootc-rootfs-v1 ] || return 0
    [ "$(stat -f -c %T /run)" = tmpfs ] || return 1
    local directory=/run/systemd/zram-generator.conf.d
    mkdir -p "$directory" || return 1
    [ ! -e "$directory/99-opd2413-no-zram.conf" ] || return 1
    (umask 022; set -C; printf '[zram0]\nzram-size = 0\n' > "$directory/99-opd2413-no-zram.conf") || return 1
    info 'OPD2413_NO_ZRAM_OVERRIDE_STAGED'
}
opd2413_no_zram
