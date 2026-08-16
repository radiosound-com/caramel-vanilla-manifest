# Caramel Vanilla manifest

This repository bootstraps the Caramel Vanilla Raspberry Pi 5 Android Automotive
checkout. It follows Raspberry Vanilla Android 17 and pins the Caramel Vanilla
compatibility fixes to the radiosound-com forks.

Copyright 2026 Radio Sound, Inc. The original checkout tooling and manifest
additions are licensed under the [Apache License 2.0](LICENSE). Raspberry
Vanilla and other upstream projects retain their own licenses.

## Build requirements

Read the official AOSP [setup requirements](https://source.android.com/docs/setup/start/requirements),
[source download guide](https://source.android.com/docs/setup/download), and
[build guide](https://source.android.com/docs/setup/build/building) first. AOSP
currently calls for a 64-bit x86 Linux workstation, at least 64 GiB of RAM,
and at least 400 GiB of free disk space; use more for parallel builds, ccache,
multiple branches, or more than one checkout. macOS is not an officially
supported AOSP build host. Install Git, Repo, Git LFS, Python 3, OpenJDK, Make,
and the Ubuntu packages listed by AOSP. Expect a large initial download of
source, prebuilts, device projects, and LFS objects: use a fast, stable,
preferably unmetered connection and allow hours for the first sync.

On Ubuntu, the core package installation is:

```sh
sudo apt-get update && sudo apt-get install \
  git-core gnupg flex bison build-essential zip curl zlib1g-dev \
  libc6-dev-i386 x11proto-core-dev libx11-dev lib32z1-dev \
  libgl1-mesa-dev libxml2-utils xsltproc unzip fontconfig repo git-lfs python3
```

## One-command checkout

Install Google's `repo` tool and Git LFS first, then run:

```sh
git clone https://github.com/radiosound-com/caramel-vanilla-manifest.git \
  && cd caramel-vanilla-manifest \
  && ./checkout.sh
```

The checkout is created at `../caramel-vanilla-android-17` by default. Pass a
different destination as the first argument to `checkout.sh`.

## Build the Raspberry Pi 5 image

```sh
cd ../caramel-vanilla-android-17
source build/envsetup.sh
lunch aosp_rpi5_car-trunk_staging-userdebug
m bootimage systemimage vendorimage
./rpi5-mkimg.sh
```

`rpi5-mkimg.sh` keeps the historical 15.3 GB default for compatibility. To
make userdata consume the remaining space on a particular medium, pass its
logical byte capacity explicitly; for example, a 250.06 GB disk reports
`250059350016` bytes on macOS:

```sh
RPI5_IMAGE_SIZE_BYTES=250059350016 ./rpi5-mkimg.sh
```

The script creates a sparse image, retains the fixed boot/system/vendor/
metadata layout, and formats the final userdata partition across all remaining
sectors. Verify the target disk capacity before writing a raw image.

For a removable target, `scripts/flash-rpi5-image.sh` performs the safety
checks and authenticates `sudo` once before streaming a compressed image. It
requires an explicit external whole-disk path and rejects internal or small
disks:

```sh
./caramel-vanilla-manifest/scripts/flash-rpi5-image.sh \
  artifacts/rpi5-usb-nvme-waveshare-20260805-7976ebd.img.gz /dev/diskN
```

The default mode asks for a typed confirmation. `--yes` is available for a
target that has already been independently verified. No flash is performed by
the checkout or build scripts.

For iterative development, use the partition updater instead of rewriting the
full expanded userdata partition:

```sh
./caramel-vanilla-manifest/scripts/update-rpi5-partitions.sh \
  artifacts/rpi5-usb-nvme-waveshare-20260805-ed37e67.img.gz /dev/diskN
```

It requires the existing 250-GB partition geometry, writes only boot/system/
vendor, and preserves metadata/userdata by default. Add `--clean-userdata` to
format those existing metadata and userdata partitions locally with `mke2fs`;
this is still much faster than streaming the 229-GB userdata region from the
image. Use the full-image flasher when repartitioning or establishing a truly
fresh disk layout.

For a boot-only fix, such as changing the Pi EEPROM/PCIe prerequisite or boot
firmware configuration, `scripts/update-rpi5-boot-partition.sh` validates and
writes only the 128-MiB boot partition:

```sh
./caramel-vanilla-manifest/scripts/update-rpi5-boot-partition.sh \
  artifacts/rpi5-usb-nvme-waveshare-20260806-6653cdd-boot.img /dev/diskN
```

To build the Android 16 generic automotive AVD, prepare the upstream generic-car
artifact-path compatibility and select the arm64 car product:

```sh
cd ../caramel-vanilla-android-16
../caramel-vanilla-manifest/tools/android16/prepare-generic-car-avd.sh .
source build/envsetup.sh
lunch sdk_car_arm64-trunk_staging-userdebug
m emu_img_zip
```

The AVD output is `out/target/product/emulator_car64_arm64`; `emu_img_zip`
also creates the portable system-image archive. The archive contains the
QEMU-oriented system and vendor disks, so launch it by extracting the archive
and supplying its system directory and kernel explicitly. The emulator uses
`arm64` for `-avd-arch` (not the package directory name `arm64-v8a`):

The preparation helper moves the emulator's system-internal CPPD setting to
`system_ext` and the CarWatchdog settings to the product partition (vendor
init cannot set those property types), and copies AOSP's Apache-2.0 sample
power-policy XML into the vendor image. Use an Automotive AVD hardware profile
when launching; a generic phone profile can boot-loop before the automotive
services initialize.

```sh
unzip -q out/target/product/emulator_car64_arm64/sdk-repo-linux-system-images.zip \
  -d "$HOME/.cache/caramel-vanilla/android-16-arm64"
cp out/target/product/emulator_car64_arm64/userdata.img \
  "$HOME/.cache/caramel-vanilla/android-16-arm64/userdata.img"
emulator -avd caramel-vanilla-aaos \
  -sysdir "$HOME/.cache/caramel-vanilla/android-16-arm64/arm64-v8a" \
  -kernel "$HOME/.cache/caramel-vanilla/android-16-arm64/arm64-v8a/kernel-ranchu" \
  -data "$HOME/.cache/caramel-vanilla/android-16-arm64/userdata.img" \
  -avd-arch arm64 -no-snapshot
```

On Apple Silicon, verify `sys.boot_completed`, `ro.product.name`,
`dumpsys car_service`, and the absence of CarService and car-power-policy
crash loops. If a generated CarService class is present in the build tree but
missing from the APK, remove only the target's Soong intermediates and rebuild
that target before rebuilding `systemimage`, `vendorimage`, and `emu_img_zip`;
an incremental package can otherwise preserve a stale APK. The x86_64 product
can be selected instead with `lunch sdk_car_x86_64-trunk_staging-userdebug`.

### Caramel Vanilla Android 16 arm64 Automotive AVD

### Caramel Vanilla Android 17 arm64 Automotive AVD

The Android 17 checkout uses the same portable Automotive image boundary as
Android 16, with a dedicated preparation helper under `tools/android17/`.
From the Android 17 source tree, run:

```sh
../caramel-vanilla-manifest/tools/android17/prepare-caramel-car-avd.sh .
source build/envsetup.sh
lunch caramel_car_arm64-trunk_staging-userdebug
m emu_img_zip -j"$(getconf _NPROCESSORS_ONLN)"
```

The output is
`out/target/product/emulator_car64_arm64/sdk-repo-linux-system-images.zip`.
Extract it on the Mac and launch it with the same Automotive hardware profile
used for Android 16, passing the extracted `arm64-v8a` directory as `-sysdir`
and its `kernel-ranchu` as `-kernel`. Validate API 36/Baklava, the
`caramel_car_arm64` product, `sys.boot_completed`, CarService, the assistant,
templates-host, OsmAnd, and offline eSpeak TTS before comparing it with the
Android 16 v6 image.

The manifest has a dedicated AVD product for testing the same Caramel voice,
OsmAnd, templates-host, and store packaging without Raspberry Pi hardware. It
is tracked in [issue #3](https://github.com/radiosound-com/caramel-vanilla-manifest/issues/3)
and [issue #8](https://github.com/radiosound-com/caramel-vanilla-manifest/issues/8).
Prepare the product in the AOSP checkout, then build its portable system-image
archive:

```sh
../caramel-vanilla-manifest/tools/android16/prepare-caramel-car-avd.sh .
source build/envsetup.sh
lunch caramel_car_arm64-trunk_staging-userdebug
m emu_img_zip -j"$(nproc)"
```

The natural-speech Kokoro flavor uses the same Automotive hardware and image
boundary while installing the optional offline Kokoro TTS engine. Build it
with:

```sh
source build/envsetup.sh
lunch caramel_car_arm64_kokoro-trunk_staging-userdebug
m emu_img_zip -j"$(nproc)"
```

The compact `caramel_car_arm64` flavor remains the eSpeak default. Kokoro is
heavier at runtime, so validate its memory and audio behavior separately
before selecting it for a 4 GB physical Pi.

The tested image is `out/target/product/emulator_car64_arm64/sdk-repo-linux-system-images.zip`.
Extract it and pass the architecture directory (`arm64-v8a`) as `-sysdir`; the
archive parent directory is not itself an emulator system-image directory. An
Apple Silicon launch using the existing Automotive hardware profile is:

```sh
unzip -q out/target/product/emulator_car64_arm64/sdk-repo-linux-system-images.zip \
  -d "$HOME/.cache/caramel-vanilla/caramel-avd"
emulator -avd automotive \
  -sysdir "$HOME/.cache/caramel-vanilla/caramel-avd/arm64-v8a" \
  -port 5566 -no-window -no-boot-anim -gpu swiftshader_indirect \
  -no-snapshot -wipe-data -allow-host-audio
```

`-wipe-data` is the clean-userdata test; omit it for an ordinary reboot
iteration. The current product is userdebug, so `adb root` is available. The
clean-image smoke test verified Android 16/API 36, product
`caramel_car_arm64`, active AAOS driver user 10, CarService, the templates-host
permission allowlist, the Caramel assistant role, both bundled recognition
services, product-installed eSpeak, and Zipformer model startup. It also
injected an AAOS `KEYCODE_VOICE_ASSIST` event and observed the bounded no-speech
timeout followed by TTS binding. The preparation helper also applies
`tools/android16/caramel-avd/patches/0001-caremu-open-virtio-input-without-monotonic.patch`.
Android Emulator 36.6.2's VirtIO capture backend rejects the generic car HAL's
`PCM_MONOTONIC`/`INT_MAX` input parameters; the narrow patch restores
`AudioRecord` capture without changing the Pi products. With `-allow-host-audio`,
both `MIC` and `VOICE_RECOGNITION` opened successfully on the Apple Silicon AVD,
and a generated spoken `what time is it` replay was recognized by Zipformer and
answered through TTS. The assistant's cold-start session showed
`Preparing microphone…` until the model was ready, then captured the utterance;
the assistant, TTS choice, role, and CarService all survived a reboot from fresh
userdata. This validates the AVD host-audio path, not a physical USB microphone
or ALSA route on the Pi.

The product default receiver is packaged at
`/product/priv-app/CaramelVoiceDefaults` and selects
`com.reecedunn.espeak` for user 10 when no user choice exists. This makes the
TTS setting reproducible from fresh userdata and preserves it across reboot;
the setting was observed both immediately after the clean boot and after a
reboot. The current verified archive is published in the
[Caramel Android 16 arm64 Automotive AVD v6 release](https://github.com/radiosound-com/caramel-vanilla-manifest/releases/tag/avd-2026-08-08-v6)
with SHA-256
`2b2d2fe39db75111c0edc8eb49ffebb1797411d5fa5acc3eeed8c986573dc5ec`.

This v6 archive was built on the littleboy Linux AOSP host from the synced
Caramel Android 16 checkout, including voice commit `667dee0` and the split
OsmAnd/templates-host packaging fix. It was booted from clean userdata on
Apple Silicon with the Automotive profile and host-audio support, then
verified through reboot, Zipformer recognition, offline eSpeak TTS, generic
MediaStore context refresh, canonical media dispatch, and OsmAnd navigation.

The same release also contains the optional natural-speech Kokoro variant:
`sdk-repo-linux-system-images-caramel-kokoro.zip`, SHA-256
`c1a27e5a3a16b6d8ef68dda2809720b3c9be719fa2c02eea6db92a389fcef578`.
It boots as `caramel_car_arm64_kokoro`, selects
`com.k2fsa.sherpa.onnx.tts.engine` by default, and retains eSpeak as a
fallback. The Kokoro AVD variant was verified through generated speech,
successful TTS completion, and reboot persistence; its higher memory use
should still be validated on a physical 4 GB Pi before becoming the default.

A follow-up [Caramel Android 16 arm64 Automotive AVD v7 release](https://github.com/radiosound-com/caramel-vanilla-manifest/releases/tag/avd-2026-08-08-v7)
rebuilds the Kokoro image with the shared AVD templates-host product
integration. Its asset is
`sdk-repo-linux-system-images-caramel-kokoro-hostfix.zip`, SHA-256
`cec18e6b5ccf8cf2b40f8c63f13546db7a7b0033dc232846c16e4bdbc3c958d7`.
From clean userdata on Apple Silicon, the image booted as
`caramel_car_arm64_kokoro`, registered
`com.android.car.libraries.templates.host/.TemplatesHostService`, and
launched OsmAnd's Automotive map and navigation templates without the
`No handlers found` or `Please contact car services` fallback.

The build includes the Caramel Vanilla OsmAnd Automotive prebuilt. Git LFS is
used because the APK is larger than GitHub's regular-file limit; `checkout.sh`
hydrates it after `repo sync`.

The dependency-free [Caramel Store catalog API](tools/catalog-api) accepts
authenticated signed catalog imports and serves the automotive-filtered read
index. Its OKD deployment is maintained separately in the
[caramel-store-manifests](https://github.com/radiosound-com/caramel-store-manifests)
repository.

## What it includes

Caramel Vanilla is a GMS-free Android Automotive OS build for Raspberry Pi 5,
based on Raspberry Vanilla Android 17. The product includes Raspberry Pi device
integration, an AndroidX car templates host, OsmAnd Automotive maps with a
separate full UI for parked tasks, Aurora Store packaging, Car Settings
integration, and the bounded F-Droid catalog scanner in
[`tools/fdroid-scanner`](tools/fdroid-scanner).

## Published source repositories

* [Manifest and checkout tooling](https://github.com/radiosound-com/caramel-vanilla-manifest)
* [Raspberry Pi 5 device integration](https://github.com/radiosound-com/android_device_brcm_rpi5/tree/caramel-vanilla-aaos)
* [OsmAnd product packaging](https://github.com/radiosound-com/android_vendor_osmand)
* [Templates Host product packaging](https://github.com/radiosound-com/android_vendor_car_templates_host)
* [Aurora Store product packaging](https://github.com/radiosound-com/android_vendor_aurora_store)
* [Car Settings install-source integration](https://github.com/radiosound-com/android_packages_apps_Car_Settings/tree/android-17.0)
* [Caramel Vanilla templates host](https://github.com/radiosound-com/android_packages_apps_Car_TemplatesHost)
* [Caramel Vanilla offline voice assistant and TTS](https://github.com/radiosound-com/android_packages_apps_Caramel_Voice)
* [OsmAnd AAOS fork](https://github.com/radiosound-com/OsmAnd/tree/caramel-vanilla-osmand-aaos)
* [Mark777a AIDL v6 GNSS HAL](https://github.com/mark777a/AOSP-AIDL-v6-GNSS-HAL)

The manifest also pins these published Radio Sound forks:

* [libcamera](https://github.com/radiosound-com/android_external_libcamera)
* [libudev-zero](https://github.com/radiosound-com/android_external_libudev-zero)
* [Mesa for Raspberry Pi](https://github.com/radiosound-com/android_external_mesa3d-rpi)

## Credits

Caramel Vanilla builds on the Raspberry Vanilla Android Automotive work led by
[KonstaKANG](https://github.com/raspberry-vanilla). We are grateful for that
open-source foundation and upstream device support.

The Raspberry Pi product uses the Apache-2.0 AIDL v6 USB NMEA GNSS HAL from
[Mark777a](https://github.com/mark777a/AOSP-AIDL-v6-GNSS-HAL), with thanks for
the upstream project and collaboration.
