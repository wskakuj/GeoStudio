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
        try:
            color, opacity = parse_fill_code(str(style["fill"]), int(style["opacity"]))
            cleaned[uid] = {"fill": color, "opacity": opacity}
        except (KeyError, ValueError, TypeError):
            continue
    return cleaned


def load_styles(map_path: str | Path) -> dict[str, dict]:
    source = sidecar_path(map_path)
    if not source.is_file():
        return {}
    if source.stat().st_size > 2_000_000:
        raise ValueError("Plik stylów jest zbyt duży")
    content = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(content, dict) or content.get("format") != "geostudio-visual-v1":
        raise ValueError("Nieznany format stylów GeoStudio")
    styles = content.get("objects", {})
    if not isinstance(styles, dict):
        raise ValueError("Nieprawidłowa lista stylów")
    return validated_styles(styles)


def write_styles(map_path: str | Path, styles: dict, *, overwrite: bool = False) -> None:
    """Write sidecar (not MAP). Existing user style files never overwritten unless explicitly owned."""
    import os
    import tempfile
    target = sidecar_path(map_path)
    data = (json.dumps({"format": "geostudio-visual-v1",
                        "objects": validated_styles(styles)},
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
