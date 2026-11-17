"""Headless Qt smoke tests; run in GitHub Actions (Qt offscreen)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication, QGraphicsSimpleTextItem, QInputDialog
from PySide6.QtCore import QPointF
from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from test_geomap import fixture_map


@pytest.fixture(scope='module')
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_parcel_selected_under_overlapping_land_use_and_exact_outline(qt_app):
    window = GeoStudioWindow()
    window.doc = GeoMap(fixture_map())
    land_uid = window.doc.append_polygon([(0,0),(1,0),(1,1)],'5230','R')
    window.rebuild_scene()
    parcel_uid = 'DEMO-01'
    # Both polygon interiors contain the same point.
    window.select_at(.8,.1)
    assert window.selected_uid == parcel_uid
    assert window.highlight_item.path().elementCount()==4
    window.select_at(.8,.1,cycle=True)
    assert window.selected_uid == land_uid
    text_items = [x.text() for x in window.labels if isinstance(x,QGraphicsSimpleTextItem)]
    assert 'TEST' in text_items
    assert 'R' in text_items
    window.close()


def test_polygon_preview_and_creation(qt_app,monkeypatch):
    window=GeoStudioWindow()
    window.doc=GeoMap(fixture_map())
    window.rebuild_scene()
    monkeypatch.setattr(QInputDialog,'getText',staticmethod(lambda *a,**k: ('5216',True)))
    window.start_polygon()
    window.add_polygon_point(5,5)
    window.add_polygon_point(8,5)
    window.add_polygon_point(5,8)
    window.preview_polygon(6,7)
    assert window.draft_item.path().elementCount() == 4
    monkeypatch.setattr(window, '_ask_polygon_attributes', lambda: {'A1':'', 'A2':'nowa', 'A3':'', 'A4':'', 'A5':'', 'A6':'', 'TX':'', 'MP':'0', 'DT':'', 'KR':''})
    window.finish_polygon()
    assert len(window.doc.objects)==2
    assert window.selected_uid in window.doc.by_id
    assert window.doc.by_id[window.selected_uid].is_closed
    window.close()


def test_edit_vertex_preserves_object_and_selection(qt_app):
    window=GeoStudioWindow()
    window.doc=GeoMap(fixture_map())
    window.rebuild_scene()
    window._select_uid('DEMO-01')
    window.start_vertex_edit()
    assert window.view.edit_mode
    assert len(window.edit_handles)==3
    window.preview_vertex(.2,.2,0)
    window.commit_vertex(.2,.2,0)
    assert window.doc.by_id['DEMO-01'].points[0].x==.2
    assert window.doc.by_id['DEMO-01'].is_closed
    assert window.selected_uid=='DEMO-01'
    assert window.view.edit_mode
    window.close()


def test_toolbar_modes_and_mouse_clicks(qt_app, monkeypatch):
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    window = GeoStudioWindow()
    window.show()
    window.doc = GeoMap(fixture_map())
    land_uid = window.doc.append_polygon([(0,0),(1,0),(1,1)],'5230','R')
    window.rebuild_scene()
    qt_app.processEvents()
    assert not window.view.pan_mode
    assert window.tool_actions['select'].isChecked()
    position = window.view.mapFromScene(QPointF(.8,-.1))
    QTest.mouseClick(window.view.viewport(),Qt.LeftButton,pos=position)
    qt_app.processEvents()
    assert window.selected_uid == 'DEMO-01'
    QTest.mouseClick(window.view.viewport(),Qt.LeftButton,Qt.AltModifier,pos=position)
    assert window.selected_uid == land_uid
    window.start_pan()
    assert window.view.pan_mode and window.tool_actions['pan'].isChecked()
    window.cancel_edit()
    assert not window.view.pan_mode and window.tool_actions['select'].isChecked()
    window.close()


def test_labels_visible_for_selected_feature_and_toggle(qt_app):
    window=GeoStudioWindow()
    window.show()
    window.doc=GeoMap(fixture_map())
    window.rebuild_scene()
    qt_app.processEvents()
    window._select_uid('DEMO-01')
    selected=[x for x in window.labels if x.data(0)=='DEMO-01']
    assert len(selected)==1 and selected[0].isVisible()
    window.labels_action.setChecked(False)
    assert not selected[0].isVisible()
    window.labels_action.setChecked(True)
    assert selected[0].isVisible()
    window.close()


def test_drawing_real_viewport_mouse_events(qt_app,monkeypatch):
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    window=GeoStudioWindow()
    window.show()
    window.doc=GeoMap(fixture_map())
    window.rebuild_scene()
    qt_app.processEvents()
    monkeypatch.setattr(QInputDialog,'getText',staticmethod(lambda *a,**k: ('5216',True)))
    window.start_polygon()
    assert window.view.draw_mode and window.tool_actions['draw'].isChecked()
    for x,y in ((0.25,0.2),(0.8,0.3),(0.3,0.8)):
        pos = window.view.mapFromScene(QPointF(x,-y))
        QTest.mouseClick(window.view.viewport(), Qt.LeftButton, pos=pos)
    assert len(window.current_polygon)==3
    assert len(window.draft_points)==3
    monkeypatch.setattr(window, '_ask_polygon_attributes', lambda: {'A1':'', 'A2':'test', 'A3':'', 'A4':'', 'A5':'', 'A6':'', 'TX':'', 'MP':'0', 'DT':'', 'KR':''})
    # Qt sends native press to the viewport; the right-click must close it.
    QTest.mouseClick(window.view.viewport(),Qt.RightButton,pos=window.view.mapFromScene(QPointF(.3,-.8)))
    assert len(window.doc.objects)==2
    assert not window.view.draw_mode
    window.close()


def test_edit_vertex_using_actual_mouse_drag(qt_app):
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    window = GeoStudioWindow()
    window.show()
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene()
    qt_app.processEvents()
    window._select_uid('DEMO-01')
    window.start_vertex_edit()
    assert window.view.edit_mode
    start = window.view.mapFromScene(QPointF(1, 0))
    end = window.view.mapFromScene(QPointF(.8, -.12))
    QTest.mousePress(window.view.viewport(), Qt.LeftButton, pos=start)
    QTest.mouseMove(window.view.viewport(), pos=end)
    QTest.mouseRelease(window.view.viewport(), Qt.LeftButton, pos=end)
    assert window.view.edit_mode
    edited = window.doc.by_id['DEMO-01']
    assert edited.points[1].x == pytest.approx(.8, abs=.01)
    assert edited.is_closed
    window.close()


def test_all_labels_toggle(qt_app):
    window = GeoStudioWindow()
    window.show()
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene()
    qt_app.processEvents()
    assert window.labels_action.isChecked()
    window.all_labels_action.setChecked(True)
    assert all(label.isVisible() for label in window.labels)
    window.all_labels_action.setChecked(False)
    window.close()


def test_plain_repeated_click_cycles_overlapping_features(qt_app):
    window = GeoStudioWindow()
    window.doc = GeoMap(fixture_map())
    land_uid = window.doc.append_polygon([(0,0),(1,0),(1,1)], '5230', 'R')
    window.rebuild_scene()
    window.select_at(.8, .1)
    assert window.selected_uid == 'DEMO-01'
    window.select_at(.8, .1)
    assert window.selected_uid == land_uid
    window.select_at(.8, .1)
    assert window.selected_uid == 'DEMO-01'
    window.select_at(.6, .15)
    assert window.selected_uid == 'DEMO-01'
    window.close()


def test_click_first_vertex_finishes_and_autosaves_work_copy(qt_app, monkeypatch, tmp_path):
    from pathlib import Path
    p = tmp_path / 'example.MAP'
    original = fixture_map()
    p.write_bytes(original)
    window = GeoStudioWindow()
    window.doc = GeoMap.open(p)
    window.rebuild_scene()
    monkeypatch.setattr(QInputDialog, 'getText', staticmethod(lambda *a, **k: ('5216', True)))
    window.start_polygon()
    for x, y in ((2,2), (5,2), (3,5)):
        window.add_polygon_point(x, y)
    monkeypatch.setattr(window, '_ask_polygon_attributes', lambda: {'A1':'', 'A2':'rysunek', 'A3':'', 'A4':'', 'A5':'', 'A6':'', 'TX':'', 'MP':'0', 'DT':'', 'KR':''})
    window.add_polygon_point(2.001, 2.001)
    assert len(window.doc.objects) == 2
    assert not window.view.draw_mode
    assert p.read_bytes() == original
    assert window._auto_copy_path is not None
    assert window._auto_copy_path.is_file()
    output = GeoMap.open(window._auto_copy_path)
    assert output.checksum_valid
    assert len(output.objects) == 2
    window.close()


def test_edit_click_edge_adds_vertex_and_keeps_edit_mode(qt_app):
    window = GeoStudioWindow()
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene()
    window._select_uid('DEMO-01')
    window.start_vertex_edit()
    original = window.doc.by_id['DEMO-01'].area_m2
    window.insert_vertex_at(.5, .001)
    obj = window.doc.by_id['DEMO-01']
    assert len(obj.points) == 5
    assert obj.points[1].x == pytest.approx(.5)
    assert obj.area_m2 == pytest.approx(original)
    assert window.view.edit_mode
    assert len(window.edit_handles) == 4
    window.close()


def test_middle_mouse_pan_keeps_tool_active(qt_app, monkeypatch):
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt, QPoint
    window = GeoStudioWindow()
    window.show()
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene()
    qt_app.processEvents()
    view = window.view
    for mode in ('select', 'pan', 'draw', 'edit'):
        if mode == 'pan':
            window.start_pan()
        elif mode == 'draw':
            monkeypatch.setattr(QInputDialog, 'getText', staticmethod(lambda *a, **k: ('5216', True)))
            window.start_polygon()
        elif mode == 'edit':
            window.cancel_edit()
            window._select_uid('DEMO-01')
            window.start_vertex_edit()
        else:
            window.cancel_edit()
        QTest.mousePress(view.viewport(), Qt.MiddleButton, pos=QPoint(60,60))
        assert view._pan_button == Qt.MiddleButton
        QTest.mouseMove(view.viewport(), pos=QPoint(90,85))
        QTest.mouseRelease(view.viewport(), Qt.MiddleButton, pos=QPoint(90,85))
        assert view._pan_button is None
        if mode == 'draw':
            assert view.draw_mode
        if mode == 'edit':
            assert view.edit_mode
    window.close()


def test_wheel_zoom_same_factor_in_all_tools(qt_app, monkeypatch):
    from PySide6.QtCore import Qt, QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    window = GeoStudioWindow()
    window.show()
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene()
    qt_app.processEvents()
    view = window.view
    for mode in ('select', 'pan', 'draw', 'edit'):
        if mode == 'pan':
            window.start_pan()
        elif mode == 'draw':
            monkeypatch.setattr(QInputDialog, 'getText', staticmethod(lambda *a, **k: ('5216', True)))
            window.start_polygon()
        elif mode == 'edit':
            window.cancel_edit()
            window._select_uid('DEMO-01')
            window.start_vertex_edit()
        else:
            window.cancel_edit()
        before = view.transform().m11()
        ev = QWheelEvent(QPointF(100,100),QPointF(100,100),QPoint(),QPoint(0,120),
                         Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
        view.wheelEvent(ev)
        assert view.transform().m11() == pytest.approx(before * 1.2)
    window.close()

def test_cursor_zoom_preserves_position(qt_app):
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtCore import Qt, QPoint, QPointF
    window = GeoStudioWindow()
    window.show()
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene()
    qt_app.processEvents()
    view = window.view
    for mode in ('select', 'pan', 'edit'):
        if mode == 'pan':
            window.start_pan()
        elif mode == 'edit':
            window.cancel_edit()
            window._select_uid('DEMO-01')
            window.start_vertex_edit()
        else:
            window.cancel_edit()
        target = QPoint(185, 220)
        world_before = view.mapToScene(target)
        event = QWheelEvent(QPointF(target), QPointF(target),
                            QPoint(), QPoint(0, 120), Qt.NoButton,
                            Qt.NoModifier, Qt.NoScrollPhase, False)
        view.wheelEvent(event)
        world_after = view.mapToScene(target)
        assert (world_after - world_before).manhattanLength() < 0.02
    window.close()


def test_full_polygon_form_and_delete_work_copy(qt_app, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    original = fixture_map()
    file = tmp_path / 'sample.MAP'
    file.write_bytes(original)
    window = GeoStudioWindow()
    window.doc = GeoMap.open(file)
    window.rebuild_scene()
    monkeypatch.setattr(QInputDialog, 'getText', staticmethod(lambda *a, **k: ('5230', True)))
    window.start_polygon()
    window.add_polygon_point(5, 5)
    window.add_polygon_point(8, 5)
    window.add_polygon_point(5, 8)
    monkeypatch.setattr(window, '_ask_polygon_attributes', lambda: {
        'A1':'105','A2':'RV','A3':'143411_5.0014','A4':'','A5':'','A6':'',
        'TX':'uwagi','MP':'0','DT':'','KR':''
    })
    window.finish_polygon()
    created = window.selected_uid
    assert window.doc.by_id[created].fields['A1'] == '105'
    assert window.doc.by_id[created].fields['A2'] == 'RV'
    assert window.doc.by_id[created].fields['A4'] == ''
    assert window.doc.by_id[created].fields['TX'] == 'uwagi'
    monkeypatch.setattr(QMessageBox, 'question', staticmethod(
        lambda *a, **k: QMessageBox.Yes))
    window.delete_selected()
    assert created not in window.doc.by_id
    assert len(window.doc.objects) == 1
    assert file.read_bytes() == original
    saved = GeoMap.open(window._auto_copy_path)
    assert saved.checksum_valid and saved.declared_lines == len(saved.lines)
    assert len(saved.objects) == 1
    window.close()


def test_hide_multipart_connectors_is_visual_only(qt_app):
    from PySide6.QtGui import QPainterPath
    doc = GeoMap(fixture_map())
    obj = doc.objects[0]
    from geostudio.geomap import GeoPoint
    obj.points = [
        GeoPoint(0,0),GeoPoint(1,0),GeoPoint(1,1),
        GeoPoint(0,0,point_type=0),
        GeoPoint(10,10),GeoPoint(11,10),GeoPoint(11,11),
        GeoPoint(10,10,point_type=0)]
    path_hidden = GeoStudioWindow._path_for(obj, hide_connectors=True)
    path_visible = GeoStudioWindow._path_for(obj, hide_connectors=False)
    assert path_hidden.elementAt(4).type == QPainterPath.MoveToElement
    assert path_visible.elementAt(4).type == QPainterPath.LineToElement
