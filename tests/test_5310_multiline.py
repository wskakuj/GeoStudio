"""5310 annotations keep GEO-MAP's stacked A2 rows without altering source MAP."""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsTextItem

from geostudio.geomap import GeoMap
from geostudio.scene_builder import RenderContext, build_scene
from test_geomap import fixture_map


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_5310_pipe_separates_stacked_a2_lines_without_editing_map_bytes(qt_app):
    doc = GeoMap(fixture_map())
    uid = doc.append_polygon([(4, 4), (8, 4), (8, 8)],
                             '5310', fields={'A1': 'y', 'A2': 'Ol75|II-0.5'})
    before = doc.to_bytes()
    scene = QGraphicsScene()  # Keep Qt owner alive while inspecting labels.
    result = build_scene(scene, doc, RenderContext())
    label = result.label_items[(uid, 'A2')]
    assert isinstance(label, QGraphicsTextItem)
    assert label.toPlainText() == 'Ol75\nII-0.5'
    assert label.data(0) == uid
    assert label.data(1) == 'A2'  # One draggable field, not two orphan pieces.
    assert [(item.data(1)) for item in result.labels if item.data(0) == uid] == ['A1', 'A2']
    assert doc.by_id[uid].fields['A2'] == 'Ol75|II-0.5'
    assert doc.to_bytes() == before
    assert b':A2[Ol75|II-0.5]' in before


def test_non_multiline_building_a2_remains_legacy_simple_text(qt_app):
    doc = GeoMap(fixture_map())
    uid = doc.append_polygon([(4, 4), (8, 4), (8, 8)],
                             '5310', fields={'A2': 'II-0.5'})
    scene = QGraphicsScene()  # Keep Qt owner alive while inspecting labels.
    result = build_scene(scene, doc, RenderContext())
    assert not isinstance(result.label_items[(uid, 'A2')], QGraphicsTextItem)
    assert result.label_items[(uid, 'A2')].text() == 'II-0.5'
