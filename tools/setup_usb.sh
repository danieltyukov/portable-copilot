#!/usr/bin/env bash
# Install Sparky (fully local) onto a USB stick (Linux / macOS).
#
#   setup_usb.sh [--mount <dir>] [--cross] [--no-model] [--yes]
#               [--preset small|medium|large|xl] [--fast TAG] [--max TAG]
#
#   --mount <dir>  target mountpoint (default: /media/$USER/Sparky, else
#                  /Volumes/Sparky on macOS)
#   --cross        also fetch macOS + Windows runtimes (portable across OSes;
#                  larger download). Default: current OS only.
#   --no-model     skip pulling the local Qwen models
#   --preset       model set sized to the stick (default large, ~32 GB):
#                    small (~8 GB) · medium (~16 GB) · large (~32 GB) · xl (~64 GB+)
#   --fast TAG     override the fast-tier model · --max TAG override the max tier
#   --yes          don't prompt for confirmation (DESTRUCTIVE — wipes the stick)
#
# The stick should already be named "Sparky" (relabel a fresh USB with your
# OS disk utility, or `sudo fatlabel /dev/sdXN SPARKY` after unmounting).
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root

MOUNT=""; CROSS="--this-os"; PULL_MODEL=1; ASSUME_YES=0
PRESET="large"; FAST=""; MAX=""
while [ $# -gt 0 ]; do
  case "$1" in
    --mount) MOUNT="$2"; shift 2 ;;
    --cross) CROSS="--all"; shift ;;
    --no-model) PULL_MODEL=0; shift ;;
    --preset) PRESET="$2"; shift 2 ;;
    --fast) FAST="$2"; shift 2 ;;
    --max) MAX="$2"; shift 2 ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done

if [ -z "$MOUNT" ]; then
  if [ -d "/media/$USER/Sparky" ]; then MOUNT="/media/$USER/Sparky"
  elif [ -d "/Volumes/Sparky" ]; then MOUNT="/Volumes/Sparky"
  else echo "Could not find a 'Sparky' mountpoint. Pass --mount <dir>."; exit 1; fi
fi
[ -d "$MOUNT" ] || { echo "Mountpoint $MOUNT does not exist."; exit 1; }

# Warn if the stick is FAT — online works, but offline needs an exec-capable fs.
FSTYPE_CHK="$(findmnt -no FSTYPE "$MOUNT" 2>/dev/null || true)"
case "$FSTYPE_CHK" in
  vfat|msdos)
    echo "NOTE: $MOUNT is $FSTYPE_CHK (FAT). Online (Claude) will work, but OFFLINE mode"
    echo "      needs exFAT on Linux. Convert later with: sudo tools/format_exfat.sh" ;;
esac

echo "Installing Sparky:"
echo "  source : $SRC"
echo "  target : $MOUNT   (label should be 'Sparky')"
echo "  runtime: $CROSS    models: $([ $PULL_MODEL = 1 ] && echo "preset=$PRESET" || echo skip)"
echo
echo "WARNING: this DELETES everything currently on $MOUNT."
if [ "$ASSUME_YES" != 1 ]; then
  read -r -p "Type 'wipe' to continue: " ans
  [ "$ans" = "wipe" ] || { echo "Aborted."; exit 1; }
fi

# ---- back up anything currently on the stick, then wipe --------------------
if [ -n "$(ls -A "$MOUNT" 2>/dev/null)" ]; then
  BK="$HOME/sparky-usb-backup-$(date +%s 2>/dev/null || echo backup)"
  echo "Backing up existing stick contents to $BK …"
  mkdir -p "$BK" && cp -a "$MOUNT"/. "$BK"/ 2>/dev/null || true
fi
echo "Wiping $MOUNT …"
find "$MOUNT" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true

# ---- copy the app ---------------------------------------------------------
echo "Copying Sparky app …"
cp -a "$SRC/sparky" "$MOUNT/"
cp -a "$SRC/tools" "$MOUNT/"
cp -a "$SRC/docs" "$MOUNT/" 2>/dev/null || true
cp -a "$SRC/sparky.cmd" "$SRC/start.sh" "$SRC/start.command" "$SRC/START.bat" "$SRC/README.md" "$MOUNT/" 2>/dev/null || true
chmod +x "$MOUNT/sparky.cmd" "$MOUNT/start.sh" "$MOUNT/start.command" "$MOUNT"/tools/*.sh 2>/dev/null || true

mkdir -p "$MOUNT/context" "$MOUNT/data/sessions"
cat > "$MOUNT/context/README.txt" <<'EOF'
Drop any files here that you want Sparky to always know about — notes, specs,
code snippets, screenshots. Everything in this folder is auto-loaded into the
copilot's context every time you launch it from this drive.
EOF

# ---- fetch the portable runtime onto the stick ----------------------------
echo "Fetching runtime onto the stick (this can take a while)…"
bash "$MOUNT/tools/fetch_runtime.sh" "$MOUNT" "$CROSS"

# ---- pre-pull the tier models so offline works out of the box -------------
# Delegated to set_models.sh, which also writes the tier overrides into
# data/sparky.env. Use the same tool later to swap models for a different stick.
if [ "$PULL_MODEL" = 1 ]; then
  SM_ARGS=(--mount "$MOUNT" --preset "$PRESET")
  [ -n "$FAST" ] && SM_ARGS+=(--fast "$FAST")
  [ -n "$MAX" ] && SM_ARGS+=(--max "$MAX")
  echo "Pulling tier models (preset=$PRESET) into the stick …"
  bash "$MOUNT/tools/set_models.sh" "${SM_ARGS[@]}"
fi

echo
echo "Done. Launch with:  cd '$MOUNT' && ./start.sh"
