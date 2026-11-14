#!/bin/sh
# RAM-only candidate: no installed module, firmware, service or disk writes.
set -eu
grep -azFxq oneplus,opd2413 /sys/firmware/devicetree/base/compatible
[ "$(tr -d '\000' < /sys/firmware/devicetree/base/chosen/armada,bluetooth-profile)" = opd2413-brahma20-uart-v1 ]
[ "$(uname -r)" = 7.2.6-opd2413-full-system03 ]
[ "$(stat -f -c %T /run)" = tmpfs ]
ram=/run/opd2413-brahma08
cd "$ram"
sha256sum -c SHA256SUMS
# An explicit firmware search directory supplements the kernel's standard
# paths. It contains only the private OPD2413 Bluetooth names, so it cannot
# shadow the already working WLAN, GPU or touch firmware.
[ -e /sys/module/firmware_class/parameters/path ]
[ -z "$(cat /sys/module/firmware_class/parameters/path)" ]
printf '%s' "$ram/firmware" > /sys/module/firmware_class/parameters/path
for driver in btqca hci_uart qcom_geni_serial; do
    # An old module loaded from the installed root must not be mistaken for
    # this candidate. Refuse it instead of unloading an in-use transport.
    [ ! -e "/sys/module/$driver" ]
    printf '<6>OPD2413_BRAHMA08_MODULE_START %s\n' "$driver" > /dev/kmsg
    modprobe -d "$ram" -S 7.2.6-opd2413-full-system03 "$driver"
    printf '<6>OPD2413_BRAHMA08_MODULE_LOADED %s\n' "$driver" > /dev/kmsg
done
printf '<6>OPD2413_BRAHMA08_MODULES_COMPLETE HCI_setup_is_asynchronous\n' > /dev/kmsg
