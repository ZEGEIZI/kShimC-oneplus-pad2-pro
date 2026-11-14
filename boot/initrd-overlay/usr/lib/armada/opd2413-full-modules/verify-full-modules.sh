#!/bin/sh
set -eu
[ "$(tr -d '\000' < /sys/firmware/devicetree/base/chosen/armada,full-module-profile)" = opd2413-rfkill-complete-modules-v1 ]
grep -Eq ' /usr/lib/modules/7\.2\.6-opd2413-full-system03 ro([, ]|$)' /proc/self/mountinfo
cd /usr/lib/modules/7.2.6-opd2413-full-system03
sha256sum -c /run/opd2413-full-modules/SHA256SUMS
modprobe rfkill
[ -c /dev/rfkill ]
printf '<6>OPD2413_COMPLETE_MODULE_TREE_VERIFIED rfkill_device=1\n' > /dev/kmsg
