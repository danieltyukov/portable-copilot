"""Sparky's look in the terminal: the brand yellow, a GitHub-dark palette
shared with meeting-copilot, and the pixel budgie drawn in half blocks."""

from __future__ import annotations

ACCENT = "#FFC61A"   # Sparky yellow, the brand colour

C = {
    "brand": ACCENT,
    "bg": "#0D1117",
    "panel": "#161B22",
    "border": "#30363D",
    "text": "#E6EDF3",
    "muted": "#8B949E",
    "dim": "#7D8590",
    "green": "#34D399",
    "cyan": "#38BDF8",
    "magenta": "#E879F9",
    "amber": "#FBBF24",
    "red": "#F87171",
}

# The same 16x16 one-colour budgie as the site and meeting-copilot
# (tools/sparky_assets.py): Y body, K eyes, . empty. The empty border rows
# and columns are trimmed here.
SPARKY = [
    ".....YY.....",
    "....YYYY....",
    "..YYYYYYYY..",
    ".YYYYYYYYYY.",
    "YYYYYYYYYYYY",
    "YYKKYYYYKKYY",
    "YYKKYYYYKKYY",
    "YYYYYYYYYYYY",
    "YYYYYYYYYYYY",
    "YYYYYYYYYYYY",
    ".YYYYYYYYYY.",
    ".YYYYYYYYYY.",
    "..YYYYYYYY..",
    "..YY....YY..",
]
EYE = "#1A1A1A"


def mascot_rows() -> list[list[tuple[str, str]]]:
    """The budgie as rows of (character, rich style), two pixel rows per text
    row: an upper half block coloured by the top pixel on a background of
    the bottom one."""
    colour = {"Y": ACCENT, "K": EYE, ".": None}
    rows = []
    for top, bottom in zip(SPARKY[0::2], SPARKY[1::2]):
        row = []
        for a, b in zip(top, bottom):
            fa, fb = colour[a], colour[b]
            if fa and fb:
                row.append(("▀", f"{fa} on {fb}"))
            elif fa:
                row.append(("▀", fa))
            elif fb:
                row.append(("▄", fb))
            else:
                row.append((" ", ""))
        rows.append(row)
    return rows


TAGLINE = "open-weight AI from a USB stick"
