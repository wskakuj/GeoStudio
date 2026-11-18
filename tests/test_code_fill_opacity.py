"""The Contents pane controls the alpha of whole GEO-MAP codes, not MAP data."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")

from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import QApplication

from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from geostudio.scene_builder import RenderContext, object_fill_brush
from geostudio.visual_styles import validated_styles, write_styles, load_styles
from test_geomap import fixture_map


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _map_with_native_fills():
    doc = GeoMap(fixture_map())
    a = doc.append_polygon([(2, 2), (5, 2), (5, 5)], "5310", fields={"A1": "y"})
    b = doc.append_polygon([(7, 2), (10, 2), (10, 5)], "5216", fields={"A2": "dzialka"})
    # A source style with an explicit nonzero COLORREF. Do not change source.
    for obj in doc.objects:
        obj.style = "8553090 15 255"
    return doc, a, b


def test_renderer_preserves_native_color_and_adapts_alpha_under_orthophoto():
    doc, a, b = _map_with_native_fills()
    obj = doc.by_id[a]
    plain = object_fill_brush(obj, RenderContext(default_fill_opacity=100))
    over_wms = object_fill_brush(obj, RenderContext(default_fill_opacity=60))
    assert plain.color().alpha() == 255
    assert over_wms.color().alpha() == round(.6 * 255)
    assert plain.color().red() == over_wms.color().red()
    assert plain.color().green() == over_wms.color().green()


def test_uid_override_remains_higher_priority_than_code_style():
    doc, a, b = _map_with_native_fills()
    ctx = RenderContext(
        default_fill_opacity=60,
        visual_styles={
            "code:5310": {"opacity": 35, "fill": "#008800"},
            a: {"opacity": 75, "fill": "#FF0000"},
        })
    assert object_fill_brush(doc.by_id[a], ctx).color().alpha() == round(.75 * 255)
    assert object_fill_brush(doc.by_id[a], ctx).color().name() == "#ff0000"
    ctx.visual_styles.pop(a)
    assert object_fill_brush(doc.by_id[a], ctx).color().alpha() == round(.35 * 255)
    assert object_fill_brush(doc.by_id[a], ctx).color().name() == "#008800"
    assert object_fill_brush(doc.by_id[b], ctx).color().alpha() == round(.6 * 255)


def test_code_settings_survive_sidecar_validation(tmp_path):
    map_path = tmp_path / "sample.MAP"
    map_path.write_bytes(fixture_map())
    original = map_path.read_bytes()
    styles = {"code:5310": {"opacity": 42},
              "code:5216": {"opacity": 70, "fill": "#C0A0FF"},
              "DEMO-01": {"opacity": 26, "fill": "#00BB33"}}
    assert validated_styles(styles) == styles
    write_styles(map_path, styles)
    assert load_styles(map_path) == styles
    assert map_path.read_bytes() == original


def test_window_adapts_opaque_fills_when_wms_appears_and_disappears(app):
    win = GeoStudioWindow()
    try:
        win.doc, a, b = _map_with_native_fills()
        win.rebuild_scene(fit=False)
        item = win.fill_items_for_uid[a]
        assert item.brush().color().alpha() == 255
        pixmap = QPixmap(10, 10)
        pixmap.fill(QColor("#aabbcc"))
        win._wms_preview.image = pixmap
        win._refresh_fill_brushes()
        assert item.brush().color().alpha() == round(.6 * 255)
        assert win._default_fill_opacity() == 60
        win._wms_preview.image = None
        win._refresh_fill_brushes()
        assert item.brush().color().alpha() == 255
    finally:
        win.close()


def test_one_code_changes_live_without_scene_rebuild_or_map_edit(app, monkeypatch):
    win = GeoStudioWindow()
    try:
        doc, a, b = _map_with_native_fills()
        win.doc = doc
        win.rebuild_scene(fit=False)
        original = doc.to_bytes()
        a_item = win.fill_items_for_uid[a]
        b_item = win.fill_items_for_uid[b]
        index = win.layer_code_choice.findData("5310")
        assert index >= 0
        win.layer_code_choice.setCurrentIndex(index)
        monkeypatch.setattr(win, "rebuild_scene", lambda **kw:
                            pytest.fail("An opacity-only change rebuilt the scene"))
        monkeypatch.setattr(win, "_autosave_work_copy", lambda: None)
        win.layer_code_opacity.setValue(37)
        win._commit_code_opacity()
        assert win.visual_styles["code:5310"]["opacity"] == 37
        assert a_item.brush().color().alpha() == round(.37 * 255)
        assert b_item.brush().color().alpha() == 255
        assert win.doc.to_bytes() == original
        assert win.history.is_dirty
    finally:
        win.close()
