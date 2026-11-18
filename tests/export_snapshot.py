"""Reference exports captured from the code before exporters.py was extracted.

PNG bytes are deterministic on a given Qt build, so the snapshot stores a hash
plus a coarse signature. The hash is compared exactly only where the recorded
Qt version and platform still match; elsewhere the signature is used, so a
Windows machine or a newer Qt does not fail the test for no reason.

DXF is compared structurally: ezdxf stamps a creation time and handles into
the file, so two identical exports are never byte-identical.
"""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QFileDialog, QMessageBox

from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap

GRID = 16
BACKGROUND = "#ffffff"
# A pixel counts as ink only if it differs from the paper by more than this
# (sum over RGB, 0..765). JPEG noise moves nearly every pixel by one or two
# steps; real drawing is far above the threshold.
INK_THRESHOLD = 30

# Layer names that exercise the DXF sanitiser: forbidden characters, an
# over-long name and an unmapped code ("Inne / kod 5200").
CATALOG = {
    "5216": 'Działki <granice> "1"',
    "5214": "Obręby/arkusze:2024",
    "5230": "Użytki; rolne|łąki",
    "5200": "x" * 140,
}


def export_map_bytes() -> bytes:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from conftest import MapBuilder

    builder = MapBuilder(ext=(1000.0, 500000.0, 6500000.0, 500500.0, 6500500.0))
    # Parcels: closed rings, no A2/A3 labels, so the rendered image does not
    # depend on font metrics and stays comparable across systems.
    builder.object(code="5216", uid="P1",
                   points=[(500100.0, 6500100.0), (500250.0, 6500100.0),
                           (500250.0, 6500250.0), (500100.0, 6500250.0)])
    builder.object(code="5216", uid="P2",
                   points=[(500250.0, 6500250.0), (500400.0, 6500250.0),
                           (500400.0, 6500400.0)])
    builder.object(code="5214", uid="PRECINCT",
                   points=[(500000.0, 6500000.0), (500500.0, 6500000.0),
                           (500500.0, 6500500.0), (500000.0, 6500500.0)])
    builder.object(code="5230", uid="LAND",
                   points=[(500300.0, 6500100.0), (500450.0, 6500100.0),
                           (500450.0, 6500200.0)])
    builder.object(code="5200", uid="POINT", closed=False,
                   points=[(500420.0, 6500420.0)])
    builder.object(code="9999", uid="UNMAPPED",
                   points=[(500350.0, 6500350.0), (500380.0, 6500350.0),
                           (500380.0, 6500380.0)])
    builder.raw(":ZZZ[zachowaj]")
    return builder.build()


def build_export_window(tmp_path: Path) -> GeoStudioWindow:
    window = GeoStudioWindow()
    window.doc = GeoMap(export_map_bytes(), filename="EXPORT.MAP")
    # GeoStudioWindow restores the libraries the user used last time from
    # QSettings. That makes rendering depend on whatever ran before, on this
    # machine and in this session, so the export fixture clears every style
    # container before rendering. Without this the reference image changes
    # whenever another test (or another developer) has libraries loaded.
    window.catalog = dict(CATALOG)
    window.symbols = {}
    window.cdf_styles = {}
    window.sym_primitives = {}
    window.sym_line_patterns = {}
    window.lay_pen_styles = {}
    window.visual_styles = {}
    window.label_positions = {}
    window.hidden_layers = set()
    window.rebuild_scene(fit=False)
    return window


def _save_with(dialog_path: str):
    """Make the window's save dialogs return one fixed path."""
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (dialog_path, ""))


def _quiet():
    QMessageBox.information = staticmethod(lambda *a, **k: None)
    QMessageBox.warning = staticmethod(lambda *a, **k: None)


def _rgb_array(image: QImage):
    """(h, w, 3) uint8 array of an image, without a per-pixel Python loop."""
    import numpy as np
    converted = image.convertToFormat(QImage.Format_RGB32)
    height, width = converted.height(), converted.width()
    buffer = converted.constBits()
    data = bytes(buffer)
    array = np.frombuffer(data, dtype=np.uint8)
    array = array.reshape(height, converted.bytesPerLine())[:, :width * 4]
    return array.reshape(height, width, 4)[:, :, :3]


