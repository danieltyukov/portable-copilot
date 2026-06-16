#!/usr/bin/env bash
# Install Sparky onto a USB stick (Linux / macOS).
#
#   setup_usb.sh [--mount <dir>] [--cross] [--no-model] [--yes]
#
#   --mount <dir>  target mountpoint (default: /media/$USER/Sparky, else
#                  /Volumes/Sparky on macOS)
#   --cross        also fetch macOS + Windows runtimes (portable across OSes;
#                  larger download). Default: current OS only.
#   --no-model     skip pulling the local Qwen model
#   --yes          don't prompt for confirmation (DESTRUCTIVE — wipes the stick)
#
# The stick should already be named "Sparky" (relabel a fresh USB with your
# OS disk utility, or `sudo fatlabel /dev/sdXN SPARKY` after unmounting).
set -euo pipefail

LOCAL_MODEL="${SPARKY_LOCAL_MODEL:-qwen2.5-coder:3b}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root

MOUNT=""; CROSS="--this-os"; PULL_MODEL=1; ASSUME_YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --mount) MOUNT="$2"; shift 2 ;;
    --cross) CROSS="--all"; shift ;;
    --no-model) PULL_MODEL=0; shift ;;
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

echo "Installing Sparky:"
echo "  source : $SRC"
echo "  target : $MOUNT   (label should be 'Sparky')"
echo "  runtime: $CROSS    model: $([ $PULL_MODEL = 1 ] && echo "$LOCAL_MODEL" || echo skip)"
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

# ---- pre-pull the local model so offline works out of the box -------------
if [ "$PULL_MODEL" = 1 ]; then
  echo "Pulling local model $LOCAL_MODEL into the stick …"
  export OLLAMA_MODELS="$MOUNT/runtime/ollama/models"
  export OLLAMA_HOST="127.0.0.1:11500"
  OS=linux; case "$(uname -s)" in Darwin) OS=macos ;; esac
  ARCH=x86_64; case "$(uname -m)" in aarch64|arm64) ARCH=aarch64 ;; esac
  # Prefer the host's executable ollama for the pull (the bundled copy on a FAT
  # stick has no exec bit). Falls back to the bundled binary if no host ollama.
  OB=""
  command -v ollama >/dev/null 2>&1 && OB="$(command -v ollama)"
  if [ -z "$OB" ]; then
    for c in "$MOUNT/runtime/ollama/pkg/$OS-$ARCH/bin/ollama" "$MOUNT/runtime/ollama/pkg/$OS-$ARCH/ollama"; do
      [ -e "$c" ] && OB="$c" && break
    done
  fi
  if [ -n "$OB" ]; then
    export LD_LIBRARY_PATH="$(dirname "$OB")/../lib/ollama:${LD_LIBRARY_PATH:-}"
    "$OB" serve >/tmp/sparky-setup-ollama.log 2>&1 &
    SPID=$!
    for _ in $(seq 1 30); do curl -sf "http://127.0.0.1:11500/api/tags" >/dev/null 2>&1 && break; sleep 1; done
    "$OB" pull "$LOCAL_MODEL"
    kill "$SPID" 2>/dev/null || true
    echo "Model pulled into $OLLAMA_MODELS"
  else
    echo "No ollama binary available to pull the model; skipping."
  fi
fi

echo
echo "Done. Launch with:  cd '$MOUNT' && ./start.sh"
