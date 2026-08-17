#!/bin/sh
set -eu

# Copyright 2026 Radio Sound, Inc.
# Licensed under the Apache License, Version 2.0.

source_root=${1:-.}
source_root=$(CDPATH= cd -- "$source_root" && pwd)
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
template_root=${script_dir}/caramel-avd
product_root=${source_root}/device/generic/car/caramel-avd
products_file=${source_root}/device/generic/car/AndroidProducts.mk

if [ ! -f "${source_root}/device/generic/car/sdk_car_arm64.mk" ]; then
    echo "Android 17 generic car source tree not found under ${source_root}" >&2
    exit 1
fi

# Apply the generic car CPPD/watchdog/power-policy compatibility fix first.
"${script_dir}/prepare-generic-car-avd.sh" "${source_root}"

# The generic car emulator HAL requests PCM_MONOTONIC and an INT_MAX stop
# threshold for capture, but the Android Emulator's VirtIO sound backend
# rejects those input parameters.
# Apply the narrow, source-preserved compatibility patch once; Pi products do
# not inherit this HAL or this patch.
caremu_audio_file=${source_root}/device/generic/car/emulator/audio/driver/audio_hw.c
caremu_audio_patch=${script_dir}/caramel-avd/patches/0001-caremu-open-virtio-input-without-monotonic.patch
if grep -Fq 'PCM_IN | PCM_MONOTONIC, &in->pcm_config' "$caremu_audio_file"; then
    git -C "$source_root" apply --check "$caremu_audio_patch"
    git -C "$source_root" apply "$caremu_audio_patch"
fi
grep -Fq 'PCM_IN, &in->pcm_config' "$caremu_audio_file"

# Android 17's generic car product includes the stock CarAppHost.  Caramel
# ships a compatible renderer prebuilt, and AndroidX CarAppActivity refuses to
# select between both hosts.  Keep the stock host for other products while
# applying the narrow exclusion only to this Caramel AVD source tree.
car_host_file=${source_root}/packages/services/Car/car_product/build/car_system.mk
car_host_patch=${script_dir}/caramel-avd/patches/0002-disable-stock-car-app-host-for-caramel.patch
if grep -Fq '    CarAppHost \' "$car_host_file"; then
    git -C "$source_root" apply --check "$car_host_patch"
    git -C "$source_root" apply "$car_host_patch"
fi
grep -Fq '$(if $(filter caramel_car_arm64 caramel_car_arm64_kokoro,$(TARGET_PRODUCT)),,CarAppHost)' "$car_host_file"

# Android's portable emulator-image makefile historically exposes emu_img_zip
# only to sdk_* and gcar_* products. Keep the product's public name and add the
# narrow Caramel prefix to that upstream packaging gate.
emu_package_mk=${source_root}/device/generic/goldfish/build/tasks.workaround/emu_img_zip.mk
if grep -Fq 'filter sdk_% gcar_%' "${emu_package_mk}"; then
    sed -i 's/filter sdk_% gcar_%/filter sdk_% gcar_% caramel_%/' "${emu_package_mk}"
fi
grep -Fq 'filter sdk_% gcar_% caramel_%' "${emu_package_mk}"

mkdir -p \
    "${product_root}/overlay/CaramelCarFrameworkOverlay/res/values" \
    "${product_root}/overlay/CaramelCarServiceOverlay/res/values" \
    "${product_root}/permissions"

cp "${template_root}/Android.bp" "${product_root}/Android.bp"
cp "${template_root}/caramel_car_arm64.mk" "${product_root}/caramel_car_arm64.mk"
cp "${template_root}/caramel_car_arm64_kokoro.mk" \
    "${product_root}/caramel_car_arm64_kokoro.mk"
cp "${template_root}/overlay/CaramelCarFrameworkOverlay/Android.bp" \
    "${product_root}/overlay/CaramelCarFrameworkOverlay/Android.bp"
cp "${template_root}/overlay/CaramelCarFrameworkOverlay/AndroidManifest.xml" \
    "${product_root}/overlay/CaramelCarFrameworkOverlay/AndroidManifest.xml"
cp "${template_root}/overlay/CaramelCarFrameworkOverlay/res/values/config.xml" \
    "${product_root}/overlay/CaramelCarFrameworkOverlay/res/values/config.xml"
cp "${template_root}/overlay/CaramelCarServiceOverlay/Android.bp" \
    "${product_root}/overlay/CaramelCarServiceOverlay/Android.bp"
cp "${template_root}/overlay/CaramelCarServiceOverlay/AndroidManifest.xml" \
    "${product_root}/overlay/CaramelCarServiceOverlay/AndroidManifest.xml"
cp "${template_root}/overlay/CaramelCarServiceOverlay/res/values/config.xml" \
    "${product_root}/overlay/CaramelCarServiceOverlay/res/values/config.xml"
cp "${template_root}/permissions/default-permissions-caramel-avd.xml" \
    "${product_root}/permissions/default-permissions-caramel-avd.xml"
cp "${template_root}/permissions/privapp-permissions-caramel-avd.xml" \
    "${product_root}/permissions/privapp-permissions-caramel-avd.xml"

if grep -Fq '$(LOCAL_DIR)/caramel_car_arm64.mk' "${products_file}"; then
    sed -i 's|$(LOCAL_DIR)/caramel_car_arm64.mk|$(LOCAL_DIR)/caramel-avd/caramel_car_arm64.mk|' "${products_file}"
fi
if ! grep -Fq '$(LOCAL_DIR)/caramel-avd/caramel_car_arm64.mk' "${products_file}"; then
    sed -i '/    \$(LOCAL_DIR)\/sdk_car_arm64.mk \\/a\    \$(LOCAL_DIR)/caramel-avd/caramel_car_arm64.mk \\' "${products_file}"
fi

if ! grep -Fq 'caramel_car_arm64-trunk_staging-userdebug' "${products_file}"; then
    sed -i '/    sdk_car_arm64-trunk_staging-userdebug \\/a\    caramel_car_arm64-trunk_staging-userdebug \\' "${products_file}"
fi

grep -Fq '$(LOCAL_DIR)/caramel-avd/caramel_car_arm64.mk' "${products_file}"
grep -Fq 'caramel_car_arm64-trunk_staging-userdebug' "${products_file}"

if ! grep -Fq '$(LOCAL_DIR)/caramel-avd/caramel_car_arm64_kokoro.mk' "${products_file}"; then
    sed -i '/caramel-avd\/caramel_car_arm64.mk \\/a\    $(LOCAL_DIR)/caramel-avd/caramel_car_arm64_kokoro.mk \\' "${products_file}"
fi
if ! grep -Fq 'caramel_car_arm64_kokoro-trunk_staging-userdebug' "${products_file}"; then
    sed -i '/caramel_car_arm64-trunk_staging-userdebug \\/a\    caramel_car_arm64_kokoro-trunk_staging-userdebug \\' "${products_file}"
fi
grep -Fq '$(LOCAL_DIR)/caramel-avd/caramel_car_arm64_kokoro.mk' "${products_file}"
grep -Fq 'caramel_car_arm64_kokoro-trunk_staging-userdebug' "${products_file}"

echo "Caramel Android 17 arm64 Automotive AVD product is prepared"
echo "  lunch caramel_car_arm64-trunk_staging-userdebug"
echo "  lunch caramel_car_arm64_kokoro-trunk_staging-userdebug"
echo "  m emu_img_zip"
