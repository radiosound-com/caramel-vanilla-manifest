#!/bin/sh
set -eu

# Android 16's car_generic_system.mk enforces partition ownership for system
# properties. The generic car AVD product still declares the VHAL connection
# timeout as a system property, so move that one emulator-only setting to the
# vendor partition before building sdk_car_x86_64.

source_root=${1:-.}
files="
${source_root}/device/generic/car/common/car.mk
${source_root}/device/generic/car/emulator/car_emulator_vendor.mk
"

for file in $files; do
    if grep -q '^PRODUCT_VENDOR_PROPERTIES += cppd.connectvhal.Timeoutmillis=60000$' "$file"; then
        continue
    fi
    if ! grep -q '^PRODUCT_SYSTEM_PROPERTIES += cppd.connectvhal.Timeoutmillis=60000$' "$file"; then
        echo "expected VHAL timeout declaration not found in $file" >&2
        exit 1
    fi
    sed -i 's/^PRODUCT_SYSTEM_PROPERTIES += cppd\.connectvhal\.Timeoutmillis=60000$/PRODUCT_VENDOR_PROPERTIES += cppd.connectvhal.Timeoutmillis=60000/' "$file"
done

echo "generic car AVD artifact-path compatibility is prepared"
