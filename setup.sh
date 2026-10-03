#!/usr/bin/env bash
# First-time setup on macOS or Linux, from a clone or a downloaded copy:
#
#   ./setup.sh                 the wizard asks everything
#   ./setup.sh --help          every option (target, purposes, models, systems)
#
# Fetches a portable Python into this folder if needed (so the computer needs
# no Python of its own), then runs the setup wizard with it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$ROOT/tools/fetch_python.sh" "$ROOT"

case "$(uname -s)" in Darwin) OS=macos ;; *) OS=linux ;; esac
case "$(uname -m)" in aarch64|arm64) ARCH=aarch64 ;; *) ARCH=x86_64 ;; esac
PYDIR="$ROOT/runtime/python/$OS-$ARCH"

export PYTHONHOME="$PYDIR"
export PYTHONPATH="$ROOT"
export PYTHONDONTWRITEBYTECODE=1
export PYTHONNOUSERSITE=1          # never mix in packages from the host computer
export PYTHONSAFEPATH=1            # the folder you start in is not on the import path
exec "$PYDIR/bin/python3.12" -m sparky setup "$@"
