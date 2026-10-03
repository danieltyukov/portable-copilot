#!/usr/bin/env bash
# Sparky launcher for macOS and Linux (sparky.cmd and start.command call this).
#   - keeps every file Sparky writes on the stick (HOME, caches, models)
#   - uses the stick's portable Python and Ollama for this computer, fetching
#     them the first time the stick meets this kind of computer
#   - starts programs through the dynamic loader when the stick's filesystem
#     does not allow running them directly (FAT on Linux)
#   - starts the model server unless one is already running for the stick,
#     and stops it on exit only if it started it
set -euo pipefail

SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"; SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
ROOT="$(cd -P "$(dirname "$SOURCE")" && pwd)"
export SPARKY_ROOT="$ROOT"
RT="$ROOT/runtime"

# ---- keep state on the stick -------------------------------------------------
export HOME="$ROOT/data/home"
export XDG_CONFIG_HOME="$ROOT/data/config"
export XDG_DATA_HOME="$ROOT/data/share"
export XDG_CACHE_HOME="$ROOT/data/cache"
export OLLAMA_MODELS="$RT/ollama/models"
export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11500}"
# Without this, Ollama fetches "model recommendations" from ollama.com when it
# starts and every few hours after. Downloading models is not affected.
export OLLAMA_NO_CLOUD="${OLLAMA_NO_CLOUD:-1}"
mkdir -p "$HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_CACHE_HOME" \
         "$ROOT/data/sessions" "$ROOT/context" "$OLLAMA_MODELS" 2>/dev/null || true

# ---- this computer -------------------------------------------------------------
case "$(uname -s)" in Linux) OS=linux ;; Darwin) OS=macos ;; *) OS=unknown ;; esac
case "$(uname -m)" in x86_64|amd64) ARCH=x86_64 ;; aarch64|arm64) ARCH=aarch64 ;; *) ARCH=unknown ;; esac
KEY="$OS-$ARCH"
PYDIR="$RT/python/$KEY"

loader() {  # the dynamic loader, for running binaries from a no-exec mount (Linux)
  for p in /lib64/ld-linux-x86-64.so.2 /lib/x86_64-linux-gnu/ld-linux-x86-64.so.2 \
           /lib/ld-linux-aarch64.so.1 /lib64/ld-linux-aarch64.so.1; do
    [ -e "$p" ] && { echo "$p"; return; }
  done
}

run() {  # run a binary from the stick, through the loader if it cannot be run directly
  local bin="$1"; shift
  if [ -x "$bin" ]; then "$bin" "$@"; else
    local ld; ld="$(loader)"
    [ -n "$ld" ] || { echo "Sparky: cannot run programs from this drive. Reformat it as exFAT." >&2; return 1; }
    "$ld" "$bin" "$@"
  fi
}

# ---- runtime: Python first, then the rest ----------------------------------------
if [ ! -e "$PYDIR/bin/python3.12" ]; then
  echo "Sparky: first run on $KEY, fetching its runtime (needs the internet once)."
  bash "$ROOT/tools/fetch_python.sh" "$ROOT"
fi
PYBIN="$PYDIR/bin/python3.12"
export PYTHONHOME="$PYDIR"
export PYTHONPATH="$ROOT:$RT/pylib"
export PYTHONDONTWRITEBYTECODE=1   # no __pycache__ littering the stick
export PYTHONNOUSERSITE=1          # never mix in packages from the host computer
export PYTHONSAFEPATH=1            # the folder you start in is not on the import path

OLLAMA_BIN=""
find_ollama() {
  for c in "$RT/ollama/pkg/$KEY/bin/ollama" "$RT/ollama/pkg/$KEY/ollama" "$RT/ollama/pkg/macos/ollama"; do
    [ -e "$c" ] && { OLLAMA_BIN="$c"; return; }
  done
}
find_ollama
if [ -z "$OLLAMA_BIN" ] || [ ! -d "$RT/pylib/rich" ]; then
  run "$PYBIN" -m sparky runtime --os this
  find_ollama
fi

# ---- model server ----------------------------------------------------------------
OHOST="${OLLAMA_HOST%%:*}"; OPORT="${OLLAMA_HOST##*:}"
listening() { (exec 3<>"/dev/tcp/$OHOST/$OPORT") 2>/dev/null; }

OLLAMA_PID=""
cleanup() {
  # the server runs in its own process group: stop the group, which takes
  # its model runners with it
  if [ -n "$OLLAMA_PID" ]; then
    kill -- "-$OLLAMA_PID" 2>/dev/null || kill "$OLLAMA_PID" 2>/dev/null || true
    # wait until it has let go of the port: a launcher started straight after
    # this one must not find a server that is about to disappear
    wait "$OLLAMA_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM HUP

if ! listening; then
  if [ -n "$OLLAMA_BIN" ]; then
    # ${VAR:+:$VAR}: no trailing ":" when it was empty, since an empty entry
    # would make the current folder a library search path
    OLIB="$(cd "$(dirname "$OLLAMA_BIN")/.." 2>/dev/null && pwd)/lib/ollama"
    export LD_LIBRARY_PATH="$OLIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    # job control gives the server its own process group, so a Ctrl-C meant
    # to stop a reply does not reach (and stop) the server too
    set -m
    (cd "$ROOT" && run "$OLLAMA_BIN" serve) >"$ROOT/data/ollama.log" 2>&1 &
    OLLAMA_PID=$!
    set +m
    for _ in $(seq 1 80); do
      listening && break
      kill -0 "$OLLAMA_PID" 2>/dev/null || { echo "Sparky: the model server did not start; see data/ollama.log" >&2; break; }
      sleep 0.25
    done
  else
    echo "Sparky: no model server for $KEY on this stick; run setup to add it." >&2
  fi
fi

# ---- the app ---------------------------------------------------------------------------
# not exec: the trap above must still stop the model server afterwards.
# Ctrl-C now belongs to the app (it stops a reply), so the shell only notes it.
set +e
trap : INT
run "$PYBIN" -m sparky "$@"
exit $?
