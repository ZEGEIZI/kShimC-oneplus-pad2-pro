#!/bin/sh
# Run before udev coldplug. Only the explicit OPD2413 rootfs profile opts in.
opd2413_early_modules() {
    [ -r /sys/firmware/devicetree/base/compatible ] || return 0
    grep -azFxq 'oneplus,opd2413' /sys/firmware/devicetree/base/compatible || return 0

    # A failed ordered load must not fall back to concurrent alias probing.
    # Explicit modprobe calls below do not use --use-blacklist.
    mkdir -p /run/modprobe.d || return 1
    cp /usr/lib/armada/opd2413-early-blacklist.conf /run/modprobe.d/opd2413-early.conf || return 1
    local profile marker driver result
    profile=$(tr -d '\000' < /sys/firmware/devicetree/base/chosen/armada,rootfs-profile) || return 1
    marker="/usr/lib/modules/$(uname -r)/.armada-opd2413"
    if [ "$profile" != opd2413-bootc-rootfs-v1 ] || [ ! -r "$marker" ] ||
        [ "$(cat "$marker")" != opd2413-rootfs-study-v1 ]; then
        die 'OPD2413 ordered boot requires its explicit rootfs and kernel profiles'
        return 1
    fi
    if [ "$(getarg sd_mod.opd2413_read_only)" != 0 ] ||
        [ "$(getarg qcom_rpmh_regulator.opd2413_l12b_oem_vote)" != 1 ]; then
        die 'OPD2413 rootfs requires explicit storage policy and the verified L12B request'
        return 1
    fi

    # Same board root order as the validated native-display diagnostic, then
    # storage. modprobe resolves each module's actual modules.dep dependencies.
    for driver in dispcc-sm8750 i2c-qcom-geni ktz8868-opd2413 spi-geni-qcom \
        panel-oneplus-xn242 msm phy-qcom-qmp-ufs ufs-qcom sd_mod; do
        info "OPD2413_EARLY_MODULE_START $driver"
        case "$driver" in
            msm) modprobe msm separate_gpu_kms=1; result=$? ;;
            sd_mod) modprobe sd_mod opd2413_read_only=0; result=$? ;;
            *) modprobe "$driver"; result=$? ;;
        esac
        info "OPD2413_EARLY_MODULE_END $driver result=$result"
        if [ "$result" != 0 ]; then
            die "OPD2413 ordered module load failed: $driver"
            return 1
        fi
    done
    if [ "$(cat /sys/module/sd_mod/parameters/opd2413_read_only)" != N ]; then
        die 'OPD2413 rootfs disk policy readback failed'
        return 1
    fi
    info 'OPD2413_EARLY_MODULES_COMPLETE'
}
opd2413_early_modules
