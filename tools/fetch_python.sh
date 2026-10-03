#!/usr/bin/env bash
# Put a portable Python for this computer into <root>/runtime/python/<os-arch>.
#
#   tools/fetch_python.sh <root>
#
# Only the bootstrap: once Python is there, `python -m sparky runtime` fetches
# the rest (the model server and the libraries) in one cross-platform place.
# Works with the bash 3.2 that macOS ships, curl, tar, and either sha256sum
# or shasum.
set -euo pipefail

PBS_TAG="20261003"
PBS_PY="3.12.15"

ROOT="${1:?usage: fetch_python.sh <root>}"
ROOT="$(cd "$ROOT" && pwd)"

case "$(uname -s)" in
  Linux) OS=linux ;;
  Darwin) OS=macos ;;
  *) echo "Sparky: this script is for macOS and Linux; on Windows run setup.bat." >&2; exit 1 ;;
esac
case "$(uname -m)" in
  x86_64|amd64) ARCH=x86_64 ;;
  aarch64|arm64) ARCH=aarch64 ;;
  *) echo "Sparky: no portable Python for $(uname -m)." >&2; exit 1 ;;
esac
case "$OS-$ARCH" in
  linux-x86_64) TRIPLE=x86_64-unknown-linux-gnu ;;
  linux-aarch64) TRIPLE=aarch64-unknown-linux-gnu ;;
  macos-x86_64) TRIPLE=x86_64-apple-darwin ;;
  macos-aarch64) TRIPLE=aarch64-apple-darwin ;;
esac

DEST="$ROOT/runtime/python/$OS-$ARCH"
if [ -e "$DEST/bin/python3.12" ]; then
  exit 0
fi

ASSET="cpython-${PBS_PY}+${PBS_TAG}-${TRIPLE}-install_only_stripped.tar.gz"
BASE="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Sparky: downloading a portable Python for $OS-$ARCH (about 30 MB, once)..."
curl -fL --retry 3 --progress-bar -o "$TMP/$ASSET" "$BASE/$ASSET"
curl -fsL --retry 3 -o "$TMP/SHA256SUMS" "$BASE/SHA256SUMS"

EXPECTED="$(grep " $ASSET\$" "$TMP/SHA256SUMS" | awk '{print $1}')"
if command -v sha256sum >/dev/null 2>&1; then
  GOT="$(sha256sum "$TMP/$ASSET" | awk '{print $1}')"
else
  GOT="$(shasum -a 256 "$TMP/$ASSET" | awk '{print $1}')"
fi
if [ -z "$EXPECTED" ] || [ "$EXPECTED" != "$GOT" ]; then
  echo "Sparky: the Python download did not match its published checksum; stopping." >&2
  exit 1
fi

tar -xzf "$TMP/$ASSET" -C "$TMP"
PY="$TMP/python"
# Leave out what a portable runtime never uses, and the bin/ links: FAT and
# exFAT cannot store links, and copying them would triple the binary.
rm -rf "$PY/share" "$PY/include" "$PY"/lib/python3*/test "$PY"/lib/python3*/idlelib \
       "$PY"/lib/python3*/tkinter "$PY"/lib/python3*/turtledemo "$PY"/lib/python3*/config-3* \
       "$PY"/lib/libtcl* "$PY"/lib/libtk* "$PY"/lib/tcl* "$PY"/lib/tk* "$PY"/lib/itcl* "$PY"/lib/thread*
rm -rf "$PY"/lib/python3*/lib2to3 "$PY"/lib/python3*/ensurepip "$PY"/lib/python3*/pydoc_data
find "$PY/bin" -maxdepth 1 -type l -exec rm -f {} +
find "$PY/lib" -maxdepth 1 -type l -name 'libpython3*.so' -exec rm -f {} +

mkdir -p "$DEST"
cp -RL "$PY/." "$DEST/"
echo "$PBS_PY" > "$DEST/SPARKY_VERSION"
echo "Sparky: Python ready."
