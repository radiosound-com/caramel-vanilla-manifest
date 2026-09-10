#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: update-rpi5-partitions.sh [--clean-userdata] IMAGE.{img,img.gz} /dev/diskN

Writes both A/B boot, system, and vendor partitions from a matching 250-GB
Caramel Vanilla nine-partition image. By default metadata/userdata are preserved.
--clean-userdata formats existing metadata and userdata after the update; it
does not stream the full userdata region from the image.
EOF
  exit 2
}

die() {
  echo "Error: $*" >&2
  exit 1
}

clean_userdata=0
if [[ ${1:-} == "--clean-userdata" ]]; then
  clean_userdata=1
  shift
fi

[[ $# -eq 2 ]] || usage
image=$1
disk=$2
[[ -f "$image" ]] || die "image does not exist: $image"
[[ "$disk" =~ ^/dev/disk[0-9]+$ ]] || die "target must be a whole disk such as /dev/disk17"

info=$(diskutil info "$disk" 2>/dev/null) || die "unable to inspect $disk"
grep -q "Whole: *Yes" <<<"$info" || die "refusing a partition target: $disk"
grep -q "Device Location: *External" <<<"$info" || die "refusing non-external disk: $disk"

byte_count() {
  local value=$1
  if [[ "$value" =~ \(([0-9]+)\ Bytes\) ]]; then
    printf '%s\n' "${BASH_REMATCH[1]}"
  else
    awk '{print $1}' <<<"$value"
  fi
}
disk_bytes=$(byte_count "$(awk -F': ' '/Disk Size:/{print $2}' <<<"$info")")
[[ "$disk_bytes" == "250059350016" ]] || die "target size is ${disk_bytes:-unknown}; expected 250059350016 bytes"

disk_number=${disk##/dev/disk}
raw=/dev/rdisk${disk_number}
part_boot_a=/dev/disk${disk_number}s1
part_boot_b=/dev/disk${disk_number}s2
part_system_a=/dev/disk${disk_number}s3
part_system_b=/dev/disk${disk_number}s4
part_vendor_a=/dev/disk${disk_number}s5
part_vendor_b=/dev/disk${disk_number}s6
part_misc=/dev/disk${disk_number}s7
part_metadata=/dev/disk${disk_number}s8
part_userdata=/dev/disk${disk_number}s9
raw_metadata=/dev/rdisk${disk_number}s8
raw_userdata=/dev/rdisk${disk_number}s9

partition_value() {
  local partition=$1
  local field=$2
  local value
  value=$(diskutil info "$partition" 2>/dev/null \
    | awk -F': ' -v wanted="$field" '$1 ~ wanted {print $2; exit}')
  byte_count "$value"
}

expect_partition() {
  local partition=$1
  local expected_offset=$2
  local expected_size=$3
  local offset size
  offset=$(partition_value "$partition" "Partition Offset")
  size=$(partition_value "$partition" "Disk Size")
  [[ "$offset" == "$expected_offset" && "$size" == "$expected_size" ]] \
    || die "$partition geometry is offset=${offset:-unknown}, size=${size:-unknown}; expected offset=$expected_offset size=$expected_size"
}

# The updater deliberately refuses to repartition. These are the fixed offsets
# emitted by device/brcm/rpi5/mkimg.sh for the 250-GB image. Refusing a mismatch
# prevents a stale or unrelated disk from receiving partition data at offsets
# that belong to another layout.
expect_partition "$part_boot_a" 1048576 134217728
expect_partition "$part_boot_b" 135266304 134217728
expect_partition "$part_system_a" 269484032 3221225472
expect_partition "$part_system_b" 3490709504 3221225472
expect_partition "$part_vendor_a" 6711934976 402653184
expect_partition "$part_vendor_b" 7114588160 402653184
expect_partition "$part_misc" 7517241344 16777216
expect_partition "$part_metadata" 7534018560 67108864
expect_partition "$part_userdata" 7601127424 242458205696

echo "Target: $disk ($disk_bytes bytes; raw device $raw)"
echo "Image:  $image"
echo "Mode:   boot A/B + system A/B + vendor A/B only"
if ((clean_userdata)); then
  echo "Data:   format metadata + userdata; do not stream userdata image"
else
  echo "Data:   preserve metadata + userdata"
fi

sudo -v
sudo -n true
diskutil unmountDisk force "$disk" >/dev/null

stream_partition() {
  local label=$1
  local offset_mib=$2
  local size_mib=$3
  local input_status output_status
  local -a stream_status

  echo "Writing $label (${size_mib} MiB at ${offset_mib} MiB)..."
  set +e
  if [[ "$image" == *.gz ]]; then
    gzip -dc "$image" \
      | dd iflag=fullblock bs=1m skip="$offset_mib" count="$size_mib" 2>/dev/null \
      | sudo -n dd of="$raw" iflag=fullblock bs=1m seek="$offset_mib" count="$size_mib" conv=notrunc 2>&1
    stream_status=("${PIPESTATUS[@]}")
    input_status=${stream_status[1]}
    output_status=${stream_status[2]}
    [[ ${stream_status[0]} -eq 0 || ${stream_status[0]} -eq 141 ]] || \
      die "$label decompression failed with status ${stream_status[0]}"
  else
    dd if="$image" iflag=fullblock bs=1m skip="$offset_mib" count="$size_mib" 2>/dev/null \
      | sudo -n dd of="$raw" iflag=fullblock bs=1m seek="$offset_mib" count="$size_mib" conv=notrunc 2>&1
    stream_status=("${PIPESTATUS[@]}")
    input_status=${stream_status[0]}
    output_status=${stream_status[1]}
  fi
  set -e
  [[ "$input_status" -eq 0 || "$input_status" -eq 141 ]] \
    || die "$label input stream failed with status $input_status"
  [[ "$output_status" -eq 0 ]] || die "$label write failed with status $output_status"
}

stream_partition boot_a 1 128
stream_partition boot_b 129 128
stream_partition system_a 257 3072
stream_partition system_b 3329 3072
stream_partition vendor_a 6401 384
stream_partition vendor_b 6785 384

if ((clean_userdata)); then
  mke2fs=$(command -v mke2fs || true)
  if [[ -z "$mke2fs" && -x /Users/mac/Library/Android/sdk/platform-tools/mke2fs ]]; then
    mke2fs=/Users/mac/Library/Android/sdk/platform-tools/mke2fs
  fi
  [[ -n "$mke2fs" ]] || die "mke2fs is required for --clean-userdata"
  echo "Formatting metadata..."
  sudo -n "$mke2fs" -t ext4 -I 512 -L metadata "$raw_metadata"
  echo "Formatting userdata..."
  sudo -n "$mke2fs" -t ext4 -I 512 -L userdata "$raw_userdata"
fi

sync
diskutil eject "$disk" >/dev/null
echo "Done. Reassemble the Pi and boot the updated partitions."
