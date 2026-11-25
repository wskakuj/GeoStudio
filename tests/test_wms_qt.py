"""No-network Qt regression tests for map-service preview and its GIS hooks."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QGraphicsScene

from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from geostudio.wms_qt import WMSDialog, WMSPreviewOverlay, scene_item_transform
from geostudio.wms_service import WMSBounds
from test_geomap import fixture_map


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _transparent_map():
    image = QImage(240, 160, QImage.Format.Format_ARGB32)
    image.fill(QColor("#55af7c"))
    from PySide6.QtCore import QBuffer, QIODevice
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(buffer.data())


def test_wms_graphic_is_below_vectors_and_wms_bounds_match_scene(qt_app):
    scene = QGraphicsScene()
    source_vector = scene.addRect(0, -100, 10, 10)
    bounds = WMSBounds(0, 100, 240, 460)
    overlay = WMSPreviewOverlay()
    overlay.set_image(_transparent_map(), bounds, "Ortofotomapa")
    overlay.attach(scene)
    assert overlay.item is not None
    assert overlay.item.zValue() < source_vector.zValue()
    assert overlay.item.acceptedMouseButtons() == Qt.MouseButton.NoButton
    origin = overlay.item.mapToScene(0, 0)
    bottom_right = overlay.item.mapToScene(240, 160)
    assert origin.x() == pytest.approx(240)
    assert origin.y() == pytest.approx(-100)
    assert bottom_right.x() == pytest.approx(0)
    assert bottom_right.y() == pytest.approx(-460)


def test_reattach_does_not_duplicate_wms_after_preview_refresh(qt_app):
    scene = QGraphicsScene()
    overlay = WMSPreviewOverlay()
    overlay.set_image(_transparent_map(), WMSBounds(0, 0, 240, 360), "WMS")
    overlay.attach(scene)
    count = len(scene.items())
    overlay.attach(scene)
    assert len(scene.items()) == count
    assert overlay.item.opacity() == pytest.approx(0.70)
    overlay.clear(scene)
    assert len(scene.items()) == 0


def test_wms_overlay_survives_vector_scene_rebuild(qt_app):
    window = GeoStudioWindow()
    try:
        window.doc = GeoMap(fixture_map())
        window._wms_preview.set_image(
            _transparent_map(), WMSBounds(0, 0, 240, 360), "WMS test")
        original = window.doc.to_bytes()
        window.rebuild_scene(fit=False)
        assert window._wms_preview.item is not None
        previous = window._wms_preview.item
        window.rebuild_scene(fit=False)
        assert window._wms_preview.item is not previous
        assert window._wms_preview.item.zValue() < 0
        assert window.doc.to_bytes() == original
        assert window.history.is_dirty is False
    finally:
        window.close()


def test_wms_dialog_requires_selected_map_crs_without_network(qt_app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    window = GeoStudioWindow()
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene(fit=False)
    dialog = WMSDialog(window)
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(
        lambda *_args, **_kwargs: messages.append("warning")))
    try:
        dialog.address.setText("https://example.org/wms")
        dialog.layer_selector.addItem("orto", "orto")
        dialog.fetch_map()
        assert messages == ["warning"]
        assert dialog.pending is None
    finally:
        dialog.close()
        window.close()


@pytest.mark.parametrize("last_url,expected_opacity", [
    ("https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow", 100),
    ("https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardResolution", 70),
])
def test_restored_wms_preset_initializes_opacity(
        qt_app, monkeypatch, tmp_path, last_url, expected_opacity):
    """A saved preset must work without another currentIndexChanged signal."""
    settings = QSettings(str(tmp_path / "wms-dialog.ini"), QSettings.Format.IniFormat)
    settings.setValue("wms/last_url", last_url)
    monkeypatch.setattr("geostudio.app.QSettings", lambda *_a, **_kw: settings)
    window = GeoStudioWindow()
    dialog = WMSDialog(window)
    try:
        assert dialog.server_selector.currentData() == last_url
        assert dialog.address.text() == last_url
        assert dialog.opacity.value() == expected_opacity
        # Selecting the restored source again does not emit the signal that
        # normally initializes KIEG opacity when switching sources.
        dialog.server_selector.setCurrentIndex(dialog.server_selector.findData(last_url))
        assert dialog.opacity.value() == expected_opacity
    finally:
        dialog.close()
        window.close()
