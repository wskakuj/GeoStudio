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
    window.catalog = dict(CATALOG)
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
    """Coarse, platform-tolerant description of a rendered image."""
    import numpy as np

    grid_source = _rgb_array(image.scaled(GRID, GRID))
    cells = grid_source.reshape(GRID * GRID, 3).astype(int).tolist()

    background = image.pixelColor(0, 0).name()
    probe = image.scaled(min(image.width(), 512), min(image.height(), 512))
    pixels = _rgb_array(probe).astype(int)
    reference = np.array(image.pixelColor(0, 0).getRgb()[:3], dtype=int)
    mask = np.abs(pixels - reference).sum(axis=2) > 0
    bbox = None
    if mask.any():
        rows, columns = np.nonzero(mask)
        scale_x = image.width() / probe.width()
        scale_y = image.height() / probe.height()
        bbox = [int(round(columns.min() * scale_x)), int(round(rows.min() * scale_y)),
                int(round(columns.max() * scale_x)), int(round(rows.max() * scale_y))]
    return {"grid": cells, "background": background, "contentBox": bbox}


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
        window.export_image()
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
