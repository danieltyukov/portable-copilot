#!/usr/bin/env bash
# Fetch the portable runtime onto the stick: a relocatable Python, the
# pure-Python deps (shared across OSes), and the Ollama package for an OS/arch.
#
#   fetch_runtime.sh <STICK_ROOT> [--this-os | --all]
#
# Notes on portable USB filesystems (FAT/exFAT):
#   * They can't store symlinks, so everything is copied with symlinks
#     dereferenced into real files.
#   * They may not carry the exec bit (FAT `showexec`), so binaries are launched
#     via the dynamic loader at runtime — see start.sh. Setup here only needs to
#     place files; pip is run through the loader too.
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

detect_os() { case "$(uname -s)" in Linux) echo linux ;; Darwin) echo macos ;; MINGW*|MSYS*|CYGWIN*) echo windows ;; *) echo unknown ;; esac; }
detect_arch() { case "$(uname -m)" in x86_64|amd64) echo x86_64 ;; aarch64|arm64) echo aarch64 ;; *) echo unknown ;; esac; }

ld_for_arch() {  # echo a dynamic loader path for the host arch (Linux)
  case "$(detect_arch)" in
    x86_64) for p in /lib64/ld-linux-x86-64.so.2 /lib/x86_64-linux-gnu/ld-linux-x86-64.so.2; do [ -e "$p" ] && { echo "$p"; return; }; done ;;
    aarch64) for p in /lib/ld-linux-aarch64.so.1 /lib64/ld-linux-aarch64.so.1; do [ -e "$p" ] && { echo "$p"; return; }; done ;;
  esac
}

py_triple() {
  case "$1-$2" in
    linux-x86_64) echo x86_64-unknown-linux-gnu ;; linux-aarch64) echo aarch64-unknown-linux-gnu ;;
    macos-x86_64) echo x86_64-apple-darwin ;; macos-aarch64) echo aarch64-apple-darwin ;;
    windows-x86_64) echo x86_64-pc-windows-msvc ;; *) echo "" ;;
  esac
}
ollama_asset() {
  case "$1-$2" in
    linux-x86_64) echo ollama-linux-amd64.tar.zst ;; linux-aarch64) echo ollama-linux-arm64.tar.zst ;;
    macos-*) echo ollama-darwin.tgz ;; windows-x86_64) echo ollama-windows-amd64.zip ;; *) echo "" ;;
  esac
}

prune_python() {  # slim the extracted tree (no GUI/tests/headers) for a leaner, faster copy
  local d="$1"
  rm -rf "$d/share" "$d/include" 2>/dev/null || true
  rm -rf "$d"/lib/python*/test "$d"/lib/python*/idlelib "$d"/lib/python*/tkinter \
         "$d"/lib/python*/turtledemo "$d"/lib/python*/lib2to3 2>/dev/null || true
  rm -rf "$d"/lib/libtcl* "$d"/lib/libtk* "$d"/lib/itcl* "$d"/lib/thread* \
         "$d"/lib/tcl* "$d"/lib/tk* 2>/dev/null || true
  # bin/python3 and bin/python are symlinks to python3.12 — drop them so we don't
  # deref-copy the 100MB binary three times. start.sh invokes python3.12 directly.
  find "$d/bin" -maxdepth 1 -type l -delete 2>/dev/null || true
}

fetch_python() {  # os arch
  local os="$1" arch="$2" dest="$RT/python/$1-$2"
  local triple; triple="$(py_triple "$os" "$arch")"
  [ -z "$triple" ] && { log "no python build for $os-$arch, skipping"; return 0; }
  if [ -e "$dest/bin/python3.12" ] || [ -e "$dest/python.exe" ]; then log "python $os-$arch present"; return 0; fi
  local asset="cpython-${PBS_PY}+${PBS_TAG}-${triple}-install_only.tar.gz"
  local url="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${asset}"
  log "downloading python $os-$arch …"
  local tmp; tmp="$(mktemp -d)"
  curl -fL --retry 3 -o "$tmp/$asset" "$url"
  tar -xzf "$tmp/$asset" -C "$tmp"          # -> $tmp/python/...  (on local fs; symlinks OK here)
  prune_python "$tmp/python"
  rm -rf "$dest"; mkdir -p "$dest"
  cp -RL "$tmp/python/." "$dest/" 2>/dev/null || cp -RL "$tmp/python/." "$dest/" || true  # dereference symlinks for FAT
  rm -rf "$tmp"
  log "python $os-$arch ready"
}

