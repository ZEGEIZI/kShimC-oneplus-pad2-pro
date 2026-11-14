#!/bin/sh
# Stage firmware and the existing transport service against the complete new
# RAM tree, so its explicit modprobe sees the same modules as global kmod.
opd2413_stage_full_brahma() {
    [ -r /etc/initrd-release ] || return 1
    [ "$(tr -d '\000' < /sys/firmware/devicetree/base/chosen/armada,full-module-profile)" = opd2413-rfkill-complete-modules-v1 ] || return 1
    [ "$(tr -d '\000' < /sys/firmware/devicetree/base/chosen/armada,bluetooth-profile)" = opd2413-brahma20-uart-v1 ] || return 1
    [ "$(stat -f -c %T /run)" = tmpfs ] || return 1
    [ -d /run/opd2413-full-modules/tree/kernel ] || return 1
    local ram=/run/opd2413-brahma08
    [ ! -e "$ram" ] && [ ! -L "$ram" ] || return 1
    mkdir -m 0700 "$ram" || return 1
    mkdir -p "$ram/lib/modules" "$ram/firmware/qca/oneplus" || return 1
    ln -s /run/opd2413-full-modules/tree "$ram/lib/modules/7.2.6-opd2413-full-system03" || return 1
    cp -a /usr/lib/firmware/qca/oneplus/opd2413 "$ram/firmware/qca/oneplus/" || return 1
    cp -p /usr/lib/armada/opd2413-brahma08/start-brahma08.sh "$ram/start-brahma08.sh" || return 1
    cp -p /usr/lib/armada/opd2413-brahma08/SHA256SUMS "$ram/SHA256SUMS" || return 1
    mkdir -p /run/modprobe.d /run/systemd/system/sysinit.target.wants || return 1
    cp -p /etc/modprobe.d/99-opd2413-brahma08.conf /run/modprobe.d/99-opd2413-brahma08.conf || return 1
    cp -p /usr/lib/armada/opd2413-brahma08/opd2413-brahma08.service /run/systemd/system/opd2413-brahma08.service || return 1
    ln -s ../opd2413-brahma08.service /run/systemd/system/sysinit.target.wants/opd2413-brahma08.service || return 1
    mkdir -p /run/systemd/system/opd2413-brahma08.service.d /run/systemd/system/opd2413-speaker-id.service.d || return 1
    cat > /run/systemd/system/opd2413-brahma08.service.d/60-full-modules.conf <<'UNIT'
[Unit]
Requires=opd2413-full-modules.service
After=opd2413-full-modules.service
UNIT
    cp -p /run/systemd/system/opd2413-brahma08.service.d/60-full-modules.conf /run/systemd/system/opd2413-speaker-id.service.d/60-full-modules.conf || return 1
    info 'OPD2413_BRAHMA08_COMPLETE_MODULE_TREE_STAGED_IN_RAM'
}
opd2413_stage_full_brahma
