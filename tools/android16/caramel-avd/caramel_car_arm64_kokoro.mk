# Copyright 2026 Radio Sound, Inc.
# Licensed under the Apache License, Version 2.0.
#
# Portable Caramel Vanilla Android 16 arm64 Automotive emulator product with
# the natural-speech Kokoro TTS engine. Keep the compact eSpeak product as a
# separate flavor for low-memory validation.

CARAMEL_VOICE_TTS := kokoro

$(call inherit-product, device/generic/car/caramel-avd/caramel_car_arm64.mk)

PRODUCT_NAME := caramel_car_arm64_kokoro
PRODUCT_MODEL := Caramel Vanilla arm64 Automotive emulator (Kokoro TTS)
