#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: update-rpi5-partitions.sh [--clean-userdata] IMAGE.{img,img.gz} /dev/diskN

Writes only the fixed boot, system, and vendor partitions from a matching
250-GB Caramel Vanilla image. By default userdata and metadata are preserved.
--clean-userdata formats the existing metadata and userdata partitions after
the update; it does not stream the full userdata region from the image.
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

disk_bytes=$(awk -F': ' '/Disk Size:/{print $2}' <<<"$info" | awk '{print $1}')
[[ "$disk_bytes" == "250059350016" ]] || die "target size is ${disk_bytes:-unknown}; expected 250059350016 bytes"

disk_number=${disk##/dev/disk}
raw=/dev/rdisk${disk_number}
part_boot=/dev/disk${disk_number}s1
part_system=/dev/disk${disk_number}s5
part_vendor=/dev/disk${disk_number}s6
part_metadata=/dev/disk${disk_number}s7
part_userdata=/dev/disk${disk_number}s3

partition_value() {
  local partition=$1
  local field=$2
  diskutil info "$partition" 2>/dev/null \
    | awk -F': ' -v wanted="$field" '$1 ~ wanted {print $2; exit}' \
    | awk '{print $1}'
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
expect_partition "$part_boot" 1048576 134217728
expect_partition "$part_system" 136314880 3221225472
expect_partition "$part_vendor" 3358588928 402653184
expect_partition "$part_metadata" 3762290688 16777216
expect_partition "$part_userdata" 3780116480 246279233536

echo "Target: $disk ($disk_bytes bytes; raw device $raw)"
echo "Image:  $image"
echo "Mode:   boot + system + vendor only"
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

  echo "Writing $label (${size_mib} MiB at ${offset_mib} MiB)..."
  set +e
  if [[ "$image" == *.gz ]]; then
    gzip -dc "$image" \
      | dd iflag=fullblock bs=1m skip="$offset_mib" count="$size_mib" 2>/dev/null \
      | sudo -n dd of="$raw" bs=1m seek="$offset_mib" count="$size_mib" conv=sync 2>&1
    input_status=${PIPESTATUS[1]}
    output_status=${PIPESTATUS[2]}
  else
    dd if="$image" iflag=fullblock bs=1m skip="$offset_mib" count="$size_mib" 2>/dev/null \
      | sudo -n dd of="$raw" bs=1m seek="$offset_mib" count="$size_mib" conv=sync 2>&1
    input_status=${PIPESTATUS[0]}
    output_status=${PIPESTATUS[1]}
  fi
  set -e
  [[ "$input_status" -eq 0 || "$input_status" -eq 141 ]] \
    || die "$label input stream failed with status $input_status"
  [[ "$output_status" -eq 0 ]] || die "$label write failed with status $output_status"
}

stream_partition boot 1 128
stream_partition system 130 3072
stream_partition vendor 3203 384

if ((clean_userdata)); then
  mke2fs=$(command -v mke2fs || true)
  if [[ -z "$mke2fs" && -x /Users/mac/Library/Android/sdk/platform-tools/mke2fs ]]; then
    mke2fs=/Users/mac/Library/Android/sdk/platform-tools/mke2fs
  fi
  [[ -n "$mke2fs" ]] || die "mke2fs is required for --clean-userdata"
  echo "Formatting metadata..."
  sudo -n "$mke2fs" -t ext4 -I 512 -L metadata "$part_metadata"
  echo "Formatting userdata..."
  sudo -n "$mke2fs" -t ext4 -I 512 -L userdata "$part_userdata"
fi

sync
diskutil eject "$disk" >/dev/null
echo "Done. Reassemble the Pi and boot the updated partitions."
