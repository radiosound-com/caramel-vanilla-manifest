# Caramel Vanilla manifest

This repository bootstraps the Caramel Vanilla Raspberry Pi 5 Android Automotive
checkout. It follows Raspberry Vanilla Android 16 and pins the Caramel Vanilla
compatibility fixes to the radiosound-com forks.

## One-command checkout

Install Google's `repo` tool first, then run:

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
