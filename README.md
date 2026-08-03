# Caramel Vanilla manifest

This repository bootstraps the Caramel Vanilla Raspberry Pi 5 Android Automotive
checkout. It follows Raspberry Vanilla Android 16 and pins the Caramel Vanilla
compatibility fixes to the radiosound-com forks.

Copyright 2026 Radio Sound, Inc. The original checkout tooling and manifest
additions are licensed under the [Apache License 2.0](LICENSE). Raspberry
Vanilla and other upstream projects retain their own licenses.

## One-command checkout

Install Google's `repo` tool and Git LFS first, then run:

```sh
git clone https://github.com/radiosound-com/caramel-vanilla-manifest.git \
  && cd caramel-vanilla-manifest \
  && ./checkout.sh
```

The checkout is created at `../caramel-vanilla-android-16` by default. Pass a
different destination as the first argument to `checkout.sh`.

## Build

```sh
cd ../caramel-vanilla-android-16
source build/envsetup.sh
lunch aosp_rpi5_car-trunk_staging-userdebug
m bootimage systemimage vendorimage -j$(getconf _NPROCESSORS_ONLN)
./rpi5-mkimg.sh
```

The current Raspberry Vanilla device tree advertises the `trunk_staging`
release configuration. The upstream README may show the older `bp4a` spelling.

The build includes the Caramel Vanilla OsmAnd Automotive prebuilt. Git LFS is
used because the APK is larger than GitHub's regular-file limit; `checkout.sh`
hydrates it after `repo sync`.

## Caramel Vanilla deltas

The device tree and standard Raspberry Vanilla manifests remain upstream where
possible. Radio Sound's public GitHub forks use Raspberry Vanilla-compatible
`android-16.0` branches; the manifest no longer has a second GitHub remote.
The Raspberry Pi 5 product consumes Mark777a's Apache-2.0 AIDL v6 USB NMEA GNSS
HAL directly from [`mark777a/AOSP-AIDL-v6-GNSS-HAL`](https://github.com/mark777a/AOSP-AIDL-v6-GNSS-HAL).
The old KonstaKANG/Lineage GPS project is retired.

The Radio Sound fork revisions are:

| Project | Revision |
| --- | --- |
| `android_external_libudev-zero` | `android-16.0` |
| `android_external_libcamera` | `android-16.0` |
| `android_external_mesa3d-rpi` | `android-16.0` |

OsmAnd AAOS integration is maintained separately in
`radiosound-com/OsmAnd`, branch `caramel-vanilla-osmand-aaos`.

The Raspberry Pi 5 product removes `CarMapsPlaceholder`, installs OsmAnd as
the `APP_MAPS` provider, and exposes both the templated car UI and a separate
`OsmAnd Full UI` launcher for downloads and other parked-only tasks.

The open-source Android 16 tree contains the `CarTemplatesHost.mk` capability
declaration but not a templates renderer service. This manifest supplies the
open-source Caramel Vanilla renderer as a platform-signed product privileged
app, so a GMS-free image has a complete templates-host implementation.

Caramel Vanilla is the public baseline. Salted Caramel Vanilla is limited to
Radio Sound's CAN/A2B amplifier overlay and does not duplicate the public device
tree or general platform work. The store, package-install, microG, and OTA plan
is in [`docs/caramel-vanilla-platform.md`](docs/caramel-vanilla-platform.md).

## Published source repositories

* [Manifest and checkout tooling](https://github.com/radiosound-com/caramel-vanilla-manifest)
* [Raspberry Pi 5 device integration](https://github.com/radiosound-com/android_device_brcm_rpi5/tree/caramel-vanilla-aaos)
* [OsmAnd product packaging](https://github.com/radiosound-com/android_vendor_osmand)
* [Caramel Vanilla templates host](https://github.com/radiosound-com/android_packages_apps_Car_TemplatesHost)
* [OsmAnd AAOS fork](https://github.com/radiosound-com/OsmAnd/tree/caramel-vanilla-osmand-aaos)
* [Mark777a AIDL v6 GNSS HAL](https://github.com/mark777a/AOSP-AIDL-v6-GNSS-HAL)

The manifest also pins these published Radio Sound forks:

* [libcamera](https://github.com/radiosound-com/android_external_libcamera)
* [libudev-zero](https://github.com/radiosound-com/android_external_libudev-zero)
* [Mesa for Raspberry Pi](https://github.com/radiosound-com/android_external_mesa3d-rpi)
