"""Generuje geostudio.ico z obrazu źródłowego.

Ikona na pulpicie była wyraźnie mniejsza od sąsiednich, bo grafika zajmowała
tylko 46–58 % szerokości kafla (duży przezroczysty margines). Tutaj treść jest
przycinana do nieprzezroczystego obszaru i skalowana tak, aby wypełniać ~94 %
kafla dla każdego rozmiaru.

Użycie:
    python tools/windows/make_icon.py [źródło.ico|źródło.png] [wyjście.ico]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageFilter

SIZES = (16, 24, 32, 48, 64, 128, 256)
FILL = 0.94          # udział treści w kaflu


def content_box(image: Image.Image) -> Image.Image:
    """Przycina obraz do nieprzezroczystej treści (z zaokrąglonym bbox)."""
    frame = image.convert("RGBA")
    box = frame.getbbox()
    return frame.crop(box) if box else frame


def master_content(source: Path) -> Image.Image:
    """Największa dostępna treść ikony — źródło dla wszystkich rozmiarów."""
    if source.suffix.lower() == ".ico":
        icon = Image.open(source)
        best = max(icon.info.get("sizes", [(0, 0)]))
        icon.size = best
        return content_box(icon)
    return content_box(Image.open(source))


def build(master: Image.Image) -> list[Image.Image]:
    frames = []
    for size in SIZES:
        inner = max(1, round(size * FILL))
        art = master.resize((inner, inner), Image.LANCZOS)
        # Delikatne wyostrzenie po skalowaniu w górę.
        if inner > master.width:
            art = art.filter(ImageFilter.UnsharpMask(radius=1, percent=60, threshold=2))
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        offset = ((size - inner) // 2, (size - inner) // 2)
        canvas.paste(art, offset, art)
        frames.append(canvas)
    return frames


def main(argv: list[str]) -> int:
    source = Path(argv[1]) if len(argv) > 1 else Path("geostudio.ico")
    target = Path(argv[2]) if len(argv) > 2 else source
    master = master_content(source)
    frames = build(master)
    frames[-1].save(target, format="ICO",
                    sizes=[(f.width, f.height) for f in frames])
    print(f"{target}: {len(frames)} rozmiarów, treść {master.width}px -> "
          f"{round(FILL * 100)}% kafla")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
