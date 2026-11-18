"""File exporters: rendered map images and DXF.

Everything here writes files and nothing here talks to the user: dialogs,
status messages and error boxes stay in the window. Sizes, colours, layer
naming and entity order are exactly what the window produced before this
module existed — the extraction is mechanical.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform

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


MAX_PRINT_PIXELS = 120_000_000


def render_print_image(scene, orientation: QTransform, *, width: int = 10000,
                       progress=None) -> QImage | None:
    """Rasterize the full map using the SAME orientation as the Qt map view.

    Scene XY coordinates are GEO-MAP technical axes and not page axes.
    Rendering scene.render() directly caused a diagonal mirror on exports.
    The normalized view transform corrects that without changing stored
    coordinates, and the output width refers to the final oriented page.

    A pixel budget guards against Qt allocations that could exhaust RAM.
    """
    from math import hypot, isfinite

    bounds = scene.itemsBoundingRect()
    if bounds.isEmpty():
        return None
    if width < 1000 or width > 20000:
        raise ValueError("Rozdzielczość eksportu: 1000–20000 pikseli szerokości.")
    zoom = hypot(orientation.m11(), orientation.m12())
    if not isfinite(zoom) or zoom < 1e-10:
        raise ValueError("Nieprawidłowa orientacja mapy.")
    matrix = QTransform(
        orientation.m11() / zoom, orientation.m12() / zoom,
        orientation.m21() / zoom, orientation.m22() / zoom, 0, 0)
    oriented = matrix.mapRect(bounds)
    if oriented.isEmpty():
        return None
    # Preserve square map units in both axes; no 5000px height clamp.
    factor = width / oriented.width()
    final_height = max(1, round(oriented.height() * factor))
    raw_width = max(1, round(bounds.width() * factor))
    raw_height = max(1, round(bounds.height() * factor))
    pixels = max(raw_width * raw_height, width * final_height)
    if pixels > MAX_PRINT_PIXELS:
        raise ValueError(
            f"Eksport wymaga około {pixels/1_000_000:.0f} mln pikseli. "
            "Zmniejsz szerokość lub wybierz fragment mapy. "
            "Limit ochrony pamięci: 120 mln pikseli.")
    if progress:
        progress(15, "Przygotowywanie obrazu mapy…")
    image = QImage(raw_width, raw_height, QImage.Format_ARGB32_Premultiplied)
    if image.isNull():
        raise MemoryError("Nie udało się przydzielić pamięci na obraz mapy.")
    image.fill(QColor("white"))
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if progress:
            progress(30, "Rysowanie elementów mapy w wysokiej rozdzielczości…")
        scene.render(painter, QRectF(0, 0, raw_width, raw_height),
                     bounds, Qt.KeepAspectRatio)
    finally:
        painter.end()
    if progress:
        progress(72, "Korygowanie orientacji i odbicia lustrzanego…")
    oriented_image = image.transformed(
        matrix, Qt.SmoothTransformation)
    del image
    if oriented_image.isNull():
        raise MemoryError("Nie udało się obrócić obrazu eksportu.")
    if oriented_image.width() != width or oriented_image.height() != final_height:
        # QTransform rounding can differ by a pixel; compose onto exact page.
        result = QImage(width, final_height, QImage.Format_RGB32)
        result.fill(QColor("white"))
        qp = QPainter(result)
        qp.setRenderHint(QPainter.SmoothPixmapTransform)
        qp.drawImage(QRectF(0, 0, width, final_height),
                     oriented_image, QRectF(oriented_image.rect()))
        qp.end()
    else:
        result = oriented_image.convertToFormat(QImage.Format_RGB32)
    # 300 DPI print metadata, without pretending it increases real detail.
    dots_per_metre = round(300 / 0.0254)
    result.setDotsPerMeterX(dots_per_metre)
    result.setDotsPerMeterY(dots_per_metre)
    return result


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
