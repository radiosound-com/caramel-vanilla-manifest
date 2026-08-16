#!/bin/sh
set -eu

# Android 17's car_generic_system.mk enforces partition ownership for system
# properties. The generic car AVD product still declares the VHAL connection
# timeout as a system property, so move that emulator-only setting to the
# system_ext partition. It is a system-internal property and must not be put
# in vendor build.prop, where vendor_init is not allowed to set its type.

source_root=${1:-.}
# Android 17 keeps the emulator-only property declarations in the vendor
# product fragment; the Android 16 common fragment is no longer present.
files="${source_root}/device/generic/car/emulator/car_emulator_vendor.mk"

for file in $files; do
    if grep -q '^PRODUCT_SYSTEM_EXT_PROPERTIES += cppd.connectvhal.Timeoutmillis=60000$' "$file"; then
        continue
    fi
    if grep -q '^PRODUCT_PRODUCT_PROPERTIES += cppd.connectvhal.Timeoutmillis=60000$' "$file"; then
        sed -i 's/^PRODUCT_PRODUCT_PROPERTIES += cppd\.connectvhal\.Timeoutmillis=60000$/PRODUCT_SYSTEM_EXT_PROPERTIES += cppd.connectvhal.Timeoutmillis=60000/' "$file"
        continue
    fi
    if grep -q '^PRODUCT_VENDOR_PROPERTIES += cppd.connectvhal.Timeoutmillis=60000$' "$file"; then
        sed -i 's/^PRODUCT_VENDOR_PROPERTIES += cppd\.connectvhal\.Timeoutmillis=60000$/PRODUCT_SYSTEM_EXT_PROPERTIES += cppd.connectvhal.Timeoutmillis=60000/' "$file"
        continue
    fi
    if ! grep -q '^PRODUCT_SYSTEM_PROPERTIES += cppd.connectvhal.Timeoutmillis=60000$' "$file"; then
        echo "expected VHAL timeout declaration not found in $file" >&2
        exit 1
    fi
    sed -i 's/^PRODUCT_SYSTEM_PROPERTIES += cppd\.connectvhal\.Timeoutmillis=60000$/PRODUCT_SYSTEM_EXT_PROPERTIES += cppd.connectvhal.Timeoutmillis=60000/' "$file"
done

vendor_file=${source_root}/device/generic/car/emulator/car_emulator_vendor.mk

# These are also system-internal properties. Keeping them in vendor/build.prop
# produces SELinux denials during early init, so place them beside the CPPD
# timeout in product/build.prop.
for property in \
    ro.carwatchdog.client_healthcheck.interval=20 \
    ro.carwatchdog.vhal_healthcheck.interval=10; do
    if grep -q "^PRODUCT_PRODUCT_PROPERTIES += ${property}$" "$vendor_file"; then
        continue
    fi
    sed -i "/${property}/d" "$vendor_file"
    sed -i "\$a\\PRODUCT_PRODUCT_PROPERTIES += ${property}" "$vendor_file"
done

# Generic Android 17 car images otherwise omit this file. carpowerpolicyd can
# start before the emulator VHAL is ready; without registered policies its
# first timeout takes CarService down. Reuse the AOSP sample policy, preserving
# its Apache-2.0 licensing and avoiding a new third-party dependency.
if ! grep -Fq 'sample_power_policy.xml:$(TARGET_COPY_OUT_VENDOR)/etc/automotive/power_policy.xml' "$vendor_file"; then
    sed -i '$a\# Supply the AOSP sample policy for generic car VHAL startup.' "$vendor_file"
    sed -i '$a\PRODUCT_COPY_FILES += packages/services/Car/cpp/power/product/sample_power_policy.xml:$(TARGET_COPY_OUT_VENDOR)/etc/automotive/power_policy.xml' "$vendor_file"
fi

echo "generic car AVD artifact-path and power-policy compatibility is prepared"
