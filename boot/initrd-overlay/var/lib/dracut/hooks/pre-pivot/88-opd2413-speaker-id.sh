#!/bin/sh
# Preserve the reviewed module set in RAM across switch-root.
opd2413_stage_speaker_id() {
    [ -r /etc/initrd-release ] || return 0
    grep -azFxq oneplus,opd2413 /sys/firmware/devicetree/base/compatible || return 0
    [ "$(tr -d '\000' < /sys/firmware/devicetree/base/chosen/armada,speaker-id-profile)" = opd2413-aw88261-id-v1 ] || return 0
    [ "$(uname -r)" = 7.2.6-opd2413-full-system03 ] || return 1
    [ "$(stat -f -c %T /run)" = tmpfs ] || return 1
    local ram=/run/opd2413-speaker-id
    [ ! -e "$ram" ] || return 1
    mkdir -m 0700 "$ram" || return 1
    mkdir -p "$ram/lib/modules" || return 1
    cp -a /usr/lib/modules/7.2.6-opd2413-full-system03 "$ram/lib/modules/" || return 1
    cp -p /usr/lib/armada/opd2413-speaker-id/start-speaker-id.sh "$ram/start-speaker-id.sh" || return 1
    cp -p /usr/lib/armada/opd2413-speaker-id/SHA256SUMS "$ram/SHA256SUMS" || return 1
    mkdir -p /run/modprobe.d /run/systemd/system/sysinit.target.wants || return 1
    cp -p /etc/modprobe.d/99-opd2413-speaker-id.conf /run/modprobe.d/99-opd2413-speaker-id.conf || return 1
    cp -p /usr/lib/armada/opd2413-speaker-id/opd2413-speaker-id.service /run/systemd/system/opd2413-speaker-id.service || return 1
    ln -s ../opd2413-speaker-id.service /run/systemd/system/sysinit.target.wants/opd2413-speaker-id.service || return 1
    info 'OPD2413_SPEAKER_ID_STAGED_IN_RAM'
}
opd2413_stage_speaker_id
