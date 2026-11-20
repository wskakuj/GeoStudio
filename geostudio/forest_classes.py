"""Classify forest land-use objects without changing source GEO-MAP records.

A1 is the land-use classification on 5230 (e.g. Ls, LsV or LsVI).
Some source maps store the same notation in A2; accept it as a fallback
only when A1 is not a forest classification. Do not turn roads or other
5230 land uses into forests.
"""
from __future__ import annotations

import re

FOREST_LAYER = "Użytki Leśne"
FILTER_KEY = "forest-class-visibility"


def forest_class_value(obj) -> str | None:
    """Normalize Ls/roman-grade subclass while preserving useful display case."""
    # Both 5220 and 5230 can carry land-use records in imported MAPs.
    # Forest grade belongs to the forest layer regardless of which
    # of these codes contains the Ls/roman-class notation.
    if obj.code not in {"5220", "5230"}:
        return None
    for field in ("A1", "A2"):
        value = re.sub(r"\s+", "", str(obj.fields.get(field, "") or ""))
        if re.fullmatch(r"Ls(?:[IVX]+[a-d]?)?", value, re.IGNORECASE):
            suffix = value[2:]
            roman = re.match(r"[ivx]*", suffix, re.IGNORECASE).group(0)
            return "Ls" + roman.upper() + suffix[len(roman):].lower()
    return None


def forest_layer_for_object(obj, catalog) -> str:
    """Group all forest site classes into one visibility layer."""
    if forest_class_value(obj) is not None:
        return FOREST_LAYER
    from .geomap import resolve_layer
    return resolve_layer(catalog, obj.code)


def forest_hidden_classes(styles) -> set[str]:
    """Persist class-specific hide state, not the entire forest layer."""
    stored = styles.get(FILTER_KEY, {}).get("hidden", [])
    return set(stored) if isinstance(stored, list) else set()
