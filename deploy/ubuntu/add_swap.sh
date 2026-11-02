#!/usr/bin/env bash
# Add a dedicated 2 GiB swap file without replacing any existing swap.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run with sudo bash deploy/ubuntu/add_swap.sh'; exit 1
fi
swap_path=/centralcrm.swap
if [ -e "$swap_path" ] || [ -L "$swap_path" ] || grep -qF "$swap_path" /etc/fstab; then
  echo 'CRM swap file or fstab entry already exists. Inspect swapon --show; nothing was changed.'
  exit 1
fi
case "$(findmnt -n -o FSTYPE -T /)" in
  ext4|xfs) ;;
  *) echo 'This helper supports ext4 or XFS only; no changes were made.'; exit 1 ;;
esac
available=$(df --output=avail -B1 / | tail -n 1 | tr -d ' ')
if [ "$available" -lt 4294967296 ]; then
  echo 'At least 4 GiB free disk space is required before creating this 2 GiB file.'
  exit 1
fi
umask 077
dd if=/dev/zero of="$swap_path" bs=1M count=2048 conv=excl status=progress
chmod 600 "$swap_path"
mkswap "$swap_path"
swapon "$swap_path"
# Append only after activation succeeds. Existing fstab lines remain intact.
printf '\n%s none swap sw 0 0\n' "$swap_path" >> /etc/fstab
swapon --show
free -h
