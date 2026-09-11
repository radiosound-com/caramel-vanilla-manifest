#!/usr/bin/env bash
# Copyright 2026 Radio Sound, Inc. SPDX-License-Identifier: Apache-2.0
# Offline expansion of the current nine-partition Caramel Pi A/B layout.
set -euo pipefail
die() { echo "Error: $*" >&2; exit 1; }

assume_yes=0
if [[ "${1:-}" == --yes ]]; then assume_yes=1; shift; fi
[[ $# -eq 1 ]] || die "Usage: sudo $0 [--yes] /dev/<whole-disk>"
[[ $EUID -eq 0 ]] || die "Run with sudo; the target and all its partitions must be unmounted"
for tool in lsblk findmnt sfdisk sgdisk jq blkid e2fsck resize2fs partprobe udevadm; do
    command -v "$tool" >/dev/null || die "$tool is required"
done
disk=$(readlink -f -- "$1")
[[ "$disk" == /dev/* && -b "$disk" ]] || die "Pass an existing /dev block device"
case "$(lsblk -dn -o TYPE "$disk")" in disk|loop) ;; *) die "Pass the whole disk, not a partition" ;; esac
[[ -z "$(lsblk -nr -o MOUNTPOINTS "$disk" | tr -d '[:space:]')" ]] || die "The disk has mounted filesystems or swap; unmount them first"
layout=$(sfdisk --json "$disk")
jq -e '
  .partitiontable as $t |
  $t.label == "gpt" and $t.sectorsize == 512 and
  ($t.partitions | length) == 9 and
  ($t.partitions | map(.name)) ==
    ["boot_a","boot_b","system_a","system_b","vendor_a","vendor_b","misc","metadata","userdata"] and
  ($t.partitions[0:8] | map(.size)) ==
    [262144,262144,6291456,6291456,786432,786432,32768,131072] and
  ($t.partitions | map(.start)) ==
    [2048,264192,526336,6817792,13109248,13895680,14682112,14714880,14845952] and
  ($t.partitions[8].type | ascii_upcase) == "0FC63DAF-8483-4772-8E79-3D69D8477DE4" and
  ($t.partitions[8].attrs // "") == ""
' <<<"$layout" >/dev/null || die "Not the supported nine-partition Caramel A/B layout; nothing changed"
userdata=$(jq -r '.partitiontable.partitions[8].node' <<<"$layout")
start=$(jq -r '.partitiontable.partitions[8].start' <<<"$layout")
uuid=$(jq -r '.partitiontable.partitions[8].uuid' <<<"$layout")
[[ -b "$userdata" ]] || die "Userdata block device missing"
[[ "$(blkid -p -s TYPE -o value "$userdata")" == ext4 ]] || die "Userdata is not a directly resizable ext4 filesystem"
[[ "$(blkid -p -s LABEL -o value "$userdata")" == userdata ]] || die "Userdata filesystem label does not match"
if findmnt -rn -S "$userdata" >/dev/null; then die "Userdata is mounted"; fi

echo "Disk: $disk; userdata: $userdata (partition 9)"
echo "This grows userdata; it does not flash, format, or change boot/system/vendor/metadata."
if (( ! assume_yes )); then
    read -r -p "Type EXPAND $disk to continue: " confirmation
    [[ "$confirmation" == "EXPAND $disk" ]] || die "Nothing changed"
fi
backup=$(mktemp -d /var/tmp/caramel-userdata-expand.XXXXXX)
sgdisk --backup="$backup/partition-table.gpt" "$disk" >/dev/null
printf '%s\n' "$layout" > "$backup/partition-table.before.json"
echo "GPT recovery backup retained: $backup/partition-table.gpt"

set +e
e2fsck -f -p "$userdata"
fsck_status=$?
set -e
(( fsck_status <= 1 )) || die "Filesystem check failed ($fsck_status); partition table unchanged"
# Retain the start sector and PARTUUID. Only the last partition's end grows.
sgdisk -e -d 9 -n "9:$start:0" -c 9:userdata -t 9:8300 -u "9:$uuid" "$disk" >/dev/null
partprobe "$disk" || die "Kernel could not reread the table; stop and reattach before resizing"
udevadm settle
after=$(sfdisk --json "$disk")
jq -e --argjson before "$layout" '
  .partitiontable.partitions as $p |
  $before.partitiontable.partitions as $b |
  $p[0:8] == $b[0:8] and
  $p[8].start == $b[8].start and $p[8].uuid == $b[8].uuid and
  $p[8].size >= $b[8].size
' <<<"$after" >/dev/null || die "Unexpected partition change; stop and inspect backup $backup"
resize2fs "$userdata"
sync
sgdisk --verify "$disk"
echo "Userdata expanded successfully; original PARTUUID preserved."
lsblk -o NAME,SIZE,FSTYPE,LABEL "$disk"
