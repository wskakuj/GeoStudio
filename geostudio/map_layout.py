"""GEO-MAP cartographic compilation scale and conservative text sizing.

GEO-MAP stores nominal annotation heights in A1 map metres in observed v8
files. For the map sheet, *7900: A1[30] is 30 projected units high, not
a 30-pixel font. At 1:5000 this produces ~6 mm printed type.

This module handles only visual presentation in GeoStudio. The original
MAP geometry and nominal-scale metadata remain untouched.
"""
from __future__ import annotations

import math
import re

_SCALE_RE = re.compile(r"\bSKALA\s*1\s*:\s*([1-9][0-9]{2,6})\b", re.I)
SHEET_CODES = frozenset(("7900", "6900", "6000", "6301"))
MIN_SCALE = 100
MAX_SCALE = 1_000_000
DEFAULT_SCALE = 5000


def validated_compilation_scale(value, *, default=None) -> int | None:
    try:
        num = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return num if MIN_SCALE <= num <= MAX_SCALE else default


def detect_source_compilation_scale(objects, default=DEFAULT_SCALE) -> int:
    """Prefer the actual source legend's 'SKALA 1:5000' text over guessing."""
    for obj in objects:
        if obj.code not in SHEET_CODES:
            continue
        tx = obj.fields.get('TX', '')
        match = _SCALE_RE.search(tx)
        if match:
            return validated_compilation_scale(match.group(1), default=default)
    return default


def source_text_height(fields, default=12.0) -> float:
    """Convert a positive finite A1 height to projected map units."""
    try:
        height = float(str(fields.get('A1', default)).replace(',', '.'))
        if not math.isfinite(height) or height <= 0:
            return default
        return min(2000.0, max(1.0, height))
    except (TypeError, ValueError, OverflowError):
        return default


def label_ratio(code, fields, font_bounding_height,
                compilation_scale, source_scale) -> float:
    """Size a map label independent of device DPI and current zoom."""
    if not math.isfinite(font_bounding_height) or font_bounding_height <= 0:
        return .55
    effective = validated_compilation_scale(compilation_scale, default=DEFAULT_SCALE)
    reference = validated_compilation_scale(source_scale, default=DEFAULT_SCALE)
    scale_factor = effective / reference
    if code in SHEET_CODES:
        # A1 is already a nominal text height in world/map units.
        base = source_text_height(fields) / font_bounding_height
    else:
        base = .55
    return base * scale_factor


def text_line_offset(index: int, count: int, bounding_height: float,
                     *, leading: float = 1.18) -> float:
    """Offset in item-local glyph units; multiplied by label_ratio later."""
    return (index-(count-1)/2) * bounding_height * leading
