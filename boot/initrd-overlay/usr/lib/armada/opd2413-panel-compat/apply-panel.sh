#!/bin/sh
# Exact known Panel.qml compatibility fix, mounted from RAM without disk writes.
set -eu
umask 077
[ "$#" -eq 0 ] || exit 2
[ "$(id -u)" = 0 ] || exit 2
[ "$(stat -f -c %T /run)" = tmpfs ] || exit 2
grep -azFxq oneplus,opd2413 /sys/firmware/devicetree/base/compatible || exit 2
[ "$(tr -d '\000' < /sys/firmware/devicetree/base/chosen/armada,rootfs-profile)" = opd2413-bootc-rootfs-v1 ] || exit 2
[ "$(uname -r)" = 7.2.6-opd2413-full-system03 ] || exit 2
[ -e /run/ostree-booted ] && [ ! -e /etc/initrd-release ] || exit 2
status=/run/opd2413-panel-patch-status
source=/run/opd2413-panel-patch/Panel.qml
target=/usr/share/plasma/shells/org.kde.plasma.mobileshell/contents/views/Panel.qml
[ ! -e "$status" ] && [ ! -L "$status" ] || exit 2
set -C
exec > "$status" 2>&1
trap 'result=$?; if [ "$result" -ne 0 ]; then printf "state=FAILED exit=%s\n" "$result"; fi' EXIT
printf 'OPD2413_PANEL_PATCH_V1\nstate=CHECKING\n'
[ -f "$source" ] && [ ! -L "$source" ] || exit 2
[ -f "$target" ] && [ ! -L "$target" ] || exit 2
printf '%s  %s\n' 637b05e7c5f983e7d259f32a1c757545f8ed83748256017df2f4eead38f7d165 "$source" | /usr/bin/sha256sum -c --status || exit 2
if printf '%s  %s\n' 637b05e7c5f983e7d259f32a1c757545f8ed83748256017df2f4eead38f7d165 "$target" | /usr/bin/sha256sum -c --status; then
    echo 'source=already-current'
else
    printf '%s  %s\n' 30c8e7f5630df1d466c9dd05019e8927b258e0767ed82f7e7bc08122fb761195 "$target" | /usr/bin/sha256sum -c --status || exit 2
    /usr/bin/mount -o bind,ro "$source" "$target"
    options=$(/usr/bin/findmnt -n --mountpoint "$target" --output VFS-OPTIONS)
    case ",$options," in *,ro,*) ;; *) exit 2 ;; esac
    printf 'source=ram-bind\nmount_options=%s\n' "$options"
fi
printf '%s  %s\n' 637b05e7c5f983e7d259f32a1c757545f8ed83748256017df2f4eead38f7d165 "$target" | /usr/bin/sha256sum -c --status || exit 2
manifest=/run/opd2413-panel-patch/plugins.manifest
if [ -e "$manifest" ]; then
    [ -f "$manifest" ] && [ ! -L "$manifest" ] || exit 2
    printf '%s  %s\n' 304b3969925926b990bfb1a3c8357020495a9c2e1f9f7bda9635cd91792f775b "$manifest" | /usr/bin/sha256sum -c --status || exit 2
    while read -r component old_hash new_hash compressed_hash expected_bytes; do
        case "$component" in panel|taskpanel) ;; *) exit 2 ;; esac
        plugin_target="/usr/lib64/qt6/plugins/plasma/applets/org.kde.plasma.mobile.$component.so"
        compressed="/run/opd2413-panel-patch/$component.so.gz"
        unpacked="/run/opd2413-panel-patch/$component.so"
        [ -f "$plugin_target" ] && [ ! -L "$plugin_target" ] || exit 2
        printf '%s  %s\n' "$compressed_hash" "$compressed" | /usr/bin/sha256sum -c --status || exit 2
        if ! printf '%s  %s\n' "$new_hash" "$plugin_target" | /usr/bin/sha256sum -c --status; then
            printf '%s  %s\n' "$old_hash" "$plugin_target" | /usr/bin/sha256sum -c --status || exit 2
            /usr/bin/gzip -dc "$compressed" > "$unpacked"
            [ "$(stat -c %s "$unpacked")" = "$expected_bytes" ] || exit 2
            chmod 0644 "$unpacked"
            printf '%s  %s\n' "$new_hash" "$unpacked" | /usr/bin/sha256sum -c --status || exit 2
            /usr/bin/mount -o bind,ro "$unpacked" "$plugin_target"
            options=$(/usr/bin/findmnt -n --mountpoint "$plugin_target" --output VFS-OPTIONS)
            case ",$options," in *,ro,*) ;; *) exit 2 ;; esac
            printf 'plugin.%s.mount_options=%s\n' "$component" "$options"
        fi
        printf '%s  %s\n' "$new_hash" "$plugin_target" | /usr/bin/sha256sum -c --status || exit 2
        printf 'plugin.%s.sha256=%s\n' "$component" "$new_hash"
    done < "$manifest"
fi
printf 'panel_sha256=637b05e7c5f983e7d259f32a1c757545f8ed83748256017df2f4eead38f7d165\nstate=APPLIED\n'
