"""Sparky brand-asset generator.

Single source of truth for the Sparky mascot: a one-colour pixel budgie with
two eyes, the same map as the sibling project meeting-copilot. Every icon is
drawn from the one ASCII map below, so each size is reproducible (the README
banner is tools/banner.html):

    python3 tools/sparky_assets.py      # writes the SVGs

Run tools/render_assets.sh to regenerate the SVGs and every PNG at once.
"""
from pathlib import Path

YELLOW = "#FFC61A"   # the one body colour
INK = "#1A1A1A"      # eyes on the yellow mark, body on the ink mark

# 16x16 single-colour budgie. 'Y' = body, 'K' = eye, '.' = empty. The crest
# tuft, the chunky body and the two feet carry it; no second body colour needed.
SPARKY = [
    "................",
    ".......YY.......",
    "......YYYY......",
    "....YYYYYYYY....",
    "...YYYYYYYYYY...",
    "..YYYYYYYYYYYY..",
    "..YYKKYYYYKKYY..",
    "..YYKKYYYYKKYY..",
    "..YYYYYYYYYYYY..",
    "..YYYYYYYYYYYY..",
    "..YYYYYYYYYYYY..",
    "...YYYYYYYYYY...",
    "...YYYYYYYYYY...",
    "....YYYYYYYY....",
    "....YY....YY....",
    "................",
]
N = len(SPARKY)

# The yellow mark is for dark backgrounds, the ink mark for light ones.
YELLOW_MARK = {"Y": YELLOW, "K": INK, ".": None}
INK_MARK = {"Y": INK, "K": YELLOW, ".": None}


def sparky_group(x0, y0, cell, cols):
    """Pixel <rect>s for Sparky. Cells overlap by 0.6px to kill antialiased seams."""
    ov = 0.6
    out = []
    for r, row in enumerate(SPARKY):
        for c, ch in enumerate(row):
            col = cols[ch]
            if not col:
                continue
            x = x0 + c * cell
            y = y0 + r * cell
            out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell+ov:.1f}" '
                       f'height="{cell+ov:.1f}" fill="{col}"/>')
    return "\n  ".join(out)


def write_icon(path, cols):
    """Sparky alone, on a transparent background."""
    size = 128
    cell = 7
    grid = N * cell
    off = (size - grid) / 2
    svg = f'''<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" \
xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
  {sparky_group(off, off, cell, cols)}
</svg>
'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(svg)


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    for rel, cols in [
        ("site/assets/icon.svg", YELLOW_MARK),
        ("site/assets/budgie-ink.svg", INK_MARK),
        ("sparky/web/static/icon.svg", YELLOW_MARK),
    ]:
        write_icon(root / rel, cols)
        print(f"wrote {rel}")
