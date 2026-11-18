"""Frozen copy of the export code as it stood before ``exporters.py``.

This module exists only for tests. It is a verbatim snapshot of the two
methods that were moved, with the file dialogs removed, so a test can run the
old and the new implementation in the same process and compare their output
byte for byte. That comparison is the real proof that the extraction changed
nothing: it does not depend on the Qt build, the platform or antialiasing
details of the machine running the tests.

Do not "improve" this file. Its value is that it stays frozen.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from geostudio.geomap import resolve_layer


def legacy_export_image(scene, file: str | Path) -> None:
    """The body of GeoStudioWindow.export_image from v0.14.0, minus the dialog."""
    rect = scene.itemsBoundingRect()
    if rect.isEmpty():
        return
    width = 2600
    height = max(400, min(5000, round(width * rect.height() / max(rect.width(), 1))))
    img = QImage(width, height, QImage.Format_RGB32)
    img.fill(QColor('white'))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    scene.render(painter, QRectF(0, 0, width, height), rect, Qt.KeepAspectRatio)
    painter.end()
    if not img.save(str(file)):
        raise RuntimeError('Format niedostępny w tej instalacji Qt; wybierz PNG/JPG.')


def legacy_export_dxf(doc, catalog, file: str | Path) -> None:
    """The body of GeoStudioWindow.export_dxf from v0.14.0, minus the dialogs."""
    import ezdxf

    d = ezdxf.new('R2010', setup=True)
    model = d.modelspace()
    for obj in doc.objects:
        if not obj.points:
            continue
        layer = resolve_layer(catalog, obj.code)
        layer = ''.join(c if c not in '<>/\\":;?*|,=' else '_' for c in layer)[:100]
        if layer not in d.layers:
            d.layers.new(name=layer)
        vertices = [(p.x, p.y) for p in obj.points]
        if len(vertices) > 1:
            model.add_lwpolyline(vertices, dxfattribs={'layer': layer})
        else:
            model.add_point(vertices[0], dxfattribs={'layer': layer})
    d.saveas(str(file))
