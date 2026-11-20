"""Read-only CRS verification and point conversion for web stage 12C.

No EPSG is deduced from the magnitude of GEO-MAP coordinates. A PRJ
must contain a valid projected CRS, or the user selects it explicitly.
Transformations do not change in-memory or on-disk MAP records.
"""
from __future__ import annotations

from math import isfinite

from geostudio.coordinates import MODERN_EPSG, transform_xy
from pyproj.exceptions import CRSError

MAX_PRJ = 128 * 1024


def verified_prj_epsg(raw: bytes) -> int:
    if not raw or len(raw) > MAX_PRJ:
        raise ValueError("Plik PRJ jest pusty lub zbyt duży.")
    try:
        from pyproj import CRS
        text = raw.decode("utf-8-sig")
        crs = CRS.from_wkt(text)
        number = crs.to_epsg(min_confidence=95)
    except (UnicodeError, ValueError, CRSError) as exc:
        raise ValueError("Plik PRJ nie zawiera poprawnego WKT.") from exc
    if number not in MODERN_EPSG:
        raise ValueError("Nie potwierdzono obsługiwanego EPSG (PL-1992/PL-2000).")
    return number


def convert_point(x: float, y: float, source: int, target: int) -> dict:
    if source not in MODERN_EPSG or target not in MODERN_EPSG:
        raise ValueError("Dozwolone są tylko PL-1992 i strefy PL-2000.")
    if not (isfinite(x) and isfinite(y)):
        raise ValueError("X i Y muszą być skończone.")
    new_x, new_y = transform_xy(x, y, source, target)
    return {"source":source,"target":target,
            "x":new_x,"y":new_y,
            "originalX":x,"originalY":y}
