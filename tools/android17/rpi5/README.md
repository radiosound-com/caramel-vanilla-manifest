# Android 17 Pi source preparation

Run `sh tools/android17/prepare-rpi5.sh /path/to/android` from the manifest
checkout after `repo sync`. `checkout.sh` does this for fresh checkouts.
The preparation is idempotent and fails on unrecognized conflicting edits.

These patches preserve the existing tested build-host changes without
requiring new forks of upstream AOSP projects:

- Only assign a virtual-A/B COW version to virtual-A/B products.
- Allow physical-A/B target-files to omit dynamic-partition metadata.
- Allow the boot-control HAL to mount the Pi FAT slots and update autoboot.
- Exclude stock CarAppHost for Caramel AVDs and products setting
  `CARAMEL_VANILLA_EXCLUDE_CAR_APP_HOST=true`, retaining it elsewhere.
- Preserve Android 16's background-media audio-focus default.

The Android 16 Bluetooth PAN/no-telephony workaround is intentionally not
applied: retain Android 17's existing Bluetooth/network implementation.

The device repository supplies the Gen2 NVMe default and one canonical .265
WiFi firmware set for vendor/early-ramdisk filenames. Firmware experiments
and replacement kernels are not part of this preparation. Keep the existing
release-signed OsmAnd prebuilt.

On the reference Pi, the original kernel at Gen2 passed native WPA2, DHCP,
HTTPS Internet access, reboot/reconnect, and Ethernet-to-WiFi handoff tests.
Gen3 reproduced association failures with the same firmware and credential.
The physical mechanism is not established, and results need not generalize
to every Pi/adapter. Country and WiFi credentials remain device-local.

Validation of source preparation is not a full release build. The latest
ramdisk build attempt was blocked by unrelated missing SDV telemetry Python
dependencies. Resolve those before publishing a new full image or OTA.
