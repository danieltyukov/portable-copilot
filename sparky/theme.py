"""Sparky theme — the pixel-budgie mascot + the brand palette (#FFC61A on a
GitHub-dark scheme), reused from the interview-copilot project."""

from __future__ import annotations

# Palette (hex) — mirrors interview-copilot/extension/sidepanel.css
C = {
    "brand": "#FFC61A",   # Sparky yellow
    "bg": "#0d1117",
    "panel": "#161b22",
    "border": "#30363d",
    "text": "#e6edf3",
    "muted": "#7d8590",
    "teal": "#34d399",
    "cyan": "#38bdf8",
    "magenta": "#e879f9",
    "amber": "#fbbf24",
    "red": "#f87171",
}

# A compact pixel-budgie, drawn with block characters in the brand yellow.
MASCOT = r"""
   ██
  ████
 ██████
██ ██ ██
████████
████████
 ██████
 ██  ██
""".strip("\n")

TAGLINE = "portable copilot · claude online · qwen offline"
