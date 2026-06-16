#!/usr/bin/env bash
# Sparky launcher (Linux / macOS). One step: plug in the stick, run it.
# - redirects HOME/XDG/OLLAMA into the stick (zero footprint on the host)
# - picks the bundled portable Python + Ollama for this OS/arch
# - launches binaries via the dynamic loader when the stick has no exec bit
#   (FAT/exFAT `showexec`/`noexec`), so it works from any USB filesystem
# - starts Ollama in the background (offline + mid-session fallback)
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
         "$ROOT/data/sessions" "$ROOT/context" "$OLLAMA_MODELS" 2>/dev/null || true

# ---- detect OS/arch --------------------------------------------------------
case "$(uname -s)" in Linux) OS=linux ;; Darwin) OS=macos ;; *) OS=unknown ;; esac
case "$(uname -m)" in x86_64|amd64) ARCH=x86_64 ;; aarch64|arm64) ARCH=aarch64 ;; *) ARCH=unknown ;; esac
KEY="$OS-$ARCH"
PYDIR="$RT/python/$KEY"

ld_for_arch() {  # dynamic loader for running non-exec binaries (Linux only)
  case "$ARCH" in
    x86_64) for p in /lib64/ld-linux-x86-64.so.2 /lib/x86_64-linux-gnu/ld-linux-x86-64.so.2; do [ -e "$p" ] && { echo "$p"; return; }; done ;;
    aarch64) for p in /lib/ld-linux-aarch64.so.1 /lib64/ld-linux-aarch64.so.1; do [ -e "$p" ] && { echo "$p"; return; }; done ;;
  esac
}

# ---- ensure runtime (bootstrap-download on first run for this OS) ----------
if { [ ! -e "$PYDIR/bin/python3.12" ] && [ ! -e "$PYDIR/python.exe" ]; } \
   || [ -z "$(ls -A "$RT/pylib" 2>/dev/null)" ]; then
  echo "Sparky: setting up the runtime for $KEY (first run on this OS)…"
  bash "$ROOT/tools/fetch_runtime.sh" "$ROOT" --this-os
fi

# Resolve the python binary.
PYBIN=""
for b in "$PYDIR/bin/python3" "$PYDIR/bin/python3.12" "$PYDIR/python.exe"; do
  [ -e "$b" ] && { PYBIN="$b"; break; }
done
[ -n "$PYBIN" ] || { echo "Sparky: no Python runtime at $PYDIR"; exit 1; }
export PYTHONPATH="$RT/pylib"
export PYTHONHOME="$PYDIR"

# ---- locate + start the bundled ollama (background) ------------------------
OLLAMA_BIN=""
for c in "$RT/ollama/pkg/$KEY/bin/ollama" "$RT/ollama/pkg/$KEY/ollama" "$RT/ollama/pkg/macos-$ARCH/ollama"; do
  [ -e "$c" ] && { OLLAMA_BIN="$c"; break; }
done
[ -z "$OLLAMA_BIN" ] && command -v ollama >/dev/null 2>&1 && OLLAMA_BIN="$(command -v ollama)"

OLLAMA_PID=""
cleanup() { [ -n "$OLLAMA_PID" ] && kill "$OLLAMA_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

if [ -n "$OLLAMA_BIN" ]; then
  export LD_LIBRARY_PATH="$(cd "$(dirname "$OLLAMA_BIN")/.." 2>/dev/null && pwd)/lib/ollama:${LD_LIBRARY_PATH:-}"
  if [ -x "$OLLAMA_BIN" ]; then
    "$OLLAMA_BIN" serve >"$ROOT/data/ollama.log" 2>&1 & OLLAMA_PID=$!
  else
    LD="$(ld_for_arch)"
    if [ -n "$LD" ]; then "$LD" "$OLLAMA_BIN" serve >"$ROOT/data/ollama.log" 2>&1 & OLLAMA_PID=$!
    else echo "Sparky: bundled Ollama not runnable here (no loader); offline mode unavailable."; fi
  fi
else
  echo "Sparky: no Ollama found — offline mode unavailable until you run setup."
fi

# ---- launch the TUI (direct if executable, else via the dynamic loader) ----
if [ -x "$PYBIN" ]; then
  exec "$PYBIN" -m sparky "$@"
else
  LD="$(ld_for_arch)"
  [ -n "$LD" ] || { echo "Sparky: cannot exec Python from this filesystem and no loader found."; exit 1; }
  exec "$LD" "$PYBIN" -m sparky "$@"
fi
