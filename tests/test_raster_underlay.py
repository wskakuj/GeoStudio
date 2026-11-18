"""Raster underlay, calibration and UI integration regression tests."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsPixmapItem

from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from geostudio.raster_overlay import RasterOverlayStore, raster_sidecar
from geostudio.raster_georef import GroundControlPoint, fit_affine
from geostudio.raster_ui import RasterCalibrationDialog
from test_geomap import fixture_map


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def image(tmp_path, app):
    path = tmp_path / "scan.png"
    raster = QImage(140, 110, QImage.Format.Format_RGB32)
    raster.fill(QColor("#c3d3e2"))
    assert raster.save(str(path))
    return path


def _gcps():
    samples = [(0, 0), (100, 0), (0, 100),
               (100, 100), (50, 30), (40, 85), (75, 62)]
    return [GroundControlPoint(u, v, 10 + u * 2, 20 + v * -2)
            for u, v in samples]


def test_underlay_is_below_vectors_and_noninteractive(image, app):
    store = RasterOverlayStore()
    layer = store.add(image)
    layer.coefficients = fit_affine(_gcps()).coefficients
    scene = QGraphicsScene()
    vector = scene.addRect(10, -20, 10, 10)
    assert vector.zValue() == 0
    store.attach(scene)
    assert layer.item is not None
    assert isinstance(layer.item, QGraphicsPixmapItem)
    assert layer.item.zValue() < vector.zValue()
    assert layer.item.acceptedMouseButtons() == Qt.MouseButton.NoButton
    assert layer.item.opacity() == pytest.approx(0.6)
    world = layer.item.mapToScene(0, 0)
    assert world.x() == pytest.approx(10)
    assert world.y() == pytest.approx(-20)


def test_raster_sidecar_round_trip_preserves_original_map(image, tmp_path, app):
    path = tmp_path / "source.MAP"
    original = fixture_map()
    path.write_bytes(original)
    first = RasterOverlayStore()
    raster = first.add(image)
    raster.gcps = _gcps()
    raster.coefficients = fit_affine(raster.gcps).coefficients
    raster.opacity = 0.4
    raster.visible = False
    saved = first.save(path)
    assert saved == raster_sidecar(path)
    assert path.read_bytes() == original
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert not os.path.isabs(data["rasters"][0]["path"])
    second = RasterOverlayStore()
    assert second.load(path) == 1
    again = second.layers[0]
    assert again.path == image
    assert again.coefficients == raster.coefficients
    assert again.gcps == raster.gcps
    assert again.opacity == pytest.approx(0.4)
    assert again.visible is False
    assert path.read_bytes() == original


def test_scene_rebuild_keeps_raster_under_map_and_source_bytes(image, app):
    window = GeoStudioWindow()
    try:
        window.doc = GeoMap(fixture_map())
        source_bytes = window.doc.to_bytes()
        layer = window._raster_overlay.add(image)
        layer.coefficients = fit_affine(_gcps()).coefficients
        window.rebuild_scene(fit=False)
        assert layer.item is not None
        old_item = layer.item
        count = len(window.map_scene.items())
        window.rebuild_scene(fit=False)
        assert layer.item is not old_item
        assert layer.item.zValue() < min(
            item.zValue() for item in window.graphics_for_uid.values())
        assert len(window.map_scene.items()) == count
        assert window.doc.to_bytes() == source_bytes
        assert window.history.is_dirty is False
    finally:
        window.close()


def test_map_point_capture_does_not_select_or_edit_map(image, app):
    window = GeoStudioWindow()
    try:
        window.doc = GeoMap(fixture_map())
        window.rebuild_scene(fit=False)
        source = window.doc.to_bytes()
        layer = window._raster_overlay.add(image)
        dialog = RasterCalibrationDialog(window, layer)
        window._raster_calibration_dialog = dialog
        dialog._pixel_clicked(22.0, 33.0)
        dialog.request_map_click()
        assert window._raster_map_picker is not None
        window.select_at(50, 60)
        assert window._raster_map_picker is None
        assert len(dialog.points) == 1
        assert dialog.points[0] == GroundControlPoint(22, 33, 50, 60)
        assert window.doc.to_bytes() == source
        dialog.close()
    finally:
        window.close()


def test_invalid_sidecar_is_rejected_without_touching_map(image, tmp_path, app):
    source = tmp_path / "source.MAP"
    source.write_bytes(fixture_map())
    sidecar = raster_sidecar(source)
    sidecar.write_text('{"version": 200, "rasters": []}')
    store = RasterOverlayStore()
    with pytest.raises(ValueError):
        store.load(source)
    assert source.read_bytes() == fixture_map()
