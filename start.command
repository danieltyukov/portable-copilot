#!/usr/bin/env bash
# macOS Finder double-click launcher: cd to the stick and run start.sh.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$DIR/start.sh" "$@"
