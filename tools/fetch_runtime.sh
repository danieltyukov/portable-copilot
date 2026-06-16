#!/usr/bin/env bash
# Fetch the portable runtime onto the stick: a relocatable Python, the
# pure-Python deps (shared across OSes), and the Ollama package for an OS/arch.
#
# Usage:
#   fetch_runtime.sh <STICK_ROOT> [--this-os | --all]
#     --this-os (default): fetch only the current machine's python + ollama
#     --all              : also fetch the other OSes' binaries (for a stick you
#                          want to carry between Linux/Mac/Windows)
#
# Python deps (pylib) are pure-Python, so one copy works on every OS. Ollama
# model blobs are fetched separately by setup_usb.sh (they need `ollama serve`).
set -euo pipefail

PBS_TAG="${PBS_TAG:-20260610}"
PBS_PY="${PBS_PY:-3.12.13}"
OLLAMA_TAG="${OLLAMA_TAG:-v0.30.8}"
PY_DEPS=(rich prompt_toolkit wcwidth pygments)

ROOT="${1:?usage: fetch_runtime.sh <STICK_ROOT> [--this-os|--all]}"
MODE="${2:---this-os}"
ROOT="$(cd "$ROOT" && pwd)"
RT="$ROOT/runtime"
mkdir -p "$RT/python" "$RT/pylib" "$RT/ollama/pkg" "$RT/ollama/models"

log() { printf '\033[1;33m[runtime]\033[0m %s\n' "$*"; }

detect_os() {
  case "$(uname -s)" in
    Linux) echo linux ;; Darwin) echo macos ;;
    MINGW*|MSYS*|CYGWIN*) echo windows ;; *) echo unknown ;;
  esac
}
detect_arch() {
  case "$(uname -m)" in
    x86_64|amd64) echo x86_64 ;; aarch64|arm64) echo aarch64 ;; *) echo unknown ;;
  esac
}

py_triple() {  # os arch -> pbs triple
  case "$1-$2" in
    linux-x86_64)   echo x86_64-unknown-linux-gnu ;;
    linux-aarch64)  echo aarch64-unknown-linux-gnu ;;
    macos-x86_64)   echo x86_64-apple-darwin ;;
    macos-aarch64)  echo aarch64-apple-darwin ;;
    windows-x86_64) echo x86_64-pc-windows-msvc ;;
    *) echo "" ;;
  esac
}

ollama_asset() {  # os arch -> asset filename
  case "$1-$2" in
    linux-x86_64)   echo ollama-linux-amd64.tar.zst ;;
    linux-aarch64)  echo ollama-linux-arm64.tar.zst ;;
    macos-*)        echo ollama-darwin.tgz ;;
    windows-x86_64) echo ollama-windows-amd64.zip ;;
    *) echo "" ;;
  esac
}

fetch_python() {  # os arch
  local os="$1" arch="$2" dest="$RT/python/$1-$2"
  local triple; triple="$(py_triple "$os" "$arch")"
  [ -z "$triple" ] && { log "no python build for $os-$arch, skipping"; return 0; }
  if [ -x "$dest/bin/python3" ] || [ -f "$dest/python.exe" ]; then
    log "python $os-$arch already present"; return 0
  fi
  local asset="cpython-${PBS_PY}+${PBS_TAG}-${triple}-install_only.tar.gz"
  local url="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${asset}"
  log "downloading python $os-$arch …"
  mkdir -p "$dest"
  curl -fL --retry 3 -o "/tmp/$asset" "$url"
  tar -xzf "/tmp/$asset" -C "$dest" --strip-components=1
  rm -f "/tmp/$asset"
  log "python $os-$arch ready"
}

fetch_ollama() {  # os arch
  local os="$1" arch="$2" dest="$RT/ollama/pkg/$1-$2"
  local asset; asset="$(ollama_asset "$os" "$arch")"
  [ -z "$asset" ] && { log "no ollama build for $os-$arch, skipping"; return 0; }
  if [ -e "$dest/bin/ollama" ] || [ -e "$dest/ollama" ] || [ -e "$dest/ollama.exe" ]; then
    log "ollama $os-$arch already present"; return 0
  fi
  local url="https://github.com/ollama/ollama/releases/download/${OLLAMA_TAG}/${asset}"
  log "downloading ollama $os-$arch …"
  mkdir -p "$dest"
  curl -fL --retry 3 -o "/tmp/$asset" "$url"
  case "$asset" in
    *.tar.zst) tar --zstd -xf "/tmp/$asset" -C "$dest" ;;
    *.tgz)     tar -xzf "/tmp/$asset" -C "$dest" ;;
    *.zip)     unzip -oq "/tmp/$asset" -d "$dest" ;;
  esac
  rm -f "/tmp/$asset"
  log "ollama $os-$arch ready"
}

fetch_pylib() {
  # Use any available python to install pure-Python wheels into the shared dir.
  if [ -n "$(ls -A "$RT/pylib" 2>/dev/null)" ]; then log "pylib already present"; return 0; fi
  local py=""
  for c in "$RT"/python/*/bin/python3 python3 python; do
    if command -v "$c" >/dev/null 2>&1 || [ -x "$c" ]; then py="$c"; break; fi
  done
  [ -z "$py" ] && { log "no python found to build pylib"; return 1; }
  log "installing pure-Python deps into runtime/pylib (via $py) …"
  "$py" -m pip install --no-cache-dir --upgrade pip >/dev/null 2>&1 || true
  "$py" -m pip install --no-cache-dir --target "$RT/pylib" "${PY_DEPS[@]}"
  log "pylib ready"
}

main() {
  local os arch; os="$(detect_os)"; arch="$(detect_arch)"
  log "host: $os-$arch  mode: $MODE"
  fetch_python "$os" "$arch"
  fetch_ollama "$os" "$arch"
  fetch_pylib
  if [ "$MODE" = "--all" ]; then
    for t in linux-x86_64 linux-aarch64 macos-x86_64 macos-aarch64 windows-x86_64; do
      [ "$t" = "$os-$arch" ] && continue
      fetch_python "${t%-*}" "${t##*-}" || true
      fetch_ollama "${t%-*}" "${t##*-}" || true
    done
  fi
  log "runtime fetch complete."
}
main
