# Caramel Vanilla manifest

This repository bootstraps the Caramel Vanilla Raspberry Pi 5 Android Automotive
checkout. It follows Raspberry Vanilla Android 16 and pins the Caramel Vanilla
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

The checkout is created at `../caramel-vanilla-android-16` by default. Pass a
different destination as the first argument to `checkout.sh`.

## Build the Raspberry Pi 5 image

```sh
cd ../caramel-vanilla-android-16
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
also creates the portable system-image archive. The x86_64 product can be
selected instead with `lunch sdk_car_x86_64-trunk_staging-userdebug`.

The build includes the Caramel Vanilla OsmAnd Automotive prebuilt. Git LFS is
used because the APK is larger than GitHub's regular-file limit; `checkout.sh`
hydrates it after `repo sync`.

## What it includes

Caramel Vanilla is a GMS-free Android Automotive OS build for Raspberry Pi 5,
based on Raspberry Vanilla Android 16. The product includes Raspberry Pi device
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
* [Car Settings install-source integration](https://github.com/radiosound-com/android_packages_apps_Car_Settings/tree/android-16.0)
* [Caramel Vanilla templates host](https://github.com/radiosound-com/android_packages_apps_Car_TemplatesHost)
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
