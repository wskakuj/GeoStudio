"""Exact field-based GEO-MAP object lookup, independent of GUI."""
from __future__ import annotations

from collections.abc import Iterable
from .geomap import GeoObject


def search_objects(objects: Iterable[GeoObject], code: str = "",
                   field: str = "A2", value: str = "") -> list[GeoObject]:
    code = code.strip()
    value = value.strip().casefold()
    if field not in {"A1", "A2", "A3", "A4", "A5", "A6", "TX", "ID", "*"}:
        raise ValueError("Unsupported search field")
    if code and (len(code) != 4 or not code.isdigit()):
        raise ValueError("Kod obiektu musi mieć dokładnie cztery cyfry")
    result = []
    for obj in objects:
        if not obj.uid or (code and obj.code != code):
            continue
        if not value:
            result.append(obj)
            continue
        if field == "*":
            values = [obj.code, obj.uid, *obj.fields.values()]
            matching = any(str(item).strip().casefold() == value for item in values)
        elif field == "ID":
            matching = obj.uid.casefold() == value
        else:
            matching = obj.fields.get(field, "").strip().casefold() == value
        if matching:
            result.append(obj)
    return result
