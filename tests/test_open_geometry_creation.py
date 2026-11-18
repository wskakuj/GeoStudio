"""Open line / point creation remains experimental and copy-only."""
from __future__ import annotations

import pytest

from geostudio.geomap import GeoMap
from test_geomap import fixture_map


def test_line_5214_ends_open_with_p0_and_preserves_source_bytes():
    doc = GeoMap(fixture_map())
    source = doc.to_bytes()
    uid = doc.append_geometry([(2, 2), (5, 2), (5, 6)],
                              '5214', kind='line', fields={'A3': 'Granica'})
    obj = doc.by_id[uid]
    assert obj.code == '5214'
    assert not obj.is_closed
    assert [(p.x, p.y) for p in obj.points] == [(2, 2), (5, 2), (5, 6)]
    assert [p.point_type for p in obj.points] == [1, 1, 0]
    assert obj.fields['A3'] == 'Granica'
    again = GeoMap(doc.to_bytes())
    assert again.checksum_valid
    assert again.declared_lines == len(again.lines)
    assert source[0:60] != b''  # Source bytes were not mutated by the append.
    assert b':UNKNOWN[retain this]' in again.to_bytes()


def test_text_6900_can_use_two_anchors_and_tx():
    doc = GeoMap(fixture_map())
    uid = doc.append_geometry([(2, 2), (5, 2)], '6900',
                              kind='line', fields={'TX': 'N'})
    result = GeoMap(doc.to_bytes()).by_id[uid]
    assert result.code == '6900'
    assert result.fields['TX'] == 'N'
    assert len(result.points) == 2 and result.points[-1].point_type == 0
    assert not result.is_closed


def test_point_object_can_be_created_without_polygon_closure():
    doc = GeoMap(fixture_map())
    uid = doc.append_geometry([(6, 6)], '5310', kind='point',
                              fields={'A1': 'y', 'A2': 'Ol75|II-0.5'})
    again = GeoMap(doc.to_bytes())
    assert again.checksum_valid
    assert again.by_id[uid].points[0].point_type == 1
    assert len(again.by_id[uid].points) == 1


def test_open_geometry_rejects_invalid_inputs():
    doc = GeoMap(fixture_map())
    with pytest.raises(ValueError):
        doc.append_geometry([(1, 1)], '5214', kind='line')
    with pytest.raises(ValueError):
        doc.append_geometry([(1, 1), (1, 1)], '5214', kind='line')
    with pytest.raises(ValueError):
        doc.append_geometry([(1, 1)], '5214', kind='bad')
    with pytest.raises(ValueError):
        doc.append_geometry([(1, 1)], 'code', kind='point')
    with pytest.raises(ValueError):
        doc.append_geometry([(1, 1)], '6900', kind='point', fields={'TX': 'x\ny'})


def test_new_open_geometry_uses_existing_same_code_style():
    doc = GeoMap(fixture_map())
    original_style = doc.objects[0].style
    uid = doc.append_geometry([(4, 4), (5, 5)], '5216', kind='line')
    assert doc.by_id[uid].style == original_style


def test_gui_creates_open_line_without_adding_last_point(monkeypatch, tmp_path):
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
    from geostudio.app import GeoStudioWindow
    app = QApplication.instance() or QApplication([])
    window = GeoStudioWindow()
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene()
    monkeypatch.setattr(QInputDialog, 'getText', staticmethod(
        lambda *args, **kwargs: ('5214', True)))
    monkeypatch.setattr(QMessageBox, 'question', staticmethod(
        lambda *args, **kwargs: QMessageBox.Yes))
    monkeypatch.setattr(window, '_ask_polygon_attributes', lambda: {
        'A1': '', 'A2': '', 'A3': 'Granica', 'A4': '', 'A5': '', 'A6': '',
        'TX': '', 'MP': '0', 'DT': '', 'KR': ''})
    try:
        window.start_polygon(kind='line')
        window.add_polygon_point(2, 2)
        window.add_polygon_point(4, 2)
        assert len(window.doc.objects) == 1
        window.finish_polygon()
        assert len(window.doc.objects) == 2
        obj = window.doc.by_id[window.selected_uid]
        assert obj.code == '5214'
        assert not obj.is_closed
        assert len(obj.points) == 2
        assert not window.view.draw_mode
        assert window.history.can_undo
    finally:
        window.close()


def test_gui_text_line_code_6900_uses_selected_geometry(monkeypatch):
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox
    from geostudio.app import GeoStudioWindow
    app = QApplication.instance() or QApplication([])
    window = GeoStudioWindow()
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene()
    monkeypatch.setattr(QInputDialog, 'getItem', staticmethod(
        lambda *args, **kwargs: ('Linia — otwarta', True)))
    monkeypatch.setattr(QInputDialog, 'getText', staticmethod(
        lambda *args, **kwargs: ('6900', True)))
    monkeypatch.setattr(QMessageBox, 'question', staticmethod(
        lambda *args, **kwargs: QMessageBox.Yes))
    monkeypatch.setattr(window, '_ask_polygon_attributes', lambda: {
        'A1': '12', 'A2': '', 'A3': '', 'A4': '', 'A5': '', 'A6': '',
        'TX': 'N', 'MP': '0', 'DT': '', 'KR': ''})
    try:
        window.start_geometry()
        assert window.geometry_kind == 'line'
        window.add_polygon_point(2, 2)
        window.add_polygon_point(3, 2)
        window.finish_polygon()
        assert window.doc.by_id[window.selected_uid].code == '6900'
        assert window.doc.by_id[window.selected_uid].fields['TX'] == 'N'
    finally:
        window.close()
