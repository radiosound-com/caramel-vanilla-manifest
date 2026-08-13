#!/usr/bin/env bash
# Copyright 2026 Radio Sound, Inc.
# Licensed under the Apache License, Version 2.0.

set -euo pipefail

die() { echo "Error: $*" >&2; exit 1; }

[[ $# -eq 1 ]] || die "Usage: expand-rpi5-userdata.sh /dev/<whole-disk>"
disk=$1
[[ -b "$disk" ]] || die "not a block device: $disk"
[[ "$(lsblk -dn -o TYPE "$disk")" == disk ]] || die "pass the whole disk, not a partition"
command -v sgdisk >/dev/null || die "sgdisk is required"
command -v partprobe >/dev/null || die "partprobe is required"
command -v e2fsck >/dev/null || die "e2fsck is required"
command -v resize2fs >/dev/null || die "resize2fs is required"

case "$disk" in
  *nvme*|*mmcblk*) userdata="${disk}p8" ;;
  *) userdata="${disk}8" ;;
esac
[[ -b "$userdata" ]] || die "missing userdata partition: $userdata"
if findmnt -rn -S "$userdata" >/dev/null 2>&1; then
  die "userdata is mounted; boot a recovery/live environment first"
fi

start=$(sgdisk -i 8 "$disk" | sed -n 's/^First sector: *\([0-9][0-9]*\).*/\1/p')
[[ "$start" =~ ^[0-9]+$ ]] || die "could not read userdata start sector"

echo "Disk: $disk"
echo "Userdata: $userdata"
echo "New end: final sector of the disk"
read -r -p "Type EXPAND to continue: " confirmation
[[ "$confirmation" == EXPAND ]] || die "nothing changed"

sudo -v
sudo -n sgdisk -e "$disk" >/dev/null
sudo -n sgdisk -d 8 -n "8:${start}:0" -c 8:userdata -t 8:8300 "$disk" >/dev/null
sudo -n partprobe "$disk"
udevadm settle 2>/dev/null || true
sleep 2

set +e
sudo -n e2fsck -f -p "$userdata"
fsck_status=$?
set -e
(( fsck_status <= 1 )) || die "e2fsck failed with status $fsck_status"
sudo -n resize2fs "$userdata"
sync
echo "Expanded userdata to $(sudo blockdev --getsize64 "$userdata") bytes"
