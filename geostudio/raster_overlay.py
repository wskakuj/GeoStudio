"""Raster underlays for the Qt map scene, with independent project sidecar.

Only image paths, GCPs and visual settings are stored here. Never modifies the
source GEO-MAP .MAP, its metadata, or GEO-MAP object/selection state.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene

from .raster_georef import GroundControlPoint, parse_world_file, find_world_file

MAX_SIDECAR_BYTES = 1_000_000
SIDECAR_VERSION = 1


def scene_transform(coefficients: tuple[float, float, float, float, float, float]) -> QTransform:
    """Pixel (u,v) → Qt scene (X,-Y), matching the existing GEO-MAP renderer."""
    a, b, c, d, e, f = coefficients
    if not all(math.isfinite(v) for v in coefficients):
        raise ValueError("Raster: nieprawidłowa macierz transformacji.")
    return QTransform(a, -d, b, -e, c, -f)


def raster_sidecar(map_path: str | Path) -> Path:
    return Path(str(map_path) + ".geostudio.rasters.json")


@dataclass
class RasterLayer:
    uid: str
    path: Path
    coefficients: tuple[float, float, float, float, float, float] | None = None
    gcps: list[GroundControlPoint] = field(default_factory=list)
    opacity: float = 0.6
    visible: bool = True
    item: QGraphicsPixmapItem | None = field(default=None, repr=False)

    @property
    def calibrated(self) -> bool:
        return self.coefficients is not None


class RasterOverlayStore:
    """Recreate all non-selectable pixmaps after each map-scene rebuild."""

    def __init__(self):
        self.layers: list[RasterLayer] = []

    def clear_items(self):
        # QGraphicsScene.clear() destroys all C++ graphics objects; discard
        # Python wrappers before rebuilding a fresh pixmap for each layer.
        for layer in self.layers:
            layer.item = None

    def clear(self):
        self.clear_items()
        self.layers.clear()

    def add(self, image: str | Path) -> RasterLayer:
        image_path = Path(image).expanduser().resolve()
        pixmap = QPixmap(str(image_path))
        if pixmap.isNull():
            raise ValueError("Nie można wczytać obrazu. Sprawdź format i dostępne kodeki Qt.")
        world = find_world_file(image_path)
        coefficients = parse_world_file(world) if world else None
        layer = RasterLayer(str(uuid4()), image_path, coefficients)
        self.layers.append(layer)
        return layer

    def by_id(self, uid: str) -> RasterLayer:
        for layer in self.layers:
            if layer.uid == uid:
                return layer
        raise KeyError(uid)

    def remove(self, uid: str, scene: QGraphicsScene | None = None):
        layer = self.by_id(uid)
        if scene is not None and layer.item is not None:
            scene.removeItem(layer.item)
        self.layers.remove(layer)

    def attach(self, scene: QGraphicsScene):
        """Add raster beneath every vector; never intercept map clicks."""
        # Refreshing a calibration is different from build_scene().clear():
        # remove the previous live underlay, otherwise each Apply adds another
        # full raster to the scene and darkens the map.
        for layer in self.layers:
            if layer.item is not None:
                try:
                    if layer.item.scene() is scene:
                        scene.removeItem(layer.item)
                except RuntimeError:
                    pass  # The C++ item was already deleted by scene.clear().
                layer.item = None
        for order, layer in enumerate(self.layers):
            if not layer.calibrated:
                continue
            pixmap = QPixmap(str(layer.path))
            if pixmap.isNull():
                continue
            item = QGraphicsPixmapItem(pixmap)
            item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
            item.setTransform(scene_transform(layer.coefficients))
            item.setZValue(-100_000 + order)
            item.setOpacity(max(0., min(1., layer.opacity)))
            item.setVisible(layer.visible)
            item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, False)
            scene.addItem(item)
            layer.item = item

    def update_layer(self, layer: RasterLayer):
        item = layer.item
        if item is None:
            return
        if layer.coefficients is not None:
            item.setTransform(scene_transform(layer.coefficients))
        item.setOpacity(max(0., min(1., layer.opacity)))
        item.setVisible(layer.visible)

    def save(self, map_path: str | Path) -> Path:
        """Atomically write *only* the GeoStudio raster sidecar, never .MAP."""
        target = raster_sidecar(map_path)
        folder = Path(map_path).parent.resolve()
        records = []
        for layer in self.layers:
            records.append({
                "id": layer.uid,
                "path": os.path.relpath(layer.path, folder),
                "coefficients": list(layer.coefficients) if layer.coefficients else None,
                "gcps": [[p.u, p.v, p.x, p.y] for p in layer.gcps],
                "opacity": layer.opacity,
                "visible": layer.visible,
            })
        payload = json.dumps({"version": SIDECAR_VERSION, "rasters": records},
                             ensure_ascii=False, indent=2)
        descriptor, name = tempfile.mkstemp(prefix=".geostudio-raster-", suffix=".tmp",
                                           dir=str(folder))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, target)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return target

    def load(self, map_path: str | Path) -> int:
        """Load references from a bounded JSON project sidecar.

        Missing images are skipped rather than preventing the .MAP opening.
        """
        self.clear()
        file = raster_sidecar(map_path)
        if not file.is_file():
            return 0
        if file.stat().st_size > MAX_SIDECAR_BYTES:
            raise ValueError("Zbyt duży plik ustawień rastrów GeoStudio.")
        data = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != SIDECAR_VERSION:
            raise ValueError("Nieobsługiwana wersja ustawień rastra.")
        records = data.get("rasters", [])
        if not isinstance(records, list) or len(records) > 128:
            raise ValueError("Nieprawidłowa lista podkładów rastrowych.")
        for row in records:
            if not isinstance(row, dict):
                continue
            path = Path(str(row.get("path", "")))
            path = (path if path.is_absolute() else file.parent / path).resolve()
            if not path.is_file():
                continue
            if QPixmap(str(path)).isNull():
                continue
            values = row.get("coefficients")
            if values is not None:
                if not isinstance(values, list) or len(values) != 6:
                    continue
                coefficients = tuple(float(v) for v in values)
                scene_transform(coefficients)
            else:
                coefficients = None
            pairs = []
            for coords in row.get("gcps", []):
                if len(coords) == 4:
                    pairs.append(GroundControlPoint(*(float(v) for v in coords)))
            opacity = float(row.get("opacity", 0.6))
            if not math.isfinite(opacity):
                opacity = 0.6
            self.layers.append(RasterLayer(
                uid=str(row.get("id") or uuid4()), path=path,
                coefficients=coefficients, gcps=pairs,
                opacity=max(0., min(1., opacity)),
                visible=bool(row.get("visible", True))))
        return len(self.layers)
