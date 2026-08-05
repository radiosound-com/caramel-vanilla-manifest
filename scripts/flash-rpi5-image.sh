#!/usr/bin/env bash
# Copyright 2026 Radio Sound, Inc.
# Licensed under the Apache License, Version 2.0.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  flash-rpi5-image.sh [--yes] IMAGE.{img,img.gz} /dev/diskN

The target must be an explicitly named external whole disk of at least 200 GB.
The script unmounts it, streams the image, and ejects it when finished.
EOF
}

assume_yes=0
if [[ "${1:-}" == "--yes" ]]; then
  assume_yes=1
  shift
fi

if [[ $# -ne 2 ]]; then
  usage >&2
  exit 2
fi

image=$1
disk=$2

if [[ ! -f "$image" ]]; then
  echo "Image does not exist: $image" >&2
  exit 1
fi

if [[ ! "$disk" =~ ^/dev/disk[0-9]+$ ]]; then
  echo "Refusing non-whole-disk target: $disk" >&2
  exit 1
fi

disk_info=$(diskutil info "$disk")
device_node=$(printf '%s\n' "$disk_info" | sed -n 's/^ *Device Node: *//p' | head -1)
device_location=$(printf '%s\n' "$disk_info" \
  | sed -n 's/^ *Device Location: *//p' \
  | head -1)
size_bytes=$(printf '%s\n' "$disk_info" \
  | sed -n 's/^ *Disk Size:.*(\([0-9][0-9,]*\) Bytes).*/\1/p' \
  | head -1 \
  | tr -d ',')

if [[ "$device_node" != "$disk" ]]; then
  echo "Refusing unexpected device node: $device_node" >&2
  exit 1
fi
if [[ "$device_location" != "External" ]]; then
  echo "Refusing non-external disk ($disk): Device Location=${device_location:-unknown}" >&2
  exit 1
fi
if [[ ! "$size_bytes" =~ ^[0-9]+$ ]] || (( size_bytes < 200000000000 )); then
  echo "Refusing target smaller than 200 GB: ${size_bytes:-unknown} bytes" >&2
  exit 1
fi

raw_disk="/dev/r${disk#/dev/}"
echo "Target: $disk ($size_bytes bytes; raw device $raw_disk)"
echo "Image:  $image"

if (( ! assume_yes )); then
  printf 'Type FLASH %s to continue: ' "$disk"
  read -r confirmation
  if [[ "$confirmation" != "FLASH $disk" ]]; then
    echo "Confirmation did not match; nothing was written." >&2
    exit 1
  fi
fi

# Authenticate once. The pipeline uses sudo -n so it cannot unexpectedly ask
# for another password halfway through a multi-gigabyte write.
sudo -v
sudo -n true
diskutil unmountDisk "$disk"

if command -v pv >/dev/null 2>&1; then
  progress=(pv -p -t -e -r -b -s "$(stat -f '%z' "$image")")
else
  progress=(cat)
fi

if [[ "$image" == *.gz ]]; then
  gzip -dc "$image" | "${progress[@]}" | sudo -n dd of="$raw_disk" bs=16m conv=sync
else
  cat "$image" | "${progress[@]}" | sudo -n dd of="$raw_disk" bs=16m conv=sync
fi

sync
diskutil eject "$disk"
echo "Flash complete and disk ejected: $disk"