fetch_ollama() {  # os arch
  local os="$1" arch="$2" dest="$RT/ollama/pkg/$1-$2"
  local asset; asset="$(ollama_asset "$os" "$arch")"
  [ -z "$asset" ] && { log "no ollama build for $os-$arch, skipping"; return 0; }
  if [ -e "$dest/bin/ollama" ] || [ -e "$dest/ollama" ] || [ -e "$dest/ollama.exe" ]; then log "ollama $os-$arch present"; return 0; fi
  # Fast path: for the current host, copy the installed ollama (binary + CPU libs)
  # instead of a ~1GB download. Dereference symlinks (FAT) and skip GPU runners.
  if [ "$os-$arch" = "$(detect_os)-$(detect_arch)" ] && command -v ollama >/dev/null 2>&1; then
    local hbin; hbin="$(command -v ollama)"; local hlib=""
    for x in /usr/local/lib/ollama /usr/lib/ollama "$(dirname "$hbin")/../lib/ollama"; do
      [ -d "$x" ] && hlib="$x" && break
    done
    if [ -n "$hlib" ]; then
      log "copying host ollama (CPU libs) for $os-$arch …"
      mkdir -p "$dest/bin" "$dest/lib/ollama"
      cp -L "$hbin" "$dest/bin/ollama"
      if [ "${SPARKY_INCLUDE_GPU:-0}" = "1" ]; then
        cp -RL "$hlib"/. "$dest/lib/ollama/"
      else
        find "$hlib" -maxdepth 1 -mindepth 1 ! -type d -exec cp -L {} "$dest/lib/ollama/" \;
      fi
      log "ollama $os-$arch ready (from host)"
      return 0
    fi
  fi
  local url="https://github.com/ollama/ollama/releases/download/${OLLAMA_TAG}/${asset}"
  log "downloading ollama $os-$arch …"
  local tmp; tmp="$(mktemp -d)"; mkdir -p "$tmp/x"
  curl -fL --retry 3 -o "$tmp/$asset" "$url"
  case "$asset" in
    *.tar.zst) tar --zstd -xf "$tmp/$asset" -C "$tmp/x" ;;
    *.tgz)     tar -xzf "$tmp/$asset" -C "$tmp/x" ;;
    *.zip)     unzip -oq "$tmp/$asset" -d "$tmp/x" ;;
  esac
  # Prune GPU runner dirs (~GBs) — portable use is CPU-only. Done in tmp before
  # copying so we never write the heavy dirs to the (slow) stick.
  if [ "${SPARKY_INCLUDE_GPU:-0}" != "1" ]; then
    find "$tmp/x" -type d \( -name 'cuda*' -o -name 'rocm*' -o -name 'vulkan*' \) -prune -exec rm -rf {} + 2>/dev/null || true
  fi
  mkdir -p "$dest"
  cp -RL "$tmp/x/." "$dest/"
  rm -rf "$tmp"
  log "ollama $os-$arch ready"
}

run_bundled_python() {  # run the freshly-bundled python (handles FAT non-exec via loader)
  local bin="" pdir=""
  for d in "$RT"/python/*/; do
    for b in "$d/bin/python3.12" "$d/bin/python3"; do [ -e "$b" ] && { bin="$b"; pdir="${d%/}"; break 2; }; done
  done
  [ -z "$bin" ] && { command -v python3 >/dev/null 2>&1 && { python3 "$@"; return $?; }; return 1; }
  if [ -x "$bin" ]; then "$bin" "$@"; else
    local ld; ld="$(ld_for_arch)"; PYTHONHOME="$pdir" "$ld" "$bin" "$@"
  fi
}

fetch_pylib() {
  if [ -n "$(ls -A "$RT/pylib" 2>/dev/null)" ]; then log "pylib present"; return 0; fi
  log "installing pure-Python deps into runtime/pylib …"
  run_bundled_python -m pip install --no-cache-dir --target "$RT/pylib" "${PY_DEPS[@]}"
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
