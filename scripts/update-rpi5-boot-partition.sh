#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: update-rpi5-boot-partition.sh BOOT.IMG /dev/diskN" >&2
  exit 2
}

die() {
  echo "Error: $*" >&2
  exit 1
}

[[ $# -eq 2 ]] || usage
boot_image=$1
disk=$2
[[ -f "$boot_image" ]] || die "boot image does not exist: $boot_image"
[[ "$disk" =~ ^/dev/disk[0-9]+$ ]] || die "target must be a whole disk such as /dev/disk17"

boot_size=$(stat -f '%z' "$boot_image")
[[ "$boot_size" == "134217728" ]] || die "boot image is $boot_size bytes; expected 134217728"

info=$(diskutil info "$disk" 2>/dev/null) || die "unable to inspect $disk"
grep -q "Whole: *Yes" <<<"$info" || die "refusing a partition target: $disk"
grep -q "Device Location: *External" <<<"$info" || die "refusing non-external disk: $disk"
disk_bytes=$(awk -F': ' '/Disk Size:/{print $2}' <<<"$info" | awk '{print $1}')
[[ "$disk_bytes" == "250059350016" ]] || die "target size is ${disk_bytes:-unknown}; expected 250059350016 bytes"

disk_number=${disk##/dev/disk}
partition=/dev/disk${disk_number}s1
raw_partition=/dev/rdisk${disk_number}s1
partition_info=$(diskutil info "$partition" 2>/dev/null) || die "missing boot partition: $partition"
partition_offset=$(awk -F': ' '/Partition Offset:/{print $2}' <<<"$partition_info" | awk '{print $1}')
partition_size=$(awk -F': ' '/Disk Size:/{print $2}' <<<"$partition_info" | awk '{print $1}')
[[ "$partition_offset" == "1048576" && "$partition_size" == "134217728" ]] \
  || die "boot partition geometry is offset=${partition_offset:-unknown}, size=${partition_size:-unknown}"

echo "Target: $disk ($disk_bytes bytes; boot partition $raw_partition)"
echo "Image:  $boot_image"
read -r -p "Type FLASH BOOT to continue: " confirmation
[[ "$confirmation" == "FLASH BOOT" ]] || die "confirmation did not match"

sudo -v
sudo -n true
diskutil unmountDisk force "$disk" >/dev/null
sudo -n dd if="$boot_image" of="$raw_partition" bs=1m conv=sync
sync
diskutil eject "$disk" >/dev/null
echo "Done. Reassemble/reboot the Pi."
