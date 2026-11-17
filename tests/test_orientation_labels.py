"""View orientation / zoom / label clarity regressions, Qt offscreen."""
import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from test_geomap import fixture_map


@pytest.fixture
def viewer():
    app = QApplication.instance() or QApplication([])
    window = GeoStudioWindow()
    window.show()
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene()
    app.processEvents()
    yield window
    window.close()


def pps(view):
    """Effective screen pixels per map unit; valid also when m11 == zero."""
    t = view.transform()
    return math.hypot(t.m11(), t.m12())


def test_default_geodetic_orientation_matches_north_up_east_right(viewer):
    view = viewer.view
    # Stored GEO-MAP X is northing; GEO-MAP Y is easting.
    pt = view.mapFromScene(QPointF(10, -20))
    east = view.mapFromScene(QPointF(10, -30))
    north = view.mapFromScene(QPointF(20, -20))
    assert east.x() > pt.x()
    assert abs(east.y() - pt.y()) <= 1
    assert north.y() < pt.y()
    assert abs(north.x() - pt.x()) <= 1
    assert pps(view) > 0


def test_rotation_and_reset_keep_world_center_and_zoom(viewer):
    view = viewer.view
    center = view.viewport().rect().center()
    before_scene = view.mapToScene(center)
    before_zoom = pps(view)
    viewer.rotate_view(15)
    assert pps(view) == pytest.approx(before_zoom)
    assert viewer.view_rotation_degrees == 15
    viewer.rotate_view(-15)
    assert viewer.view_rotation_degrees == 0
    viewer.legacy_orientation()
    legacy = view.mapFromScene(QPointF(10, -20))
    old_east = view.mapFromScene(QPointF(10, -30))
    assert old_east.y() < legacy.y()
    viewer.reset_orientation()
    assert viewer.orientation_is_geodetic
    assert viewer.view_rotation_degrees == 0
    assert pps(view) == pytest.approx(before_zoom)
    after_scene = view.mapToScene(center)
    assert (after_scene - before_scene).manhattanLength() < .2


def test_zoom_wheel_works_at_90_degree_and_tracks_cursor(viewer):
    view = viewer.view
    assert abs(view.transform().m11()) < .001
    target = QPoint(250, 230)
    before_scene = view.mapToScene(target)
    before_zoom = pps(view)
    event = QWheelEvent(QPointF(target), QPointF(target),
        QPoint(), QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
        Qt.NoScrollPhase, False)
    view.wheelEvent(event)
    assert pps(view) == pytest.approx(before_zoom * 1.2)
    after_scene = view.mapToScene(target)
    assert (after_scene - before_scene).manhattanLength() < .03


def test_zoomed_out_labels_remain_present_but_shrink_with_map(viewer):
    uid = viewer.doc.append_polygon(
        [(20,20),(35,20),(35,35)], "5310", fields={"A1":"bx","A2":"budynek"})
    viewer.rebuild_scene()
    label = next(x for x in viewer.labels if x.data(0) == uid)
    before = label.deviceTransform(viewer.view.viewportTransform()).mapRect(
        label.boundingRect()).width()
    viewer.view.scale(.02, .02)
    viewer.update_label_visibility()
    after = label.deviceTransform(viewer.view.viewportTransform()).mapRect(
        label.boundingRect()).width()
    assert label.isVisible()  # never intentionally hide by zoom threshold
    assert after < before / 20
    viewer._select_uid(uid)
    assert label.isVisible()


def test_pick_and_snap_tolerance_nonzero_after_view_rotation(viewer):
    from geostudio.app import QPoint
    view = viewer.view
    origin = view.mapToScene(QPoint(0, 0))
    other = view.mapToScene(QPoint(12, 0))
    assert math.hypot(other.x()-origin.x(), other.y()-origin.y()) > 0
    viewer._select_uid("DEMO-01")
    viewer.start_vertex_edit()
    viewer.insert_vertex_at(.5, .001)
    assert len(viewer.doc.by_id["DEMO-01"].points) == 5
