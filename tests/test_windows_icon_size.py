"""Ikona Windows musi wypełniać kafel — inaczej jest mniejsza od sąsiednich."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ICON = Path("geostudio.ico")


def _frames(icon: Image.Image):
    for size in sorted(icon.info["sizes"]):
        icon.size = size
        yield size[0] if isinstance(size, tuple) else size, icon.convert("RGBA")


def test_icon_has_all_windows_sizes():
    icon = Image.open(ICON)
    sizes = {s[0] if isinstance(s, tuple) else s for s in icon.info["sizes"]}
    assert {16, 32, 48, 256} <= sizes


def test_icon_content_fills_the_tile():
    icon = Image.open(ICON)
    for width, frame in _frames(icon):
        box = frame.getbbox()
        assert box, f"pusty kafel {width}px"
        fill = (box[2] - box[0]) / width
        # Wcześniej grafika zajmowała 46–58 % i ikona wyglądała na małą.
        assert fill >= 0.90, f"{width}px: treść zajmuje tylko {fill:.0%}"


def test_icon_generator_exists():
    assert Path("tools/windows/make_icon.py").is_file()
