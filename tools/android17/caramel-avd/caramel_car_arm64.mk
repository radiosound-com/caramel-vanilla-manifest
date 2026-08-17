# Copyright 2026 Radio Sound, Inc.
# Licensed under the Apache License, Version 2.0.
#
# Portable Caramel Vanilla Android 17 arm64 Automotive emulator product.
# This deliberately inherits only the generic car emulator product; it does
# not inherit Raspberry Pi board, boot, audio, display, or storage settings.

CARAMEL_VOICE_ASR_MODEL := zipformer-int8
# Keep eSpeak as the compact default. The Kokoro AVD flavor sets this before
# inheriting the product and gets the same hardware/image boundary.
CARAMEL_VOICE_TTS ?= espeak

$(call inherit-product, device/generic/car/sdk_car_arm64.mk)

PRODUCT_SOONG_NAMESPACES += \
    device/generic/car/caramel-avd \
    vendor/radiosound/voiceassistant \
    vendor/radiosound/osmand \
    vendor/radiosound/templates-host \
    vendor/radiosound/aurora-store \
    vendor/radiosound/caramelstore \
    device/brcm/rpi5

$(call inherit-product, vendor/radiosound/voiceassistant/caramel_voice.mk)
$(call inherit-product, vendor/radiosound/osmand/caramel_vanilla_osmand.mk)
$(call inherit-product, vendor/radiosound/templates-host/caramel_vanilla_templates_host.mk)

# Android 17's generic car product and CarTemplatesHost.mk both expose the
# AOSP CarAppHost.  The Caramel prebuilt above is the renderer we ship and is
# the only templates host OsmAnd can bind to; retaining both hosts makes
# CarAppActivity reject the Automotive system as ambiguous.  Android 16 does
# not include CarAppHost in its generic product, so this removal is
# intentionally Android 17-specific and must remain after the host fragment.
PRODUCT_PACKAGES := $(filter-out CarAppHost,$(PRODUCT_PACKAGES))

$(call inherit-product, vendor/radiosound/aurora-store/caramel_vanilla_aurora_store.mk)
$(call inherit-product, vendor/radiosound/caramelstore/caramel_store.mk)

PRODUCT_PACKAGES += \
    CaramelVoiceDefaults \
    CaramelCarFrameworkOverlay \
    CaramelCarServiceOverlay

PRODUCT_COPY_FILES += \
    device/generic/car/caramel-avd/permissions/default-permissions-caramel-avd.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/default-permissions/default-permissions-caramel-avd.xml \
    device/generic/car/caramel-avd/permissions/privapp-permissions-caramel-avd.xml:$(TARGET_COPY_OUT_PRODUCT)/etc/permissions/privapp-permissions-caramel-avd.xml

# Retain the source property used by the portable SDK-car emulator package.
PRODUCT_SDK_ADDON_SYS_IMG_SOURCE_PROP := \
    device/generic/car/emulator/car_source.prop_template

PRODUCT_CHARACTERISTICS := automotive,nosdcard
PRODUCT_NAME := caramel_car_arm64
PRODUCT_DEVICE := emulator_car64_arm64
PRODUCT_BRAND := Caramel
PRODUCT_MANUFACTURER := Radio Sound
PRODUCT_MODEL := Caramel Vanilla arm64 Automotive emulator
EMULATOR_VENDOR_NO_SOUND := true
