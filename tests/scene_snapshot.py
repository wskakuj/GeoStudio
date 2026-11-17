"""Deterministic description of a rendered scene, used to prove refactors are inert.

``build_scene_window`` renders one fixed synthetic map with a fixed set of
libraries and overrides, and ``serialize_scene`` turns the result into plain
JSON-able data: item kind, stacking, geometry, pens, brushes, fonts, label
data and tooltips. Comparing that snapshot before and after a refactor shows
that rendering did not change, which passing tests alone cannot prove.
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QGraphicsSimpleTextItem

from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from geostudio.library_render import parse_cdf, parse_sym_primitives

# Rounded to micrometres: far finer than any visible difference, coarse enough
# to keep the golden file readable.
PRECISION = 6

# Qt resolves "Segoe UI" differently on Windows and on Linux, so anything the
# renderer derives from glyph metrics changes between machines. Those values
# are therefore recorded in a font-independent form instead of raw:
#
#   offsetPerHeight   setData(2) / measured text height
#                     -> +-0.6 for 5310, the line leading for sheet codes, 0 elsewhere
#   ratioRule         sheet codes: setData(3) * height / scale factor, i.e. the
#                     nominal A1 height in map units
#                     other codes: setData(3) unchanged, a constant 0.55
#
# Both forms are exactly reconstructible from the renderer's own rule, so the
# snapshot is identical on every platform while still catching any change to
# label sizing or placement.
SHEET_CODES = frozenset(("7900", "6900", "6000", "6301"))


def _f(value: float) -> float:
    return round(float(value), PRECISION)


def _color(value) -> list[int]:
    return list(value.getRgb())


def golden_map_bytes() -> bytes:
    """One map exercising every rendering branch of rebuild_scene."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from conftest import MapBuilder

    builder = MapBuilder(ext=(1000.0, 500000.0, 6500000.0, 500500.0, 6500500.0))
    # Parcel with a name and an explicit fill override in visual_styles.
    builder.object(code="5216", uid="PARCEL", fields={"A2": "12/3"},
                   points=[(500100.0, 6500100.0), (500200.0, 6500100.0),
                           (500200.0, 6500200.0), (500100.0, 6500200.0)])
    # Precinct with an A3 title.
    builder.object(code="5214", uid="PRECINCT", fields={"A3": "OBRĘB 0001"},
                   points=[(500000.0, 6500000.0), (500300.0, 6500000.0),
                           (500300.0, 6500300.0), (500000.0, 6500300.0)])
    # Two filled land-use polygons, styled from the CDF library.
    builder.object(code="5220", uid="FOREST", fields={"A2": "Ls"},
                   points=[(500120.0, 6500120.0), (500180.0, 6500120.0),
                           (500180.0, 6500180.0)])
    builder.object(code="5230", uid="MEADOW", fields={"A2": "R"},
                   points=[(500320.0, 6500320.0), (500380.0, 6500320.0),
                           (500380.0, 6500380.0)])
    # Single-point object rendered from SYM primitives.
    builder.object(code="5310", uid="BUILDING", closed=False,
                   fields={"A1": "101", "A2": "Budynek"},
                   points=[(500150.0, 6500250.0)])
    # Map title, multi-line legend text and a directional letter.
    builder.object(code="7900", uid="TITLE", closed=False,
                   fields={"TX": "MAPA ZASADNICZA||skala 1:1000"},
                   points=[(500050.0, 6500450.0), (500450.0, 6500450.0)])
    builder.object(code="6900", uid="NORTH", closed=False, fields={"TX": "N"},
                   points=[(500420.0, 6500420.0), (500420.0, 6500440.0)])
    # Compass quarter: 5200 with FA=0 must be painted near-black.
    builder.object(code="5200", uid="COMPASS", fields={"FA": "0"},
                   points=[(500400.0, 6500400.0), (500440.0, 6500400.0),
                           (500400.0, 6500440.0)])
    # Multipart object with a P 0 terminator between two components.
    builder.multipart(code="5216", uid="MULTI")
    # Open polyline: no fill, no area.
    builder.object(code="5216", uid="OPEN", closed=False,
                   points=[(500250.0, 6500450.0), (500300.0, 6500480.0),
                           (500350.0, 6500450.0)])
    # Unknown record that the parser must carry through untouched.
    builder.raw(":ZZZ[zachowaj]")
    return builder.build()


