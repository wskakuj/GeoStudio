"""Modern map furniture, print orientation, WMS sources and label regression tests."""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QTransform, QBrush, QPen
from PySide6.QtWidgets import QApplication, QGraphicsScene, QMessageBox, QInputDialog

from conftest import MapBuilder
from geostudio.app import GeoStudioWindow
from geostudio.exporters import render_print_image, MAX_PRINT_PIXELS
from geostudio.geomap import GeoMap
from geostudio.label_editor import ATTRIBUTE_FIELDS, AttributeLabelsDialog
from geostudio.map_decorations import DecorationItem, new_decoration
from geostudio.visual_styles import load_styles, write_styles
from geostudio.wms_qt import WMSDialog


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch):
    data = (MapBuilder(ext=(1000, 0, 0, 250, 250))
            .object("5310", "A", {"A1": "a", "A2": "B", "A3": "Opis 1"},
                    [(0, 0), (20, 0), (20, 20), (0, 20)])
            .object("5310", "B", {"A1": "a", "A2": "C", "A3": "Opis 2"},
                    [(30, 0), (50, 0), (50, 20), (30, 20)])
            .build())
    w = GeoStudioWindow()
    w.doc = GeoMap(data)
    w.catalog = {"5310": "Budynki"}
    w.rebuild_scene(fit=False)
    monkeypatch.setattr(w, "_autosave_work_copy", lambda: None)
    yield w
    w.close()


def test_print_orientation_is_not_raw_scene_orientation(app):
    scene = QGraphicsScene()
    scene.addRect(QRectF(0, 0, 100, 40), QPen(Qt.NoPen), QBrush(QColor("white")))
    scene.addRect(QRectF(0, 0, 12, 12), QPen(Qt.NoPen), QBrush(QColor("#FF0000")))
    raw = render_print_image(scene, QTransform(), width=1000)
    geodetic = render_print_image(scene, QTransform(0.0, -1.0, -1.0, 0.0, 0.0, 0.0), width=1000)
    assert raw.width() == 1000
    assert raw.height() < raw.width()
    assert geodetic.width() == 1000
    assert geodetic.height() > geodetic.width()
    # Technical top-left goes to geodetic bottom-right after axis swap.
    assert geodetic.pixelColor(950, geodetic.height() - 80).red() > 180
    assert geodetic.pixelColor(50, 50).red() == 255


def test_print_export_rejects_huge_raster_without_allocating(app):
    scene = QGraphicsScene()
    scene.addRect(0, 0, 100, 100)
    with pytest.raises(ValueError, match="Limit ochrony pamięci"):
        render_print_image(scene, QTransform(), width=20000)


def test_modern_compass_resizes_without_background_and_keeps_legend_rows(app, tmp_path):
    uid, data = new_decoration("north", 100, 200)
    assert data["scale"] == 1.0
    scene = QGraphicsScene()
    item = DecorationItem(uid, data, 1.0, on_move=lambda *a: None,
                          on_edit=lambda *a: None, on_resize=lambda *a: None)
    scene.addItem(item)
    assert item.boundingRect().width() > 180
    item.setScale(2)
    assert item.scale() == 2
    assert scene.itemsBoundingRect().width() > 360
    uid2, legend = new_decoration("legend", 120, 200)
    legend["items"].extend(
        {"name": f"Pozycja {index}", "color": "#CCAABB"} for index in range(12))
    legend["scale"] = 2.5
    map_file = tmp_path / "EXAMPLE.MAP"
    map_file.write_bytes(b"test")
    write_styles(map_file, {uid: data, uid2: legend})
    saved = load_styles(map_file)[uid2]
    assert len(saved["items"]) == 19
    assert saved["items"][11]["color"] == "#CCAABB"
    assert saved["scale"] == 2.5
    large = DecorationItem(uid2, saved, 1.0, on_move=lambda *a: None,
                           on_edit=lambda *a: None)
    assert large.boundingRect().height() > 500


def test_wms_presets_are_real_services_and_smartsdi_not_network_wms(window, monkeypatch):
    dlg = WMSDialog(window)
    try:
        high = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/HighResolution"
        assert dlg.server_selector.findData(high) >= 0
        dlg.server_selector.setCurrentIndex(dlg.server_selector.findData(high))
        assert dlg.address.text() == high
        dlg.server_selector.setCurrentIndex(dlg.server_selector.findData("smartsdi"))
        assert not dlg.address.isEnabled()
        assert not dlg.capabilities_button.isEnabled()
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a: None))
        dlg.fetch_layers()
        assert dlg.pending is None
    finally:
        dlg.close()


def test_layer_bulk_attribute_replacement_is_atomic(window, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getItem",
                        staticmethod(lambda *a, **k: ("A1", True)))
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("nowe", True)))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    before = window.doc.to_bytes()
    window.bulk_edit_layer_field("Budynki", window._objects_in_layer("Budynki"))
    assert window.doc.by_id["A"].fields["A1"] == "nowe"
    assert window.doc.by_id["B"].fields["A1"] == "nowe"
    window.undo_last_edit()
    assert window.doc.to_bytes() == before


def test_any_attribute_can_be_labelled_and_moved(window, monkeypatch):
    from geostudio import app as app_module
    class Accepted:
        def __init__(self, code, current, parent):
            assert code == "5310"
        def exec(self):
            return 1
        def specification(self):
            return {"fields": {"A3": {
                "visible": True, "font": "DejaVu Sans",
                "size": 22, "color": "#123456"}}}
    monkeypatch.setattr(app_module, "AttributeLabelsDialog", Accepted)
    window._select_uid("A")
    window.open_attribute_label_dialog()
    label = window.label_items[("A", "A3")]
    assert label.font().pixelSize() == 22
    assert label.brush().color().name() == "#123456"
    assert ("A", "A1") not in window.label_items
    assert ("A", "A2") not in window.label_items
    window.start_label_edit()
    p = label.pos()
    screen = label.deviceTransform(window.view.viewportTransform()).mapRect(
        label.boundingRect()).center().toPoint()
    pt = window.view.mapToScene(screen)
    window.begin_label_drag(pt.x(), -pt.y())
    assert window._active_label is label
    window.move_label(p.x() + 1, -p.y() + 2)
    window.end_label_drag(p.x() + 1, -p.y() + 2)
    assert window.label_positions["A"]["A3"] == [round(p.x() + 1, 3), round(-p.y() + 2, 3)]
