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
