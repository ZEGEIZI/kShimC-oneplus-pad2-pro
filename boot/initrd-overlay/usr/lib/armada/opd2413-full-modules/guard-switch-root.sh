#!/bin/sh
# initrd-switch-root.service ExecStartPre; a refused reconstruction cannot fall
# through to the installed old consumers with the new kernel.
set -eu
[ "$(tr -d '\000' < /sys/firmware/devicetree/base/chosen/armada,full-module-profile)" = opd2413-rfkill-complete-modules-v1 ]
grep -Fxq 'OPD2413_MODULE_DELTA_READY files=182 bytes=21686181' /run/opd2413-full-modules/reconstruction.log
grep -Eq ' /sysroot/usr/lib/modules/7\.2\.6-opd2413-full-system03 ro([, ]|$)' /proc/self/mountinfo
[ -d /sysroot/usr/lib/modules/7.2.6-opd2413-full-system03/kernel ]
[ ! -L /sysroot/usr/lib/modules/7.2.6-opd2413-full-system03/kernel ]