def _png_signature(image: QImage) -> dict:
    """Coarse, platform-tolerant description of a rendered image.

    Thin cartographic lines barely move a cell's mean colour, so the content is
    described by how much ink each cell holds instead: that reacts strongly to
    geometry moving and hardly at all to antialiasing differences between Qt
    builds.
    """
    import numpy as np

    reference = np.array(image.pixelColor(0, 0).getRgb()[:3], dtype=int)
    probe = image.scaled(min(image.width(), 512), min(image.height(), 512))
    pixels = _rgb_array(probe).astype(int)
    mask = np.abs(pixels - reference).sum(axis=2) > INK_THRESHOLD

    rows, columns = np.nonzero(mask)
    bbox = None
    if rows.size:
        scale_x = image.width() / probe.width()
        scale_y = image.height() / probe.height()
        bbox = [int(round(columns.min() * scale_x)), int(round(rows.min() * scale_y)),
                int(round(columns.max() * scale_x)), int(round(rows.max() * scale_y))]

    ink_grid = []
    step_y = probe.height() / GRID
    step_x = probe.width() / GRID
    for cell_y in range(GRID):
        for cell_x in range(GRID):
            y0, y1 = int(cell_y * step_y), max(int((cell_y + 1) * step_y), int(cell_y * step_y) + 1)
            x0, x1 = int(cell_x * step_x), max(int((cell_x + 1) * step_x), int(cell_x * step_x) + 1)
            block = mask[y0:y1, x0:x1]
            ink_grid.append(round(float(block.mean()) if block.size else 0.0, 6))

    return {
        "background": image.pixelColor(0, 0).name(),
        "contentBox": bbox,
        "inkFraction": round(float(mask.mean()) if mask.size else 0.0, 6),
        "inkGrid": ink_grid,
    }


def _image_facts(path: Path) -> dict:
    image = QImage(str(path))
    if image.isNull():
        return {"readable": False}
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")            # canonical re-encoding for hashing
    payload = bytes(buffer.data())
    facts = {
        "readable": True,
        "width": image.width(),
        "height": image.height(),
        "format": path.suffix.lower(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size": path.stat().st_size,
        "signature": _png_signature(image),
    }
    buffer.close()
    return facts


def _dxf_structure(path: Path) -> dict:
    import ezdxf

    doc = ezdxf.readfile(str(path))
    model = doc.modelspace()
    entities = []
    for entity in model:
        record = {"type": entity.dxftype(), "layer": entity.dxf.layer}
        if entity.dxftype() == "LWPOLYLINE":
            record["points"] = [[round(x, 6), round(y, 6)]
                                for x, y in entity.get_points("xy")]
            record["closed"] = bool(entity.closed)
        elif entity.dxftype() == "POINT":
            location = entity.dxf.location
            record["points"] = [[round(location.x, 6), round(location.y, 6)]]
        entities.append(record)
    return {
        "dxfversion": doc.dxfversion,
        "layers": sorted(layer.dxf.name for layer in doc.layers),
        "entities": entities,
    }


def run_exports(window: GeoStudioWindow, outdir: Path) -> dict:
    """Drive the real export methods and describe what they produced."""
    saved_dialog = QFileDialog.getSaveFileName
    saved_info = QMessageBox.information
    saved_warning = QMessageBox.warning
    _quiet()
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        return _run_exports(window, outdir)
    finally:
        QFileDialog.getSaveFileName = saved_dialog
        QMessageBox.information = saved_info
        QMessageBox.warning = saved_warning


def _run_exports(window: GeoStudioWindow, outdir: Path) -> dict:
    result: dict = {"environment": {"qt": _qt_version(), "platform": sys.platform}}

    for suffix in (".png", ".jpg", ".tif"):
        target = outdir / ("export" + suffix)
        _save_with(str(target))
        # This snapshot validates the frozen v0.14 rendering API; the
        # interactive window now deliberately provides a different,
        # orientation-correct, high-DPI print export with a size dialog.
        from geostudio.exporters import render_scene_image, save_image
        source = render_scene_image(window.map_scene)
        if source is not None:
            save_image(source, target)
        result["image" + suffix] = (
            _image_facts(target) if target.exists()
            else {"created": False, "status": window.status.currentMessage()}
        )

    target = outdir / "export.dxf"
    _save_with(str(target))
    window.export_dxf()
    result["dxf"] = (_dxf_structure(target) if target.exists()
                     else {"created": False, "status": window.status.currentMessage()})
    return result


def _qt_version() -> str:
    from PySide6 import __version__ as pyside
    from PySide6.QtCore import qVersion
    return f"PySide6 {pyside} / Qt {qVersion()}"


def snapshot_json(window: GeoStudioWindow, outdir: Path) -> str:
    return json.dumps(run_exports(window, outdir), indent=1, sort_keys=True,
                      ensure_ascii=False)
