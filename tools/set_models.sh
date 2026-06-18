#!/usr/bin/env bash
# Swap the local Qwen models on a Sparky stick — for resizing to bigger/smaller
# USB drives. Pulls the chosen models into the stick's Ollama store and writes
# the tier overrides into data/sparky.env (the app picks them up on next launch).
#
#   set_models.sh [--mount DIR] [--preset small|medium|large|xl]
#                 [--fast TAG] [--max TAG] [--rm-old] [--no-pull] [--list]
#
#   --preset    size-appropriate model pair (explicit --fast/--max override it):
#                 small  (~8 GB stick) : fast qwen3.5:0.8b · max qwen3.5:4b
#                 medium (~16 GB)      : fast qwen3.5:4b   · max qwen3.5:9b
#                 large  (~32 GB, def) : fast qwen3.5:4b   · max qwen3-coder:30b
#                 xl     (~64 GB+)     : fast qwen3.5:9b   · max qwen3.6:35b-a3b
#   --fast TAG  override the fast-tier model (any Ollama tag)
#   --max  TAG  override the max-tier model
#   --rm-old    delete weights on the stick that aren't the new fast/max
#   --no-pull   only rewrite data/sparky.env (don't download)
#   --list      list models currently on the stick and exit
set -euo pipefail

MOUNT=""; PRESET="large"; FAST=""; MAX=""; RM_OLD=0; PULL=1; LIST=0
while [ $# -gt 0 ]; do
  case "$1" in
    --mount) MOUNT="$2"; shift 2 ;;
    --preset) PRESET="$2"; shift 2 ;;
    --fast) FAST="$2"; shift 2 ;;
    --max) MAX="$2"; shift 2 ;;
    --rm-old) RM_OLD=1; shift ;;
    --no-pull) PULL=0; shift ;;
    --list) LIST=1; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done

# ---- resolve the stick mountpoint -----------------------------------------
if [ -z "$MOUNT" ]; then
  if [ -n "${SPARKY_ROOT:-}" ]; then MOUNT="$SPARKY_ROOT"
  elif [ -d "/media/$USER/Sparky" ]; then MOUNT="/media/$USER/Sparky"
  elif [ -d "/Volumes/Sparky" ]; then MOUNT="/Volumes/Sparky"
  else echo "Could not find a 'Sparky' mountpoint. Pass --mount <dir>."; exit 1; fi
fi
[ -d "$MOUNT" ] || { echo "Mountpoint $MOUNT does not exist."; exit 1; }

# ---- preset -> model pair (explicit flags win) ----------------------------
case "$PRESET" in
  small)  P_FAST="qwen3.5:0.8b"; P_MAX="qwen3.5:4b" ;;
  medium) P_FAST="qwen3.5:4b";   P_MAX="qwen3.5:9b" ;;
  large)  P_FAST="qwen3.5:4b";   P_MAX="qwen3-coder:30b" ;;
  xl)     P_FAST="qwen3.5:9b";   P_MAX="qwen3.6:35b-a3b" ;;
  *) echo "unknown preset: $PRESET (small|medium|large|xl)"; exit 2 ;;
esac
FAST="${FAST:-$P_FAST}"; MAX="${MAX:-$P_MAX}"

export OLLAMA_MODELS="$MOUNT/runtime/ollama/models"
export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11500}"
mkdir -p "$OLLAMA_MODELS"

# ---- locate an ollama binary (host preferred; bundled is exec on exFAT) ----
OS=linux; case "$(uname -s)" in Darwin) OS=macos ;; esac
ARCH=x86_64; case "$(uname -m)" in aarch64|arm64) ARCH=aarch64 ;; esac
OB=""
command -v ollama >/dev/null 2>&1 && OB="$(command -v ollama)"
if [ -z "$OB" ]; then
  for c in "$MOUNT/runtime/ollama/pkg/$OS-$ARCH/bin/ollama" "$MOUNT/runtime/ollama/pkg/$OS-$ARCH/ollama"; do
    [ -e "$c" ] && OB="$c" && break
  done
fi
[ -n "$OB" ] || { echo "No ollama binary found (host or bundled). Run setup first."; exit 1; }
export LD_LIBRARY_PATH="$(dirname "$OB")/../lib/ollama:${LD_LIBRARY_PATH:-}"

# ---- start a temporary ollama server pointed at the stick ------------------
"$OB" serve >/tmp/sparky-setmodels-ollama.log 2>&1 & SPID=$!
cleanup() { kill "$SPID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
for _ in $(seq 1 30); do curl -sf "http://${OLLAMA_HOST#http://}/api/tags" >/dev/null 2>&1 && break; sleep 1; done

list_models() { "$OB" list 2>/dev/null | awk 'NR>1{print $1}'; }

if [ "$LIST" = 1 ]; then
  echo "Models on $MOUNT:"; list_models | sed 's/^/  /'; exit 0
fi

echo "Stick   : $MOUNT"
echo "fast    : $FAST"
echo "max     : $MAX   (default tier)"

# ---- pull the chosen models -----------------------------------------------
if [ "$PULL" = 1 ]; then
  for m in "$FAST" "$MAX"; do
    echo "Pulling $m …"
    "$OB" pull "$m"
  done
fi

# ---- optionally remove weights that aren't the new pair -------------------
if [ "$RM_OLD" = 1 ]; then
  for m in $(list_models); do
    if [ "$m" != "$FAST" ] && [ "$m" != "$MAX" ]; then
      echo "Removing old model $m …"; "$OB" rm "$m" || true
    fi
  done
fi

# ---- write the tier overrides into data/sparky.env ------------------------
ENV_FILE="$MOUNT/data/sparky.env"
mkdir -p "$MOUNT/data"
TMP="$(mktemp)"
[ -f "$ENV_FILE" ] && grep -v -E '^(SPARKY_FAST_MODEL|SPARKY_MAX_MODEL)=' "$ENV_FILE" > "$TMP" || true
{
  [ -s "$TMP" ] || echo "# Sparky settings — fully local, no API keys needed."
  cat "$TMP" 2>/dev/null || true
  echo "SPARKY_FAST_MODEL=$FAST"
  echo "SPARKY_MAX_MODEL=$MAX"
} > "$ENV_FILE.new"
mv "$ENV_FILE.new" "$ENV_FILE"
rm -f "$TMP"
chmod 600 "$ENV_FILE" 2>/dev/null || true

echo
echo "Done. data/sparky.env now points fast→$FAST, max→$MAX."
echo "Launch Sparky and use /model fast|max (or Ctrl-T) to switch."
