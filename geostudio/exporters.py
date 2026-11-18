"""File exporters: rendered map images and DXF.

Everything here writes files and nothing here talks to the user: dialogs,
status messages and error boxes stay in the window. Sizes, colours, layer
naming and entity order are exactly what the window produced before this
module existed — the extraction is mechanical.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from .geomap import resolve_layer

# Rendered image width in pixels; height follows the scene aspect ratio but is
# clamped so a degenerate extent cannot produce an unusable file.
IMAGE_WIDTH = 2600
IMAGE_MIN_HEIGHT = 400
IMAGE_MAX_HEIGHT = 5000

# Characters AutoCAD rejects in layer names.
FORBIDDEN_LAYER_CHARS = '<>/\\":;?*|,='
LAYER_NAME_LIMIT = 100


def scene_image_geometry(rect: QRectF, *, width: int = IMAGE_WIDTH) -> tuple[int, int]:
    """Pixel size of the exported image for a scene rectangle."""
    height = max(IMAGE_MIN_HEIGHT,
                 min(IMAGE_MAX_HEIGHT,
                     round(width * rect.height() / max(rect.width(), 1))))
    return width, height


def render_scene_image(scene, *, width: int = IMAGE_WIDTH) -> QImage | None:
    """Render the whole scene to a white-background RGB image.

    Returns None for an empty scene, which is what the caller used to detect
    with ``rect.isEmpty()`` before creating the image.
    """
    rect = scene.itemsBoundingRect()
    if rect.isEmpty():
        return None
    pixel_width, pixel_height = scene_image_geometry(rect, width=width)
    image = QImage(pixel_width, pixel_height, QImage.Format_RGB32)
    image.fill(QColor('white'))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    scene.render(painter, QRectF(0, 0, pixel_width, pixel_height), rect,
                 Qt.KeepAspectRatio)
    painter.end()
    return image


def save_image(image: QImage, path: str | Path) -> bool:
    """Write the image; False means this Qt build cannot write that format."""
    return bool(image.save(str(path)))


def sanitise_layer_name(name: str) -> str:
    """Make a GEO-MAP layer name acceptable to AutoCAD."""
    return ''.join(char if char not in FORBIDDEN_LAYER_CHARS else '_'
                   for char in name)[:LAYER_NAME_LIMIT]


def write_dxf(doc, catalog: dict[str, str], path: str | Path) -> None:
    """Write the simplified DXF: polylines and points, one layer per group.

    Raises ImportError when ezdxf is missing, so the window can keep showing
    its installation hint.
    """
    import ezdxf

    drawing = ezdxf.new('R2010', setup=True)
    model = drawing.modelspace()
    for obj in doc.objects:
        if not obj.points:
            continue
        layer = sanitise_layer_name(resolve_layer(catalog, obj.code))
        if layer not in drawing.layers:
            drawing.layers.new(name=layer)
        vertices = [(point.x, point.y) for point in obj.points]
        if len(vertices) > 1:
            model.add_lwpolyline(vertices, dxfattribs={'layer': layer})
        else:
            model.add_point(vertices[0], dxfattribs={'layer': layer})
    drawing.saveas(str(path))
