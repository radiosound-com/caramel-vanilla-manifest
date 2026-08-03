#!/usr/bin/env bash
# Copyright 2026 Radio Sound, Inc.
# Licensed under the Apache License, Version 2.0.

set -euo pipefail

serial="${ADB_SERIAL:-}"
package_name="${1:-com.android.car.media}"

adb_args=()
if [[ -n "$serial" ]]; then
  adb_args=(-s "$serial")
fi

adb_run() {
  adb "${adb_args[@]}" "$@"
}

echo "== device =="
adb_run get-state
adb_run shell getprop ro.build.version.release
adb_run shell getprop ro.product.name

echo
echo "== unknown-app-sources resolver for $package_name =="
adb_run shell cmd package query-activities --brief \
  -a android.settings.MANAGE_UNKNOWN_APP_SOURCES \
  -d "package:$package_name"

echo
echo "== APK installer resolver with a content URI =="
adb_run shell cmd package query-activities --brief \
  -a android.intent.action.INSTALL_PACKAGE \
  -d content://com.android.providers.downloads.documents/document/primary%3ADownload%2Fcandidate.apk \
  -t application/vnd.android.package-archive

echo
echo "== manifest permission and current app-op =="
adb_run shell dumpsys package "$package_name" | \
  grep -E "REQUEST_INSTALL_PACKAGES|requested permissions|install permissions" || true
adb_run shell cmd appops get "$package_name" android:request_install_packages || true

echo
echo "== recent package-manager/install logs =="
adb_run shell logcat -d -b all -v brief | \
  grep -E "PackageInstaller|PackageManager|UnknownApp|InstallStart|No provider" | tail -100 || true
