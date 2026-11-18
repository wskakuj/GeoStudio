"""GeoStudio-only visual styling. Never modifies GEO-MAP binary/text records.

Sidecars live alongside *new* work copies, not inside source MAP files.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_COLOR_CODE = re.compile(r"^#?([0-9a-fA-F]{6})(?:@(\d{1,3}))?$")


def parse_fill_code(value: str, default_opacity: int = 25) -> tuple[str, int]:
    """Parse #RRGGBB or #RRGGBB@opacity%; no ambiguity about decimal/alpha."""
    match = _COLOR_CODE.fullmatch(value.strip())
    if not match:
        raise ValueError("Kolor musi mieć postać #RRGGBB lub #RRGGBB@40")
    opacity = int(match.group(2)) if match.group(2) is not None else default_opacity
    if not 0 <= opacity <= 100:
        raise ValueError("Przezroczystość / krycie musi być w zakresie 0–100%.")
    return "#" + match.group(1).upper(), opacity


def fill_code(color: str, opacity: int) -> str:
    return f"{parse_fill_code(color, opacity)[0]}@{opacity}"


def sidecar_path(map_path: str | Path) -> Path:
    return Path(str(map_path) + ".geostudio.json")


def validated_styles(styles: dict) -> dict[str, dict]:
    cleaned = {}
    for uid, style in styles.items():
        if not isinstance(uid, str) or not isinstance(style, dict):
            continue
        if re.fullmatch(r"layout:[0-9a-f]{32}", uid):
            # New map furniture shares the same visual sidecar and history;
            # never appears as a fake object in the original GEO-MAP file.
            from math import isfinite
            kind = style.get("kind")
            if kind not in {"north", "title", "credits", "legend"}:
                continue
            try:
                x, y = float(style["x"]), float(style["y"])
            except (KeyError, ValueError, TypeError):
                continue
            if not (isfinite(x) and isfinite(y) and
                    abs(x) < 1e9 and abs(y) < 1e9):
                continue
            texts = {}
            for key in ("title", "subtitle", "details", "area"):
                value = str(style.get(key, ""))[:3000]
                if any(ord(c) < 32 and c not in "\\n\\t" for c in value):
                    value = ""
                texts[key] = value
            cleaned[uid] = {"kind": kind, "x": x, "y": y, **texts}
            continue
        if uid.startswith("legacy-hidden:") and len(uid) < 300:
            if style.get("hidden") is True:
                cleaned[uid] = {"hidden": True}
            continue
        if re.fullmatch(r"code:\d{4}", uid):
            # An opacity override for a whole GEO-MAP code need not change
            # any original per-object CDF/native fill color. Store it in
            # the existing sidecar dictionary so Undo/Redo works unchanged.
            try:
                opacity = int(style["opacity"])
                if not 0 <= opacity <= 100:
                    continue
                entry = {"opacity": opacity}
                if "fill" in style:
                    entry["fill"] = parse_fill_code(str(style["fill"]))[0]
                cleaned[uid] = entry
            except (KeyError, ValueError, TypeError):
                continue
            continue
        try:
            color, opacity = parse_fill_code(str(style["fill"]), int(style["opacity"]))
            cleaned[uid] = {"fill": color, "opacity": opacity}
        except (KeyError, ValueError, TypeError):
            continue
    return cleaned




def validated_label_positions(positions: dict) -> dict[str, dict[str, list[float]]]:
    """Only A1/A2 geographic coordinates are allowed in visual sidecars."""
    from math import isfinite
    result = {}
    if not isinstance(positions, dict):
        return result
    for uid, fields in positions.items():
        if not isinstance(uid, str) or not isinstance(fields, dict):
            continue
        valid = {}
        for key, xy in fields.items():
            if key not in ('A1','A2','TX') or not isinstance(xy, (list, tuple)) or len(xy) != 2:
                continue
            try:
                x,y = float(xy[0]), float(xy[1])
            except (TypeError, ValueError):
                continue
            if isfinite(x) and isfinite(y) and abs(x)<1e9 and abs(y)<1e9:
                valid[key] = [x,y]
        if valid:
            result[uid] = valid
    return result


def _read_payload(map_path: str | Path) -> dict:
    path = sidecar_path(map_path)
    if not path.exists():
        return {'format':'geostudio-visual-v1','objects':{},'labels':{}}
    if path.stat().st_size > 2_000_000:
        raise ValueError('Plik stylów jest zbyt duży')
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload,dict) or payload.get('format') != 'geostudio-visual-v1':
        raise ValueError('Nieznany format stylów GeoStudio')
    return payload


def load_label_positions(map_path: str | Path) -> dict[str, dict[str, list[float]]]:
    return validated_label_positions(_read_payload(map_path).get('labels', {}))


def load_styles(map_path: str | Path) -> dict[str, dict]:
    return validated_styles(_read_payload(map_path).get('objects', {}))


def write_styles(map_path: str | Path, styles: dict, *, overwrite: bool = False,
                 label_positions: dict | None = None) -> None:
    """Write sidecar (not MAP). Existing user style files never overwritten unless explicitly owned."""
    import os
    import tempfile
    target = sidecar_path(map_path)
    data = (json.dumps({"format": "geostudio-visual-v1",
                        "objects": validated_styles(styles),
                        "labels": validated_label_positions(label_positions or {})},
                       ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if not overwrite:
        with target.open("xb") as output:
            output.write(data)
        return
    fd, tmp = tempfile.mkstemp(prefix=".geostudio-style-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
