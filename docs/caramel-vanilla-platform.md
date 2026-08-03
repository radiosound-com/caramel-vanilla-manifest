# Caramel Vanilla platform plan

Copyright 2026 Radio Sound, Inc. Licensed under the Apache License, Version 2.0.

This document records the next platform pieces for Caramel Vanilla and the
small, non-HA services that can run on Radio Sound's three-node Kubernetes
cluster. Raspberry Vanilla and other upstream projects retain their original
copyrights and licenses.

## Public baseline and Salted boundary

Public Caramel Vanilla is the source of truth for the Android 16 checkout:
GNSS, the general Raspberry Pi device integration, templates host, OsmAnd,
store/catalog tooling, package-install UX, and OTA/security plumbing belong in
the public GitHub repositories whenever their licenses permit it.

Salted Caramel Vanilla is a thin product overlay. Its only product-specific
delta should be Radio Sound's CAN configuration and AD242x A2B amplifier path:
the CAN profile/configuration, A2B initialization/controller code, required I2C
support, related audio routing, and the minimum device-tree/boot properties
needed to operate that amplifier. Display density/mode, generic adb settings,
GNSS, maps, templates, microG, Aurora, and the ordinary Pi device tree do not
belong in Salted.

The public manifest is therefore the base. The Salted manifest should select the
same public GitHub projects and add/replace only the CAN/A2B overlay project on
the internal GitLab remote.

## Current integration changes

The Android 16 manifest now uses one `github` remote for Raspberry Vanilla and
Radio Sound's public GitHub forks. Only Salted Caramel Vanilla keeps a separate
GitLab remote, because its device tree and Salted changes live on the internal
GitLab server.

The old `lineage-rpi/android_hardware_gps` project is retired. The Raspberry Pi
5 product consumes Mark777a's Apache-2.0 AIDL v6 USB NMEA GNSS HAL directly:

<https://github.com/mark777a/AOSP-AIDL-v6-GNSS-HAL>

The device integration installs the HAL, its VINTF fragment, USB serial
permissions, GPS feature declaration, and the narrow SELinux policy needed for
`ttyACM*`/`ttyUSB*`. The first hardware validation target is a Pi 5 with a USB
GPS dongle. Use the HAL's logs and `dumpsys location` as the acceptance test.

## Caramel Store direction

The store should be a catalog and policy layer, not a second developer upload
destination:

1. Consume the signed F-Droid repository index and retain package metadata,
   version, checksum, license, anti-feature, and source links.
2. Maintain a Radio Sound automotive compatibility flag derived from APK
   manifest inspection and a small human review. The current F-Droid index does
   not carry a reliable Android Automotive declaration, so the store must
   inspect `uses-feature`, SDK requirements, permissions, activities, and car
   service metadata in candidate APKs.
3. Link to the upstream F-Droid artifact where possible. Mirror an APK only
   when we have a clear redistribution/license basis and a reproducible checksum
   record.
4. Keep Aurora Store as an optional second source. It is an open-source
   frontend for Google Play, but the Play-delivered APK remains Google's or the
   developer's artifact and has its own terms, signature, and compatibility
   constraints.

### Sensible F-Droid scanning budget

On 2026-08-03, one download of the official `index-v2.json` was about 54.5 MiB,
covering 4,122 packages. The latest APK for every package represented roughly
67.8 GiB in aggregate. A broad media/navigation/browser/connectivity category
shortlist was still 1,453 packages and about 28.2 GiB, so downloading the whole
shortlist is neither necessary nor polite.

The scanner should therefore:

- fetch the signed index once daily with `ETag`/`If-Modified-Since`, not fetch
  it once per device;
- shortlist by category, package name, declared permissions, and source
  metadata before downloading APKs;
- inspect only the newest version for a candidate and cache it by SHA-256;
- use one or two concurrent downloads, a low per-host rate limit, exponential
  backoff, and a daily byte budget;
- retain the APK only long enough to extract the manifest unless it is selected
  for the store catalog; and
- record the upstream URL and checksum so a later install can download from the
  source instead of making Radio Sound a permanent mirror.

For a first pass, a 100-candidate/day budget is approximately 1–5 GiB/day for
typical APK sizes and completes a 1,453-package category shortlist in roughly
two to four weeks. The exact cost depends on split APKs and artifact sizes; the
scanner should measure and enforce bytes rather than assume an average.

F-Droid's signed index format and custom-repository model are documented at
<https://f-droid.org/en/docs/All_our_APIs/> and
<https://f-droid.org/en/docs/Setup_an_F-Droid_App_Repo/>. A future Caramel Store
can publish a signed, filtered index of approved entries without asking app
developers to submit to another portal.

### Aurora Store provisioning

Use the official Aurora OSS release/source locations only:

- source: <https://gitlab.com/AuroraOSS/AuroraStore>
- releases: <https://gitlab.com/AuroraOSS/AuroraStore/-/releases>

The first product version should treat Aurora as an optional parked-mode app,
not as a privileged silent installer. It needs the same in-car install path as
every other third-party installer. When we package a release, retain the
upstream license/notice, record the release URL and SHA-256, and verify its
manifest before adding it to the image. Anonymous Play access is convenient but
not a substitute for an app's own licensing, Play Services, DRM, or account
requirements.

