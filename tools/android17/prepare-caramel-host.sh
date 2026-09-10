#!/bin/sh
# Copyright 2026 Radio Sound, Inc. SPDX-License-Identifier: Apache-2.0
set -eu
source_root=$(CDPATH= cd -- "${1:-.}" && pwd)
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
host_patch=$script_dir/caramel-avd/patches/0004-unify-pi-avd-stock-host.patch
upgrade_patch=$script_dir/caramel-avd/patches/0003-upgrade-avd-only-host-exclusion.patch

if git -C "$source_root" apply --reverse --check "$host_patch" 2>/dev/null; then
    echo 'Caramel templates-host exclusion already prepared'
elif git -C "$source_root" apply --check "$host_patch" 2>/dev/null; then
    git -C "$source_root" apply "$host_patch"
elif git -C "$source_root" apply --check "$upgrade_patch" 2>/dev/null; then
    git -C "$source_root" apply "$upgrade_patch"
else
    echo 'Unrecognized CarAppHost packaging; inspect local changes before preparing' >&2
    exit 1
fi
git -C "$source_root" apply --reverse --check "$host_patch"
