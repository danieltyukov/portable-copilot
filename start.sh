#!/usr/bin/env bash
# Sparky launcher (Linux / macOS). One step: plug in the stick, run this.
# - redirects HOME/XDG/OLLAMA into the stick (zero footprint on the host)
# - picks the bundled portable Python + Ollama for this OS/arch
# - starts Ollama in the background (enables offline + mid-session fallback)
# - launches the Sparky TUI; stops Ollama on exit
set -euo pipefail

# Resolve the stick root = the directory this script lives in (resolve symlinks).
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"; SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
ROOT="$(cd -P "$(dirname "$SOURCE")" && pwd)"
export SPARKY_ROOT="$ROOT"
RT="$ROOT/runtime"

# ---- zero-footprint env: keep all state on the stick -----------------------
export HOME="$ROOT/data/home"
export XDG_CONFIG_HOME="$ROOT/data/config"
export XDG_DATA_HOME="$ROOT/data/share"
export XDG_CACHE_HOME="$ROOT/data/cache"
export OLLAMA_HOME="$RT/ollama"
export OLLAMA_MODELS="$RT/ollama/models"
export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
mkdir -p "$HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_CACHE_HOME" \
         "$ROOT/data/sessions" "$ROOT/context" "$OLLAMA_MODELS"

# ---- detect OS/arch --------------------------------------------------------
case "$(uname -s)" in Linux) OS=linux ;; Darwin) OS=macos ;; *) OS=unknown ;; esac
case "$(uname -m)" in x86_64|amd64) ARCH=x86_64 ;; aarch64|arm64) ARCH=aarch64 ;; *) ARCH=unknown ;; esac
KEY="$OS-$ARCH"

# ---- ensure runtime (bootstrap-download on first run, if online) -----------
PY="$RT/python/$KEY/bin/python3"
if [ ! -x "$PY" ] || [ ! -d "$RT/pylib" ] || [ -z "$(ls -A "$RT/pylib" 2>/dev/null)" ]; then
  echo "Sparky: setting up the runtime for $KEY (first run on this OS)…"
  bash "$ROOT/tools/fetch_runtime.sh" "$ROOT" --this-os
fi
[ -x "$PY" ] || { echo "Sparky: no usable Python runtime found at $PY"; exit 1; }
export PYTHONPATH="$RT/pylib"

# ---- locate the bundled ollama binary --------------------------------------
OLLAMA_BIN=""
for cand in "$RT/ollama/pkg/$KEY/bin/ollama" "$RT/ollama/pkg/$KEY/ollama" "$RT/ollama/pkg/macos-$ARCH/ollama"; do
  [ -x "$cand" ] && { OLLAMA_BIN="$cand"; break; }
done
command -v ollama >/dev/null 2>&1 && [ -z "$OLLAMA_BIN" ] && OLLAMA_BIN="$(command -v ollama)"

OLLAMA_PID=""
cleanup() { [ -n "$OLLAMA_PID" ] && kill "$OLLAMA_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

if [ -n "$OLLAMA_BIN" ]; then
  # Make the bundled libs discoverable; start serve in the background.
  export LD_LIBRARY_PATH="$(dirname "$OLLAMA_BIN")/../lib/ollama:${LD_LIBRARY_PATH:-}"
  "$OLLAMA_BIN" serve >"$ROOT/data/ollama.log" 2>&1 &
  OLLAMA_PID=$!
else
  echo "Sparky: no Ollama found — offline mode unavailable until you run setup."
fi

# ---- launch ----------------------------------------------------------------
exec "$PY" -m sparky "$@"
