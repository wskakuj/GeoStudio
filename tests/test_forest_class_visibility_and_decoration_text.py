"""Forest-class UI + drawing regressions from user screenshots (Nov 2026)."""
from __future__ import annotations

import os
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
pytest.importorskip("PySide6")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtWidgets import QApplication, QGraphicsScene, QMenu

from conftest import MapBuilder
from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from geostudio.forest_classes import (
    FOREST_LAYER, FILTER_KEY, forest_class_value, forest_hidden_classes,
)
from geostudio.map_decorations import DecorationItem, new_decoration
from geostudio.visual_styles import write_styles, load_styles


@pytest.fixture(scope="module")
def qt():
    return QApplication.instance() or QApplication([])


def source_bytes():
    return (MapBuilder(ext=(1000, 0, 0, 500, 500))
            .object("5230", "FOREST", {"A1": "Ls", "A2": "Ls"}, 
                    [(10, 10), (20, 10), (20, 20), (10, 20)])
            .object("5230", "GRADE5", {"A1": "LsV", "A2": "LsV"}, 
                    [(45, 10), (55, 10), (55, 20), (45, 20)])
            .object("5230", "GRADE6", {"A1": "LsVI", "A2": "LsVI"}, 
                    [(80, 10), (90, 10), (90, 20), (80, 20)])
            .object("5230", "ROAD", {"A1": "dr", "A2": "droga"}, 
                    [(115, 10), (125, 10), (125, 20), (115, 20)])
            .object("5310", "BUILDING", {"A1": "b", "A2": "B"}, 
                    [(150, 10), (160, 10), (160, 20), (150, 20)])
            .build())


@pytest.fixture
def window(qt, monkeypatch):
    win = GeoStudioWindow()
    win.doc = GeoMap(source_bytes())
    win.catalog = {"5230": "Użytki", "5310": "Budynki"}
    win.rebuild_scene(fit=False)
    monkeypatch.setattr(win, "_autosave_work_copy", lambda: None)
    yield win
    win.close()


def test_forest_group_contains_all_Ls_grades_but_not_roads(window):
    for uid in ("FOREST", "GRADE5", "GRADE6"):
        assert window.layer_for_uid[uid] == FOREST_LAYER
    assert window.layer_for_uid["ROAD"] == "Użytki"
    assert window.layer_for_uid["BUILDING"] == "Budynki"
    names = {window.layers_tree.topLevelItem(i).text(0)
             for i in range(window.layers_tree.topLevelItemCount())}
    assert FOREST_LAYER in names
    assert "Użytki" in names
    assert window._forest_class_counts() == {"Ls": 1, "LsV": 1, "LsVI": 1}


def test_forest_class_filter_is_per_grade_and_hides_geometries_labels_picks_snap(
        window, tmp_path):
    unchanged = window.doc.to_bytes()
    window.set_forest_class_visible("LsV", False)
    assert not window.graphics_for_uid["GRADE5"].isVisible()
    assert not window.fill_items_for_uid["GRADE5"].isVisible()
    assert window.graphics_for_uid["FOREST"].isVisible()
    assert window.graphics_for_uid["GRADE6"].isVisible()
    assert window.graphics_for_uid["ROAD"].isVisible()
    assert "GRADE5" not in window._visible_uids()
    assert "GRADE6" in window._visible_uids()
    assert not window._pick_candidates(50, 15)
    assert all(value.uid != "GRADE5" for value in
               [window._snap(45, 10)] if value is not None)
    assert window.doc.to_bytes() == unchanged

    outfile = tmp_path / "forest.MAP"
    outfile.write_bytes(unchanged)
    write_styles(outfile, window.visual_styles)
    assert load_styles(outfile)[FILTER_KEY] == {"hidden": ["LsV"]}
    window._set_all_layers_visible(False)
    window._set_all_layers_visible(True)
    assert not window.graphics_for_uid["GRADE5"].isVisible()
    window.undo_last_edit()
    assert "LsV" not in forest_hidden_classes(window.visual_styles)
    assert window.graphics_for_uid["GRADE5"].isVisible()


