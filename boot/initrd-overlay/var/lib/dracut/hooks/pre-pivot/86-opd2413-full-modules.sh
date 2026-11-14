#!/bin/sh
# Temporary pre-pivot driver overlay. The installed package stays the source
# for its original boot assets and for verified delta dictionaries.
opd2413_stage_full_modules() {
    [ -r /etc/initrd-release ] || return 1
    grep -azFxq oneplus,opd2413 /sys/firmware/devicetree/base/compatible || return 1
    [ "$(tr -d '\000' < /sys/firmware/devicetree/base/chosen/armada,full-module-profile)" = opd2413-rfkill-complete-modules-v1 ] || return 1
    [ "$(uname -r)" = 7.2.6-opd2413-full-system03 ] || return 1
    [ "$(stat -f -c %T /run)" = tmpfs ] || return 1
    local ram=/run/opd2413-full-modules
    local target=/sysroot/usr/lib/modules/7.2.6-opd2413-full-system03
    [ ! -e "$ram" ] && [ ! -L "$ram" ] || return 1
    [ -d "$target" ] && [ ! -L "$target" ] || return 1
    mkdir -m 0755 "$ram" || return 1
    mkdir -m 0755 "$ram/original" || return 1
    mount --bind "$target" "$ram/original" || return 1
    mount -o remount,bind,ro "$ram/original" || return 1
    /usr/libexec/armada/opd2413-reconstruct-modules "$ram/original" \
        /usr/lib/armada/opd2413-full-modules/bundle "$ram/tree" > "$ram/reconstruction.log" || return 1
    grep -Fxq 'OPD2413_MODULE_DELTA_READY files=182 bytes=21686181' "$ram/reconstruction.log" || return 1
    # Preserve the installed package's boot assets through a read-only alias.
    # The complete fresh kernel/ tree and every kmod index come from the bundle.
    local entry name
    for entry in "$ram/original/"* "$ram/original/".[!.]* "$ram/original/"..?*; do
        [ -e "$entry" ] || [ -L "$entry" ] || continue
        name=${entry##*/}
        [ ! -e "$ram/tree/$name" ] && [ ! -L "$ram/tree/$name" ] || continue
        case "$name" in
            config|dtb|vmlinuz|initramfs.img|System.map|build|source|.armada-opd2413-full-system|.armada-source)
                ln -s "$ram/original/$name" "$ram/tree/$name" || return 1 ;;
            *) return 1 ;;
        esac
    done
    mount --bind "$ram/tree" "$target" || return 1
    mount -o remount,bind,ro "$target" || return 1
    cp -p /usr/lib/armada/opd2413-full-modules/SHA256SUMS "$ram/SHA256SUMS" || return 1
    cp -p /usr/lib/armada/opd2413-full-modules/verify-full-modules.sh "$ram/verify-full-modules.sh" || return 1
    mkdir -p /run/systemd/system/sysinit.target.wants || return 1
    cp -p /usr/lib/armada/opd2413-full-modules/opd2413-full-modules.service /run/systemd/system/opd2413-full-modules.service || return 1
    ln -s ../opd2413-full-modules.service /run/systemd/system/sysinit.target.wants/opd2413-full-modules.service || return 1
    /bin/sh /usr/lib/armada/opd2413-full-modules/guard-switch-root.sh || return 1
    info 'OPD2413_FULL_MODULE_TREE_STAGED_READ_ONLY'
}
opd2413_stage_full_modules
