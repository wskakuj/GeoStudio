"""Screen-stable GEO-MAP-like label appearance.

The font is expressed in *pixels*, not points or geodetic map units. The
Qt graphics item must also use ItemIgnoresTransformations. The readability
filter may skip overlapping labels but never changes their font size.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class MapLabelStyle:
    font_family: str
    pixel_size: int
    bold: bool
    color: str
    opacity: int = 255


def map_label_style(code: str, field: str) -> MapLabelStyle:
    if code == '5310':
        # Forestry wydzielenie: red, legible and bold on close-up views.
        return MapLabelStyle('Arial', 14 if field == 'A1' else 13,
                             True, '#E41F29', 255)
    if code == '5216':
        # Parcel numbers: neutral grey like the GEO-MAP cadastral layer.
        return MapLabelStyle('Arial', 11, False, '#626B70', 215)
    if code in ('5220', '5230'):
        # Forest land-use and land-class labels: subdued green.
        return MapLabelStyle('Arial', 10, False, '#378349', 205)
    return MapLabelStyle('Arial', 10, False, '#4C5C60', 205)


def display_label_text(code: str, field: str, value: str) -> str:
    value = value.strip()
    if code == '5310' and field == 'A2':
        # GEO-MAP forestry annotations separate stand type and age/group.
        return value.replace('||', '\n').replace('|', '\n')
    if field == 'TX':
        return value.replace('||', '\n').replace('|', ' ')
    return value
