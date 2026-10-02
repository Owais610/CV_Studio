"""Generate CV Studio's app icon with Pillow, without external artwork.

Run from any directory: python scripts/create_app_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw


ASSETS = Path(__file__).resolve().parents[1] / "assets"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
NAVY = "#18232F"
PAPER = "#F8FAFC"
FOLD = "#DCE7F3"
BLUE = "#5186BC"
SLATE = "#8796A6"

SVG = f'''<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
  <title>CV Studio</title>
  <rect x="6" y="6" width="244" height="244" rx="52" fill="{NAVY}"/>
  <path d="M80 43H157L188 74V204Q188 216 176 216H80Q68 216 68 204V55Q68 43 80 43Z" fill="{PAPER}"/>
  <path d="M157 43L188 74H169Q157 74 157 62Z" fill="{FOLD}"/>
  <rect x="88" y="96" width="80" height="11" rx="3" fill="{BLUE}"/>
  <rect x="88" y="129" width="80" height="7" rx="2" fill="{SLATE}"/>
  <rect x="88" y="151" width="80" height="7" rx="2" fill="{SLATE}"/>
  <rect x="88" y="173" width="58" height="7" rx="2" fill="{SLATE}"/>
</svg>
'''


def create_icon() -> None:
    """Draw at four times the final size for crisp antialiased edges."""
    factor = 4
    icon = Image.new("RGBA", (256 * factor, 256 * factor), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)

    def box(coords):
        return tuple(value * factor for value in coords)

    def points(coords):
        return [(x * factor, y * factor) for x, y in coords]

    draw.rounded_rectangle(box((6, 6, 250, 250)), radius=52 * factor, fill=NAVY)
    draw.rounded_rectangle(box((68, 43, 188, 216)), radius=12 * factor, fill=PAPER)
    # The folded corner uses the same geometry as the editable SVG source.
    draw.polygon(points(((157, 43), (189, 43), (189, 75))), fill=NAVY)
    draw.polygon(points(((157, 43), (188, 74), (169, 74), (157, 62))), fill=FOLD)
    for coords, radius, color in (
        ((88, 96, 168, 107), 3, BLUE),
        ((88, 129, 168, 136), 2, SLATE),
        ((88, 151, 168, 158), 2, SLATE),
        ((88, 173, 146, 180), 2, SLATE),
    ):
        draw.rounded_rectangle(box(coords), radius=radius * factor, fill=color)

    icon = icon.resize((256, 256), Image.Resampling.LANCZOS)
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "icon.svg").write_text(SVG, encoding="utf-8", newline="\n")
    icon.save(ASSETS / "icon.png", format="PNG")
    icon.save(ASSETS / "icon.ico", format="ICO", sizes=[(size, size) for size in ICON_SIZES])
    print(f"Created icon.svg, icon.png and icon.ico in {ASSETS}")


if __name__ == "__main__":
    create_icon()