def build_scene_window(tmp_path: Path) -> GeoStudioWindow:
    """Render ``golden_map_bytes`` with a fixed catalogue, libraries and overrides."""
    tmp_path = Path(tmp_path)
    cdf = tmp_path / "TEST.CDF"
    cdf.write_bytes(
        b'; ID RGB S RGB W\r\n'
        b'5220.Ls 120 200 120 0 40 90 40 1.4 test\r\n'
        b'5230.R 200 220 150 2 60 120 60 0.9 test\r\n'
        b'5216.?.RV 10 255 10 4 0 20 0 0.25 test\r\n')
    sym = tmp_path / "TEST.SYM"
    sym.write_bytes(
        b'*5310 budynek\r\n'
        b' L 0.00 0.00 1.00 0.00\r\n'
        b' O 4001.00 0 0 0 0 0\r\n')

    window = GeoStudioWindow()
    window.doc = GeoMap(golden_map_bytes(), filename="GOLDEN.MAP")
    window.catalog = {"5216": "Działki", "5214": "Obręby", "?9??": "Opisy"}
    window.symbols = {"5216": "granica", "5310": "budynek"}
    window.cdf_styles = parse_cdf(cdf)
    window.sym_primitives = parse_sym_primitives(sym)
    window.visual_styles = {"MEADOW": {"fill": "#AABBCC", "opacity": 37}}
    window.label_positions = {"PARCEL": {"A2": [500160.0, 6500160.0]}}
    window.source_compilation_scale = 1000.0
    window.compilation_scale = 2000.0
    window.rebuild_scene(fit=False)
    return window


def _path_data(path: QPainterPath) -> dict:
    elements = []
    for index in range(path.elementCount()):
        element = path.elementAt(index)
        elements.append([int(element.type.value), _f(element.x), _f(element.y)])
    return {"elements": elements, "fillRule": int(path.fillRule().value)}


def _item_data(item, *, code: str | None = None, scale_factor: float = 1.0) -> dict:
    """One item as plain data.

    Keys ``data0``/``data1`` (object id and field name) are exact. The values
    the renderer stores under ``setData(2..4)`` are font-metric offsets, so
    they are recorded as dimensionless ratios to the item's own text height.
    """
    record = {
        "kind": type(item).__name__,
        "z": _f(item.zValue()),
        "pos": [_f(item.pos().x()), _f(item.pos().y())],
        "visible": bool(item.isVisible()),
        "ignoresTransformations": bool(
            item.flags() & item.GraphicsItemFlag.ItemIgnoresTransformations),
        "tooltip": item.toolTip(),
        "data0": item.data(0),
        "data1": item.data(1),
    }
    pen = getattr(item, "pen", None)
    pen = pen() if callable(pen) else pen
    if pen is not None:
        dash = list(pen.dashPattern()) if pen.style() == Qt.CustomDashLine else []
        record["pen"] = {"style": int(pen.style().value), "widthF": _f(pen.widthF()),
                         "color": _color(pen.color()), "dash": [_f(d) for d in dash]}
    brush = getattr(item, "brush", None)
    brush = brush() if callable(brush) else brush
    if brush is not None:
        record["brush"] = {"style": int(brush.style().value),
                           "color": _color(brush.color())}
    path = getattr(item, "path", None)
    if callable(path):
        record["path"] = _path_data(item.path())
    if isinstance(item, QGraphicsSimpleTextItem):
        height = item.boundingRect().height()
        metrics = {}
        if height > 0:
            offset = item.data(2)
            ratio = item.data(3)
            if offset is not None:
                metrics["offsetPerHeight"] = _f(offset / height)
            if ratio is not None:
                if code in SHEET_CODES:
                    metrics["ratioRule"] = _f(ratio * height / scale_factor)
                else:
                    metrics["ratioRule"] = _f(ratio)
        record["metrics"] = metrics
        font = item.font()
        record["text"] = {
            "content": item.text(),
            "family": font.family(),
            "pixelSize": int(font.pixelSize()),
            "bold": bool(font.bold()),
            "brush": _color(item.brush().color()),
        }
    return record


def serialize_scene(window: GeoStudioWindow) -> dict:
    """Snapshot of every item in the scene plus the maps rebuild_scene fills in.

    Items are listed in paint order (bottom to top), which is what the user
    sees: a change in stacking or in the order equal-z items are added shows
    up as a reordered list.
    """
    ordered = window.map_scene.items(Qt.AscendingOrder)
    scale_factor = ((window.compilation_scale or 1.0)
                    / (window.source_compilation_scale or 1.0))
    doc = window.doc
    items = []
    for index, item in enumerate(ordered):
        uid = item.data(0)
        obj = doc.by_id.get(uid) if (doc is not None and isinstance(uid, str)) else None
        record = _item_data(item, code=obj.code if obj else None,
                            scale_factor=scale_factor)
        record["paintIndex"] = index
        items.append(record)
    return {
        "items": items,
        "itemCount": len(items),
        "layerForUid": dict(sorted(window.layer_for_uid.items())),
        "graphicsForUid": sorted(window.graphics_for_uid),
        "fillItemsForUid": sorted(window.fill_items_for_uid),
        "itemsByLayer": {name: len(values)
                         for name, values in sorted(window.items_by_layer.items())},
        "labels": len(window.labels),
        "labelKeys": sorted(f"{uid}|{field}" for uid, field in window.label_items),
        "labelWorldSpan": {uid: _f(span)
                           for uid, span in sorted(window.label_world_span.items())},
        "labelPositions": {f"{uid}|{field}": [_f(item.pos().x()), _f(item.pos().y())]
                           for (uid, field), item in sorted(window.label_items.items())},
    }


def snapshot_json(window: GeoStudioWindow) -> str:
    return json.dumps(serialize_scene(window), indent=1, sort_keys=True,
                      ensure_ascii=False)
