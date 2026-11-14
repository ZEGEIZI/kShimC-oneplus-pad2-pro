#!/bin/sh
# Temporary initrd only. Stage the read-only observer in RAM across switch-root.
opd2413_stage_input_probe() {
    [ -r /etc/initrd-release ] || return 0
    [ "$(cat /etc/opd2413-input-probe 2>/dev/null)" = opd2413-input-observe-v1 ] || return 0
    grep -azFxq oneplus,opd2413 /sys/firmware/devicetree/base/compatible || return 1
    [ "$(tr -d '\000' < /sys/firmware/devicetree/base/chosen/armada,rootfs-profile)" = opd2413-bootc-rootfs-v1 ] || return 1
    [ "$(uname -r)" = 7.2.6-opd2413-full-system03 ] || return 1
    [ "$(stat -f -c %T /run)" = tmpfs ] || return 1
    local ram=/run/opd2413-input-probe
    [ ! -e "$ram" ] || return 1
    mkdir -m 0700 "$ram" || return 1
    cp -p /usr/libexec/armada/opd2413-rootfs-log "$ram/logger" || return 1
    [ "$(stat -c %s "$ram/logger")" = 781576 ] || return 1
    mkdir -p /run/systemd/system/opd2413-rootfs-log.service.d || return 1
    cat > /run/systemd/system/opd2413-rootfs-log.service.d/90-input-probe.conf <<'UNIT'
[Service]
ExecStart=
ExecStart=/run/opd2413-input-probe/logger
UNIT
    cp -p /usr/lib/armada/opd2413-desktop-run.sh /run/opd2413-desktop-run.sh || return 1
    cp -p /etc/opd2413-desktop-probe /run/opd2413-desktop-probe-marker || return 1
    mkdir -p /run/udev/rules.d || return 1
    cp -p /usr/lib/udev/rules.d/99-armada-opd2413-touch.rules /run/udev/rules.d/99-armada-opd2413-touch.rules || return 1
    [ ! -e /run/opd2413-panel-patch ] || return 1
    mkdir -m 0700 /run/opd2413-panel-patch || return 1
    cp -p /usr/lib/armada/opd2413-panel-compat/Panel.qml /run/opd2413-panel-patch/Panel.qml || return 1
    cp -p /usr/lib/armada/opd2413-panel-compat/apply-panel.sh /run/opd2413-panel-patch/apply-panel.sh || return 1
    mkdir -p /run/systemd/system/sysinit.target.wants || return 1
    cp -p /usr/lib/armada/opd2413-panel-compat/opd2413-panel-compat.service /run/systemd/system/opd2413-panel-compat.service || return 1
    ln -s ../opd2413-panel-compat.service /run/systemd/system/sysinit.target.wants/opd2413-panel-compat.service || return 1
    mkdir -p /run/opd2413-direct-mobile /run/systemd/system/sddm.service.d || return 1
    cp -p /usr/lib/armada/opd2413-panel-compat/sddm.conf /run/opd2413-direct-mobile/sddm.conf || return 1
    cp -p /usr/lib/armada/opd2413-panel-compat/sddm-runtime.conf /run/systemd/system/sddm.service.d/90-opd2413-direct-mobile.conf || return 1
    info 'OPD2413_PANEL_COMPAT_STAGED_IN_RAM'
    [ ! -e /run/opd2413-touch-recovery ] || return 1
    mkdir -m 0755 /run/opd2413-touch-recovery || return 1
    cp -p /usr/lib/armada/opd2413-panel-compat/recover-touch.sh /run/opd2413-touch-recovery/recover-touch.sh || return 1
    cp -p /usr/lib/armada/opd2413-panel-compat/opd2413-touch-recovery.service /run/systemd/system/opd2413-touch-recovery.service || return 1
    ln -s ../opd2413-touch-recovery.service /run/systemd/system/sysinit.target.wants/opd2413-touch-recovery.service || return 1
    cp -p /usr/lib/armada/opd2413-panel-compat/panel.so.gz /run/opd2413-panel-patch/panel.so.gz || return 1
    cp -p /usr/lib/armada/opd2413-panel-compat/taskpanel.so.gz /run/opd2413-panel-patch/taskpanel.so.gz || return 1
    cp -p /usr/lib/armada/opd2413-panel-compat/plugins.manifest /run/opd2413-panel-patch/plugins.manifest || return 1
    info 'OPD2413_INPUT_PROBE_STAGED_IN_RAM'
}
opd2413_stage_input_probe
