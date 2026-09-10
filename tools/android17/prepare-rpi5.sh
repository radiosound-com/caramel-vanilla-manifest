#!/bin/sh
# Copyright 2026 Radio Sound, Inc. SPDX-License-Identifier: Apache-2.0
set -eu
source_root=$(CDPATH= cd -- "${1:-.}" && pwd)
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
test -f "$source_root/device/brcm/rpi5/aosp_rpi5_car.mk"

sh "$script_dir/prepare-caramel-host.sh" "$source_root"
for source_patch in "$script_dir"/rpi5/patches/*.patch; do
    if git -C "$source_root" apply --reverse --check "$source_patch" 2>/dev/null; then
        echo "Already prepared: $(basename "$source_patch")"
    else
        git -C "$source_root" apply --check "$source_patch"
        git -C "$source_root" apply "$source_patch"
    fi
done
echo 'Caramel Android 17 Pi physical-A/B source is prepared'
