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


def test_geomap_labels_are_never_mirrored_or_rotated_and_track_zoom(viewer):
    """The GEO-MAP geodetic view swaps axes and has negative determinant.

    All 5310 and 5216 glyphs must nevertheless have normal screen
    orientation while their pixel size follows the map's magnification.
    """
    from PySide6.QtWidgets import QGraphicsItem
    uid_building = viewer.doc.append_polygon(
        [(20,20),(35,20),(35,35)], '5310',
        fields={'A1':'bx','A2':'budynek'})
    uid_parcel = viewer.doc.append_polygon(
        [(40,40),(55,40),(55,55)], '5216',
        fields={'A2':'29/16'})
    viewer.rebuild_scene()
    labels = [viewer.label_items[(uid_building,'A1')],
              viewer.label_items[(uid_building,'A2')],
              viewer.label_items[(uid_parcel,'A2')]]
    view = viewer.view

    def check_upright():
        for item in labels:
            assert not (item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            transform = item.deviceTransform(view.viewportTransform())
            assert transform.determinant() > 0
            assert transform.m11() > 0 and transform.m22() > 0
            assert abs(transform.m12()) < 1e-8
            assert abs(transform.m21()) < 1e-8
            assert item.isVisible()

    def glyph_width(item):
        return item.deviceTransform(view.viewportTransform()).mapRect(
            item.boundingRect()).width()

    assert view.transform().determinant() < 0  # GEO-MAP orientation flips axes
    check_upright()
    before = glyph_width(labels[0])

    view.scale(2.5, 2.5)
    viewer.update_label_visibility()
    check_upright()
    assert glyph_width(labels[0]) == pytest.approx(before*2.5, abs=0.15)

    viewer.rotate_view(15)
    check_upright()
    viewer.rotate_view(90)
    check_upright()
    viewer.reset_orientation()
    check_upright()

    viewer.legacy_orientation()
    check_upright()
    viewer.reset_orientation()
    check_upright()

    view.scale(.1, .1)
    viewer.update_label_visibility()
    check_upright()
    assert glyph_width(labels[0]) == pytest.approx(before*.25, abs=0.15)


def test_wheel_and_scale_entry_refresh_label_screen_size(viewer):
    from PySide6.QtWidgets import QGraphicsItem
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtCore import QPoint, QPointF, Qt
    uid = viewer.doc.append_polygon(
        [(20,20),(35,20),(35,35)], '5310',
        fields={'A1':'bx','A2':'budynek'})
    viewer.rebuild_scene()
    view=viewer.view
    item=viewer.label_items[(uid,'A1')]
    before=item.deviceTransform(view.viewportTransform()).m11()
    cursor=QPoint(250,230)
    event=QWheelEvent(
        QPointF(cursor),QPointF(cursor),QPoint(),QPoint(0,120),
        Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
    view.wheelEvent(event)
    assert item.deviceTransform(view.viewportTransform()).m11() == pytest.approx(before*1.2,rel=1e-4)
    viewer.scale_combo.setCurrentText('1:2000')
    viewer.apply_view_scale()
    assert item.deviceTransform(view.viewportTransform()).m11() == pytest.approx(.55*pps(view),rel=1e-6)
    transform=item.deviceTransform(view.viewportTransform())
    assert transform.m11()>0 and transform.m22()>0
    assert abs(transform.m12()) < 1e-8
    assert item.isVisible()


def test_map_label_anchor_is_stationary_under_zoom_rotation_and_orientation(viewer):
    """One geodetic point anchors each caption independently of viewport scale.

    In v0.12 the item ignored the view transform and was then scaled again,
    making its centre drift away from the underlying parcel when zooming.
    """
    uid=viewer.doc.append_polygon(
        [(20,20),(35,20),(35,35)],'5310',fields={'A1':'bx','A2':'bud'})
    parcel=viewer.doc.append_polygon(
        [(40,40),(55,40),(55,55)],'5216',fields={'A2':'29/16'})
    viewer.rebuild_scene()
    view=viewer.view
    labels=[viewer.label_items[(uid,'A1')],
            viewer.label_items[(uid,'A2')],
            viewer.label_items[(parcel,'A2')]]

    def verify():
        for item in labels:
            t=item.deviceTransform(view.viewportTransform())
            center=t.map(item.boundingRect().center())
            anchor=view.viewportTransform().map(item.pos())
            q=pps(view)
            offset=float(item.data(2) or 0)
            ratio=float(item.data(3) or .55)
            assert center.x() == pytest.approx(anchor.x(), abs=.02)
            assert center.y() == pytest.approx(anchor.y()+q*ratio*offset,abs=.02)
            assert t.m11()==pytest.approx(q*ratio,rel=1e-7)
            assert t.m22()==pytest.approx(q*ratio,rel=1e-7)
            assert abs(t.m12()) < 1e-7 and abs(t.m21()) < 1e-7

    verify()
    view.scale(2.2,2.2)
    viewer.update_label_visibility()
    verify()
    view.scale(.2,.2)
    viewer.update_label_visibility()
    verify()
    viewer.rotate_view(15)
    verify()
    viewer.rotate_view(-90)
    verify()
    viewer.reset_orientation()
    verify()
    viewer.legacy_orientation()
    verify()
    viewer.reset_orientation()
    verify()


def test_manual_label_drag_keeps_anchor_exact_after_zoom(viewer):
    uid=viewer.doc.append_polygon(
        [(20,20),(35,20),(35,35)],'5310',fields={'A1':'bx','A2':'bud'})
    viewer.rebuild_scene()
    item=viewer.label_items[(uid,'A1')]
    viewer.start_label_edit()
    pos=item.pos()
    viewer._active_label=item
    viewer.end_label_drag(pos.x()+4, -pos.y()+3)
    assert item.pos().x() == pytest.approx(pos.x()+4)
    assert item.data(2)==0
    for factor in (2.0,.1,2.0):
        viewer.view.scale(factor,factor)
        viewer.update_label_visibility()
        center=item.deviceTransform(viewer.view.viewportTransform()).map(
            item.boundingRect().center())
        anchor=viewer.view.viewportTransform().map(item.pos())
        assert center.x() == pytest.approx(anchor.x(),abs=.02)
        assert center.y() == pytest.approx(anchor.y(),abs=.02)
