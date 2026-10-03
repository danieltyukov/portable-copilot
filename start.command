#!/usr/bin/env bash
# macOS: double-click this in Finder to start Sparky from the stick.
# The first time, macOS may ask for confirmation: right-click it and choose Open.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$DIR/start.sh" "$@"