## In-car package installation

The current AVD confirms that `PackageInstaller` resolves an APK only when the
intent includes a `content://` URI and
`application/vnd.android.package-archive`. The generic
`MANAGE_UNKNOWN_APP_SOURCES` intent resolves to a framework stub in this image;
that is the source of the unusable “no provider” path.

The product fix is a Car Settings screen that:

- lists installed apps declaring `REQUEST_INSTALL_PACKAGES`;
- shows the app label, signer, requested source, and current app-op;
- lets the driver enable/disable that app's install source; and
- launches the normal `PackageInstaller` flow with a persisted `content://`
  grant.

It should write only the per-package `android:request_install_packages` app-op.
Do not grant `INSTALL_PACKAGES` to ordinary apps and do not enable the app-op
globally. `scripts/check-package-installer.sh` captures the resolver, manifest,
app-op, and log state needed to close this loop on the AVD and on a Pi image.

## microG and push

microG is a compatibility layer, not a complete replacement for every Google
service. The initial target is:

- microG Services Core/GmsCore;
- microG Companion where required by the target release;
- a controlled signature-spoofing compatibility path restricted to microG;
- UnifiedNlp only if a network/location backend is selected; and
- explicit documentation of apps that still require Play Integrity, Google
  licensing, DRM, or proprietary push endpoints.

UnifiedPush is useful for apps that implement its protocol and lets the user or
product choose a distributor such as ntfy or another self-hosted service. It
cannot transparently provide push for apps that only know Firebase Cloud
Messaging. That makes it an opt-in complement to microG, not a required base
service.

Reference points: <https://github.com/microg/GmsCore/wiki>,
<https://github.com/microg/GmsCore/wiki/Signature-Spoofing>, and
<https://unifiedpush.org/developers/intro/>.

## OTA and security updates

The current Pi image is a single-image, fixed-partition layout with no recovery,
no Android A/B slots, permissive SELinux, and an orange verified-boot state.
That is acceptable for bring-up but not for a production update story.

The staged path is:

1. Make the release build enforcing and establish signing keys, AVB metadata,
   rollback indexes, and a reproducible release manifest.
2. Move the Pi image to an A/B-capable layout. On Pi 5, use the EEPROM
   `tryboot`/`autoboot.txt` mechanism as the bootloader-side fallback while
   Android's `update_engine` handles system/vendor payloads.
3. Add an update client that polls signed metadata, downloads to the inactive
   slot, verifies the payload, reboots once, and marks the slot successful only
   after Android reaches a health checkpoint.
4. Publish security bulletin tracking and monthly image rebuilds, with urgent
   out-of-band releases for kernel, bootloader, WebView/browser, and critical
   Android CVEs.
5. Keep the signing key outside Kubernetes and outside build workers. A release
   job may produce unsigned artifacts and metadata; a controlled signing step
   must be explicit and auditable.

Android's OTA, A/B, and Virtual A/B references are:
<https://source.android.com/docs/core/ota>,
<https://source.android.com/docs/core/ota/ab>, and
<https://source.android.com/docs/core/ota/virtual_ab>. Raspberry Pi's
`tryboot`/A-B boot documentation is at
<https://www.raspberrypi.com/documentation/config_txt.html>.

## Kubernetes handoff

This is intentionally a small, non-HA deployment. The three Intel NUCs and
replicated NVMe storage are useful for recovery and capacity, but the services
below should be treated as unavailable during node maintenance or a storage
incident.

### Requested services

| Service | Initial shape | Persistent data |
| --- | --- | --- |
| Store API/catalog | 1 pod, 0.25–0.5 CPU, 256–512 MiB | PostgreSQL or SQLite backup, catalog index |
| APK manifest scanner | 1 scheduled worker, 1 CPU, 2 GiB | 20–50 GiB bounded cache |
| OTA metadata/API | 1 pod, 0.25 CPU, 256 MiB | signed release metadata |
| Artifact storage | 1 object-store instance or existing replicated volume | OTA payloads, selected APKs, checksums |
| TLS/ingress | use the existing cluster ingress if available | certificates/secrets |
| Metrics/logs | use existing cluster facilities | ordinary retention only |

The scanner and build jobs must not run on the Kubernetes NUCs unless there is
no alternative; use littleboy or `.153` for Android and APK builds. The cluster
should only catalog, scan on a schedule, serve metadata, and host selected
artifacts.

### Storage and safety requirements

- one HTTPS hostname for the catalog and one for OTA artifacts, or a single
  ingress with separate paths;
- a persistent volume backed by the existing replicated NVMe storage;
- quotas for scanner cache and APK artifacts so a bad upstream index cannot fill
  the cluster;
- daily catalog/database backups and a documented restore test;
- no release signing keys in ConfigMaps, container images, Git, or ordinary
  Kubernetes Secrets;
- immutable release paths containing version, target, checksum, and signing
  metadata; and
- rate limits on both the scanner's upstream requests and device OTA polling.

The first useful deployment is therefore one catalog/scanner instance, one
metadata service, and one object store behind existing ingress. We do not need
a multi-region service mesh, a highly available database, or a second CI system.
