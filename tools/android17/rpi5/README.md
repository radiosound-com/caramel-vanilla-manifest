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
- Preserve Android 16's focused/full-screen dock guard so reselecting an open
  car app does not restart its wrapper. Media-app launches remain unchanged.
- Omit two optional Cuttlefish ownership annotations referring to a team not
  defined in this source snapshot. No fake team definition is needed; runtime
  code, licenses and the display tests' existing package-level team are intact.

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

The Pi product excludes SDV/display-safety tests alongside the services omitted
by the manifest, using PRODUCT_SOURCE_ROOT_DIRS. Normal dependency checking
remains enabled. Validate preparation with `test-source-preparation.py`, then
run a complete target-files/OTA build and hardware acceptance before release.

The dock predicate has a small compiled regression test (run on Linux after
preparation, using the Android tree's Kotlin compiler):

```sh
python3 tools/android17/test-dock-guard.py \
  /path/to/android/packages/apps/Car/Launcher/docklib/src/com/android/car/docklib/DockViewController.kt \
  /path/to/android/external/kotlinc/bin/kotlinc
```
