#!/usr/bin/env bash
# Convert the Sparky USB to exFAT (Linux) — needed so the bundled local model
# can run OFFLINE.
#
# Why: a FAT/vfat stick mounts with `showexec`, which marks non-.exe files
# non-executable, so Ollama can't launch its `llama-server` inference binary.
# exFAT is cross-platform (Windows/macOS/Linux), supports files >4GB, and mounts
# executable on Linux — so offline inference works. Online (Claude API) works on
# FAT already; only offline needs this.
#
#   sudo tools/format_exfat.sh [--device /dev/sdX] [--mount <dir>] [--yes]
#
# DESTRUCTIVE: wipes the whole device. The script stages the current Sparky
# contents to your home dir, reformats, and restores them — but the device must
# NOT be in use (close file managers, terminals cd'd into it, and any running
# Sparky/Ollama, then unplug-replug if needed).
set -euo pipefail

MOUNT=""; DEVICE=""; ASSUME_YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --device) DEVICE="$2"; shift 2 ;;
    --mount) MOUNT="$2"; shift 2 ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo: sudo $0"; exit 1; }
USER_NAME="${SUDO_USER:-$USER}"
[ -z "$MOUNT" ] && MOUNT="/media/$USER_NAME/Sparky"
[ -d "$MOUNT" ] || { echo "Sparky not mounted at $MOUNT. Pass --mount <dir>."; exit 1; }

if [ -z "$DEVICE" ]; then
  SRC_DEV="$(findmnt -no SOURCE "$MOUNT" 2>/dev/null || true)"   # e.g. /dev/sdb1
  DEVICE="$(lsblk -no PKNAME "$SRC_DEV" 2>/dev/null | head -1)"
  [ -n "$DEVICE" ] && DEVICE="/dev/$DEVICE"
fi
[ -n "$DEVICE" ] && [ -b "$DEVICE" ] || { echo "Could not determine the device. Pass --device /dev/sdX."; exit 1; }

command -v mkfs.exfat >/dev/null 2>&1 || { echo "Installing exfatprogs…"; apt-get install -y exfatprogs >/dev/null 2>&1 || { echo "Install exfatprogs first."; exit 1; }; }

echo "Convert to exFAT:"
echo "  mount  : $MOUNT"
echo "  device : $DEVICE  ($(lsblk -no MODEL,SIZE "$DEVICE" 2>/dev/null | tr -s ' '))"
echo "WARNING: this ERASES the entire device $DEVICE."
if [ "$ASSUME_YES" != 1 ]; then
  read -r -p "Type 'exfat' to continue: " a; [ "$a" = "exfat" ] || { echo "Aborted."; exit 1; }
fi

STAGE="/home/$USER_NAME/sparky-exfat-stage"
echo "Staging current contents to $STAGE …"
rm -rf "$STAGE"; mkdir -p "$STAGE"
cp -a "$MOUNT"/. "$STAGE"/
chown -R "$USER_NAME":"$USER_NAME" "$STAGE" 2>/dev/null || true

echo "Unmounting $MOUNT …"
if ! umount "$MOUNT" 2>/dev/null; then
  echo "ERROR: $MOUNT is busy. Close anything using it (file manager, terminals"
  echo "cd'd into it, running Sparky/Ollama), or unplug-replug the stick, then re-run."
  exit 1
fi

echo "Wiping $DEVICE and creating one exFAT partition labeled Sparky …"
wipefs -a "$DEVICE"
parted -s "$DEVICE" mklabel msdos
parted -s "$DEVICE" mkpart primary 0% 100%
partprobe "$DEVICE" 2>/dev/null || true
sleep 2
PART="${DEVICE}1"; [ -b "$PART" ] || PART="$(lsblk -nro NAME "$DEVICE" | sed -n '2p' | awk '{print "/dev/"$1}')"
mkfs.exfat -L Sparky "$PART"

echo "Remounting and restoring …"
NEWMNT="/media/$USER_NAME/Sparky"
mkdir -p "$NEWMNT"
mount "$PART" "$NEWMNT" 2>/dev/null || mount -o uid="$(id -u "$USER_NAME")",gid="$(id -g "$USER_NAME")" "$PART" "$NEWMNT"
cp -a "$STAGE"/. "$NEWMNT"/
sync
echo
echo "Done — $NEWMNT is now exFAT. Offline mode will work. (Stage kept at $STAGE; delete when happy.)"
echo "Launch:  cd '$NEWMNT' && ./sparky.cmd"
