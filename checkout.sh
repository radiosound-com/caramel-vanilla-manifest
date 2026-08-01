#!/usr/bin/env bash
set -euo pipefail

if ! command -v repo >/dev/null 2>&1; then
  echo "repo is required; install Google's repo tool and retry." >&2
  exit 1
fi

manifest_root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
android_root=${1:-"$manifest_root/../caramel-vanilla-android-16"}
android_root=$(mkdir -p "$android_root" && cd "$android_root" && pwd)

if [ ! -d "$android_root/.repo" ]; then
  (
    cd "$android_root"
    repo init -u https://android.googlesource.com/platform/manifest \
      -b android-16.0.0_r4 --depth=1 --quiet \
      --repo-url=https://gerrit.googlesource.com/git-repo
  )
fi

mkdir -p "$android_root/.repo/local_manifests"
cp "$manifest_root/manifests/manifest_brcm_rpi.xml" \
  "$manifest_root/manifests/remove_projects.xml" \
  "$manifest_root/manifests/gps.xml" \
  "$android_root/.repo/local_manifests/"

(cd "$android_root" && repo sync --current-branch --no-tags)

echo "Caramel Vanilla checkout ready at $android_root"
