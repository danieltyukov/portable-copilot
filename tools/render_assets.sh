#!/usr/bin/env bash
# Regenerate every Sparky brand asset: the SVG marks (tools/sparky_assets.py),
# the 48px favicon, and the README banner pair. Needs Chrome or Chromium, and
# network for the banner's fonts (Google Fonts). Inkscape is used for the
# favicon when it is installed, Chrome otherwise.
set -euo pipefail
cd "$(dirname "$0")/.."

CHROME="${CHROME:-$(command -v google-chrome || command -v chromium || command -v chromium-browser || true)}"
[ -n "$CHROME" ] || { echo "Chrome or Chromium not found; set CHROME=/path/to/chrome" >&2; exit 1; }

python3 tools/sparky_assets.py

# shot <url> <out.png> <width> <height> [scale]: one headless screenshot, transparent background.
shot() {
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars \
    --force-device-scale-factor="${5:-1}" --default-background-color=00000000 \
    --virtual-time-budget=6000 --window-size="$3,$4" \
    --screenshot="$PWD/$2" "$1" >/dev/null 2>&1
}

# favicon PNG, next to the SVG one
if command -v inkscape >/dev/null; then
  inkscape site/assets/icon.svg --export-type=png --export-filename=site/assets/icon48.png -w 48 >/dev/null 2>&1
else
  shot "file://$PWD/site/assets/icon.svg" site/assets/icon48.png 128 128 0.375
fi

# README banner, light and dark: tools/banner.html drawn with the site's own
# stylesheet, at 2x (2400x920). The light one doubles as the site's social preview.
shot "file://$PWD/tools/banner.html"       docs/logo.png      1200 460 2
shot "file://$PWD/tools/banner.html?dark"  docs/logo-dark.png 1200 460 2
cp docs/logo.png site/assets/logo.png

echo "Sparky assets regenerated."
