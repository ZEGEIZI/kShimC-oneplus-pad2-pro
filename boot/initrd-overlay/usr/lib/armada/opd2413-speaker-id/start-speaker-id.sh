#!/bin/sh
# Read-only chip discovery. No mixer, firmware, amplifier configuration or sound.
set -eu
grep -azFxq oneplus,opd2413 /sys/firmware/devicetree/base/compatible
[ "$(tr -d '\000' < /sys/firmware/devicetree/base/chosen/armada,speaker-id-profile)" = opd2413-aw88261-id-v1 ]
[ "$(uname -r)" = 7.2.6-opd2413-full-system03 ]
[ "$(stat -f -c %T /run)" = tmpfs ]
ram=/run/opd2413-speaker-id
cd "$ram"
sha256sum -c SHA256SUMS
[ ! -e /sys/module/opd2413_speaker_id ]
printf '<6>OPD2413_SPEAKER_ID_MODULE_START\n' > /dev/kmsg
modprobe -d "$ram" -S 7.2.6-opd2413-full-system03 opd2413_speaker_id
printf '<6>OPD2413_SPEAKER_ID_MODULE_LOADED no_codec_controls=1\n' > /dev/kmsg
# Each successful probe records the exact physical controller/address/channel
# and ID in the kernel log. Summarize currently bound clients without another
# I2C transfer, retrying a failed probe, or assuming Linux adapter numbers.
count=0
for path in /sys/bus/i2c/drivers/opd2413-speaker-id/*; do
    [ -r "$path/chip_id" ] && [ -r "$path/audio_channel" ] || continue
    [ "$(cat "$path/chip_id")" = 0x2113 ] || continue
    count=$((count + 1))
done
printf '<6>OPD2413_SPEAKER_ID_DISCOVERY bound_clients=%s expected=6 physical_success_requires_six_probe_records=1\n' "$count" > /dev/kmsg
