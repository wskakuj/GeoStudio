"""Regressions: KIEG parcels, bulk styling, inspector state, decoration hits."""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QColorDialog, QInputDialog, QGraphicsScene

from conftest import MapBuilder
from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from geostudio.label_editor import AttributeLabelsDialog
from geostudio.map_decorations import DecorationItem, new_decoration
from geostudio.visual_styles import load_styles, write_styles
from geostudio.wms_qt import WMSDialog
from geostudio.wms_service import WMSLayerInfo


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch):
    raw = (MapBuilder(ext=(1000, 0, 0, 250, 250))
           .object("5310", "A", {"A1": "a", "A2": "B"},
                   [(0, 0), (20, 0), (20, 20), (0, 20)])
           .object("5310", "B", {"A1": "b", "A2": "C"},
                   [(30, 0), (50, 0), (50, 20), (30, 20)])
           .object("5230", "C", {"A1": "Ls"},
                   [(0, 30), (15, 30), (15, 45), (0, 45)])
           .build())
    w = GeoStudioWindow()
    w.doc = GeoMap(raw)
    w.catalog = {"5310": "Budynki", "5230": "Użytki"}
    w.rebuild_scene(fit=False)
    monkeypatch.setattr(w, "_autosave_work_copy", lambda: None)
    yield w
    w.close()


def test_label_palette_opens_directly_from_color_cell(app, monkeypatch):
    dlg = AttributeLabelsDialog("5310")
    calls = []
    monkeypatch.setattr(QColorDialog, "getColor",
                        staticmethod(lambda *_a, **_kw: calls.append(1) or QColor("#CC2277")))
    try:
        assert dlg.findChild(type(dlg.table.cellWidget(0, 4)), "GeoStudioLabelColor_A1")
        picker = dlg.table.cellWidget(1, 4)
        picker.click()
        assert calls == [1]
        assert dlg.specification()["fields"]["A2"]["color"] == "#CC2277"
        assert dlg.table.verticalHeader().defaultSectionSize() >= 35
        assert not hasattr(dlg, "choose_color")
    finally:
        dlg.close()


def test_inspector_shows_saved_opacity_after_rebuild(window):
    window._select_uid("A")
    window.fill_entry.setText("#AABBCC@35")
    window.opacity_spin.setValue(35)
    window.apply_fill_style()
    assert window.visual_styles["A"]["opacity"] == 35
    assert window.opacity_spin.value() == 35
    window._select_uid("B")
    window._select_uid("A")
    assert window.opacity_spin.value() == 35
    assert window.fill_entry.text().endswith("@35")


def test_code_outline_color_width_applies_and_persists(window, tmp_path):
    window._select_uid("A")
    window.outline_color = QColor("#E91C42")
    window.outline_width.setValue(3.5)
    window.apply_code_outline()
    for uid in ("A", "B"):
        pen = window.graphics_for_uid[uid].pen()
        assert pen.color().name() == "#e91c42"
        assert pen.widthF() == pytest.approx(3.5)
    source = tmp_path / "test.MAP"
    source.write_bytes(window.doc.to_bytes())
    write_styles(source, window.visual_styles)
    assert load_styles(source)["code:5310"]["stroke_width"] == pytest.approx(3.5)
    assert load_styles(source)["code:5310"]["stroke"] == "#E91C42"


def test_bulk_color_ignores_older_feature_override(window, monkeypatch):
    window.visual_styles["A"] = {"fill": "#FF0000", "opacity": 30}
    window.rebuild_scene(fit=False)
    monkeypatch.setattr(QColorDialog, "getColor",
                        staticmethod(lambda *_a, **_k: QColor("#05BD95")))
    monkeypatch.setattr(QInputDialog, "getInt",
                        staticmethod(lambda *_a, **_k: (65, True)))
    before_doc = window.doc.to_bytes()
    objects = window._objects_in_layer("Budynki")
    window.bulk_color_layer("Budynki", objects)
    for uid in ("A", "B"):
        color = window.fill_items_for_uid[uid].brush().color()
        assert color.name() == "#05bd95"
        assert color.alpha() == round(65 * 255 / 100)
    assert window.visual_styles["code:5310"]["force_fill"] is True
    assert window.doc.to_bytes() == before_doc
    window._select_uid("A")
    assert window.opacity_spin.value() == 65
    window.undo_last_edit()
    assert "code:5310" not in window.visual_styles


def test_kieg_wms_combines_parcel_boundaries_and_numbers(window, monkeypatch):
    dlg = WMSDialog(window)
    try:
        kieg = "https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow"
        dlg.server_selector.setCurrentIndex(dlg.server_selector.findData(kieg))
        assert dlg.address.text() == kieg
        assert dlg.opacity.value() == 100
        layers = (
            WMSLayerInfo("dzialki", "Działki ewidencyjne", ("EPSG:2180",)),
            WMSLayerInfo("numery_dzialek", "Numery działek", ("EPSG:2180",)),
        )
        monkeypatch.setattr("geostudio.wms_qt.parse_capabilities",
                            lambda _: layers)
        monkeypatch.setattr(dlg, "_request",
                            lambda _url, received, **_kwargs: received(b"test"))
        dlg.fetch_layers()
        assert dlg.layer_selector.currentData() == "dzialki,numery_dzialek"
        assert dlg.layer_selector.itemText(0).startswith("Działki i numery")
        index = dlg.crs_selector.findData(2180)
        assert index >= 0
        dlg.crs_selector.setCurrentIndex(index)
        sources = []
        monkeypatch.setattr(window._wms_auto, "configure", sources.append)
        dlg.fetch_map()
        assert sources and sources[-1].layer == "dzialki,numery_dzialek"
    finally:
        dlg.close()


def test_layout_empty_space_does_not_steal_clicks_and_no_group_selection(app):
    uid, meta = new_decoration("title", 120, 120)
    item = DecorationItem(uid, meta, 1.0,
                          on_move=lambda *_: None, on_edit=lambda *_: None)
    scene = QGraphicsScene()
    scene.addItem(item)
    assert item.boundingRect().contains(QPointF(400, 160))
    assert not item.shape().contains(QPointF(400, 160))
    assert item.shape().contains(QPointF(25, 10))
    uid2, title2 = new_decoration("credits", 125, 130)
    item2 = DecorationItem(uid2, title2, 1.0,
                           on_move=lambda *_: None, on_edit=lambda *_: None)
    scene.addItem(item2)
    assert not item2.shape().contains(QPointF(400, 160))
    uid3, legend = new_decoration("legend", 140, 120)
    legend["items"] = [{"name": "Element " + str(i), "color": "#BADA55"}
                       for i in range(43)]
    legend_item = DecorationItem(uid3, legend, 1.0,
                                 on_move=lambda *_: None, on_edit=lambda *_: None)
    assert legend_item.boundingRect().width() > 1000
    assert legend_item.boundingRect().height() <= 510
    assert legend_item.shape().contains(QPointF(15, 99))
    assert legend_item.shape().contains(QPointF(745, 110))
    assert not legend_item.shape().contains(QPointF(300, 170))


def test_new_legend_uses_actual_map_layers_instead_of_seven_samples(window):
    window.insert_map_decoration("legend", x=170, y=170)
    key = next(k for k in window.visual_styles if k.startswith("layout:"))
    entries = window.visual_styles[key]["items"]
    labels = [item["name"] for item in entries]
    assert any("5310" in label for label in labels)
    assert any("5230" in label for label in labels)
    assert not any(label == "Sosna i modrzew" for label in labels)
