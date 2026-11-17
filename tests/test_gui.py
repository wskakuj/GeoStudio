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
    monkeypatch.setattr(QInputDialog,'getText',staticmethod(lambda *a,**k: ('nowa',True)))
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
    assert not window.view.edit_mode
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
    monkeypatch.setattr(QInputDialog,'getText',staticmethod(lambda *a,**k: ('test',True)))
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
    assert not window.view.edit_mode
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
