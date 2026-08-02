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

The device tree and standard Raspberry Vanilla manifests remain upstream. This
manifest adds the public Lineage-RPi GPS project and uses these pinned fork
revisions:

| Project | Revision |
| --- | --- |
| `android_external_libudev-zero` | `1f150ed203f1082e99170fc4e1b6fe8aeb0b9b18` |
| `android_external_libcamera` | `99e2a7bda5bce9a13c404990390a6aff20916d5f` |
| `android_external_mesa3d-rpi` | `39dd40bfaf3f8077176dbcff9e2d51231c95603d` |

OsmAnd AAOS integration is maintained separately in
`radiosound-com/OsmAnd`, branch `caramel-vanilla-osmand-aaos`.

The Raspberry Pi 5 product removes `CarMapsPlaceholder`, installs OsmAnd as
the `APP_MAPS` provider, and exposes both the templated car UI and a separate
`OsmAnd Full UI` launcher for downloads and other parked-only tasks.

The open-source Android 16 tree contains the `CarTemplatesHost.mk` capability
declaration but not a templates renderer service. This manifest supplies the
open-source Caramel Vanilla renderer as a platform-signed product privileged
app, so a GMS-free image has a complete templates-host implementation.

## Published source repositories

* [Manifest and checkout tooling](https://github.com/radiosound-com/caramel-vanilla-manifest)
* [Raspberry Pi 5 device integration](https://github.com/radiosound-com/android_device_brcm_rpi5/tree/caramel-vanilla-aaos)
* [OsmAnd product packaging](https://github.com/radiosound-com/android_vendor_osmand)
* [Caramel Vanilla templates host](https://github.com/radiosound-com/android_packages_apps_Car_TemplatesHost)
* [OsmAnd AAOS fork](https://github.com/radiosound-com/OsmAnd/tree/caramel-vanilla-osmand-aaos)

The manifest also pins these published Radio Sound forks:

* [libcamera](https://github.com/radiosound-com/android_external_libcamera)
* [libudev-zero](https://github.com/radiosound-com/android_external_libudev-zero)
* [Mesa for Raspberry Pi](https://github.com/radiosound-com/android_external_mesa3d-rpi)