def test_forest_context_menu_contains_checkable_grades(window):
    menu = QMenu()
    class_menu = window._add_forest_class_menu(menu)
    actions = [item for item in class_menu.actions() if item.isCheckable()]
    assert len(actions) == 3
    assert all(action.isChecked() for action in actions)
    assert any(action.text().startswith("LsVI") for action in actions)
    # Qt QAction emits the desired bool; this is the real menu callback.
    grade_v = next(action for action in actions if action.text().startswith("LsV ("))
    grade_v.trigger()
    assert forest_hidden_classes(window.visual_styles) == {"LsV"}
    assert not window.graphics_for_uid["GRADE5"].isVisible()


def _render_decoration(kind, *, details=None, items=None):
    _uid, data = new_decoration(kind, 0, 0)
    if details is not None:
        data["details"] = details
    if items is not None:
        data["items"] = items
    item = DecorationItem(_uid, data, 1.0, on_move=lambda *a: None,
                          on_edit=lambda *a: None)
    img = QImage(1500, 1000, QImage.Format_RGB32)
    img.fill(Qt.white)
    painter = QPainter(img)
    try:
        painter.setRenderHint(QPainter.Antialiasing)
        item.paint(painter, None)
    finally:
        painter.end()
    return item, img


def _ink_count(img, left, top, width, height):
    total = 0
    for y in range(top, top + height):
        for x in range(left, left + width):
            color = img.pixelColor(x, y)
            if color.red() < 225 or color.green() < 225 or color.blue() < 225:
                total += 1
    return total


def test_map_title_and_credits_have_real_body_not_only_headers(qt):
    for kind in ("title", "credits"):
        item, image = _render_decoration(kind)
        assert item.layout_data["details"]
        # Header and subtitle occupy y <= 85; all body text is below 95.
        assert _ink_count(image, 12, 100, 430, 135) > 65, kind
        if kind == "title":
            assert _ink_count(image, 12, 195, 460, 50) > 20


def test_decoration_details_survive_scene_transform_and_render(qt):
    """Regression for screenshots where only the headings were visible."""
    scene = QGraphicsScene()
    uid, info = new_decoration("title", 50, 50)
    info["details"] = "Gmina: Tłuszcz\\nPowiat: wołomiński\\nStan na: 2026"
    item = DecorationItem(uid, info, 1, on_move=lambda *args: None,
                          on_edit=lambda *args: None)
    scene.addItem(item)
    source = item.sceneBoundingRect()
    image = QImage(max(1, int(source.width() * 2)),
                   max(1, int(source.height() * 2)), QImage.Format_RGB32)
    image.fill(Qt.white)
    qp = QPainter(image)
    try:
        scene.render(qp, QRectF(0, 0, image.width(), image.height()),
                     source, Qt.IgnoreAspectRatio)
    finally:
        qp.end()
    # Transform item-local detail bounds into the rendered image coordinates;
    # no reliance on the scene's swapped Y/X geodetic orientation.
    bounds = item.mapRectToScene(QRectF(14, 95, 420, 70))
    px = max(0, round((bounds.left() - source.left()) /
                      source.width() * image.width()))
    py = max(0, round((bounds.top() - source.top()) /
                      source.height() * image.height()))
    right = min(image.width(), round((bounds.right() - source.left()) /
                                    source.width() * image.width()))
    bottom = min(image.height(), round((bounds.bottom() - source.top()) /
                                      source.height() * image.height()))
    assert _ink_count(image, px, py, right-px, bottom-py) > 75


def test_legend_draws_multiple_actual_coloured_rows(qt):
    items = [{"name": "Ls " + str(i), "color": "#BF5511"}
             for i in range(28)]
    item, image = _render_decoration("legend", items=items)
    assert item.boundingRect().width() > 700
    # Paint first column and last entry of the second column.
    for x, y in ((20, 104), (20, 104 + 14*24), (385, 104)):
        color = image.pixelColor(x, y)
        assert color.red() > 130 and 30 < color.green() < 150, (x, y, color.name())
    assert _ink_count(image, 60, 100, 270, 180) > 60
