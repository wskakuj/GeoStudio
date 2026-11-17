"""Behavioural tests for the extracted canvas widget.

MapView talks to the window only through signals, so these tests drive the
event handlers directly and assert the emitted signal, its coordinates and its
modifiers. Nothing here renders: the widget's geometry contract (swapped map
axes, cursor-anchored zoom) is checked through the real transforms.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsView

from geostudio.app import GeoStudioWindow
from geostudio.map_tools import MapView

SIGNALS = ("coordinate", "canvas_click", "canvas_context", "point_for_polygon",
           "polygon_hover", "finish_polygon", "undo_polygon_point", "cancel_action",
           "vertex_hover", "vertex_commit", "edge_insert", "label_press",
           "label_move", "label_drop", "zoom_changed")


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def view(qt_app):
    scene = QGraphicsScene()
    scene.setSceneRect(0, 0, 1000, 1000)
    widget = MapView(scene)
    widget.resize(400, 300)
    # Shown so the scroll bars have a real range: cursor-anchored zoom is
    # implemented by correcting those scroll positions.
    widget.show()
    QApplication.processEvents()
    yield widget
    widget.close()


def press(view, x, y, button=Qt.LeftButton, modifiers=Qt.NoModifier):
    event = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x, y), QPointF(x, y),
                        button, button, modifiers)
    view.mousePressEvent(event)
    return event


def release(view, x, y, button=Qt.LeftButton, modifiers=Qt.NoModifier):
    event = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(x, y), QPointF(x, y),
                        button, Qt.NoButton, modifiers)
    view.mouseReleaseEvent(event)
    return event


def move(view, x, y, button=Qt.NoButton, buttons=Qt.LeftButton):
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(x, y), QPointF(x, y),
                        button, buttons, Qt.NoModifier)
    view.mouseMoveEvent(event)
    return event


def key(view, code, modifiers=Qt.NoModifier):
    event = QKeyEvent(QEvent.Type.KeyPress, code, modifiers)
    view.keyPressEvent(event)
    return event


def wheel(view, x, y, delta, modifiers=Qt.NoModifier):
    event = QWheelEvent(QPointF(x, y), QPointF(x, y), QPoint(), QPoint(0, delta),
                        Qt.NoButton, modifiers, Qt.NoScrollPhase, False)
    view.wheelEvent(event)
    return event


# --- identity of the widget ---------------------------------------------

def test_all_signals_are_preserved():
    for name in SIGNALS:
        assert hasattr(MapView, name), name
    assert len([n for n in SIGNALS if hasattr(MapView, n)]) == 15


def test_initial_state_and_swapped_map_axes(view):
    assert (view.draw_mode, view.edit_mode, view.pan_mode, view.label_mode) == (False,) * 4
    assert view.edit_points == []
    assert view.dragged_vertex is None
    transform = view.transform()
    # GEO-MAP stores X before Y; the canvas maps (X, -Y) and orients
    # geodetic axes with (Y, -X). That swap must survive the move.
    assert (transform.m11(), transform.m12(), transform.m21(), transform.m22()) == (0, -1, -1, 0)
    assert view.dragMode() == QGraphicsView.DragMode.NoDrag
    assert view.hasMouseTracking() is True
    assert view.backgroundBrush().color().name() == "#f7f9fb"


def test_window_still_exposes_the_view(qt_app):
    window = GeoStudioWindow()
    assert isinstance(window.view, MapView)
    assert window.view.scene() is window.map_scene
    window.close()


def test_position_converts_scene_y_to_map_y(view, monkeypatch):
    monkeypatch.setattr(view, "mapToScene", lambda point: QPointF(123.0, -456.0))
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(0, 0), QPointF(0, 0),
                        Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    assert view._position(event) == (123.0, 456.0)


# --- zoom ----------------------------------------------------------------

def test_wheel_zooms_and_keeps_the_point_under_the_cursor(view):
    seen = []
    view.zoom_changed.connect(lambda: seen.append(True))
    cursor = QPointF(120.0, 90.0)
    before = view.mapToScene(cursor.toPoint())
    wheel(view, 120.0, 90.0, 120)
    after = view.mapToScene(cursor.toPoint())
    assert seen == [True]
    assert after.x() == pytest.approx(before.x(), abs=1.0)
    assert after.y() == pytest.approx(before.y(), abs=1.0)


def test_wheel_without_delta_does_nothing(view):
    seen = []
    view.zoom_changed.connect(lambda: seen.append(True))
    before = view.transform()
    wheel(view, 10.0, 10.0, 0)
    assert seen == []
    assert view.transform() == before


def test_wheel_refuses_absurd_zoom(view):
    seen = []
    view.zoom_changed.connect(lambda: seen.append(True))
    view.scale(3500, 3500)          # 3500 * 1.2 exceeds the 4000 guard
    before = view.transform()
    wheel(view, 10.0, 10.0, 120)
    assert seen == []
    assert view.transform() == before


# --- keyboard ------------------------------------------------------------

def test_return_finishes_the_polygon_in_draw_mode(view):
    seen = []
    view.finish_polygon.connect(lambda: seen.append(True))
    view.draw_mode = True
    key(view, Qt.Key_Return)
    key(view, Qt.Key_Enter)
    assert seen == [True, True]


def test_escape_undoes_a_polygon_point_while_drawing(view):
    undone, cancelled = [], []
    view.undo_polygon_point.connect(lambda: undone.append(True))
    view.cancel_action.connect(lambda: cancelled.append(True))
    view.draw_mode = True
    key(view, Qt.Key_Escape)
    assert undone == [True] and cancelled == []


def test_escape_cancels_the_other_modes(view):
    cancelled = []
    view.cancel_action.connect(lambda: cancelled.append(True))
    for mode in ("edit_mode", "pan_mode", "label_mode"):
        setattr(view, mode, True)
        key(view, Qt.Key_Escape)
        setattr(view, mode, False)
    assert cancelled == [True, True, True]


# --- mouse ---------------------------------------------------------------

def test_left_click_selects_with_modifiers(view):
    seen = []
    view.canvas_click.connect(lambda *args: seen.append(args))
    press(view, 50, 60, Qt.LeftButton, Qt.AltModifier | Qt.ControlModifier)
    assert len(seen) == 1
    x, y, alt, ctrl = seen[0]
    assert (alt, ctrl) == (True, True)
    expected = view.mapToScene(QPoint(50, 60))
    assert x == pytest.approx(expected.x())
    assert y == pytest.approx(-expected.y())


def test_right_click_opens_the_context_menu(view):
    seen = []
    view.canvas_context.connect(lambda *args: seen.append(args))
    press(view, 20, 30, Qt.RightButton)
    assert len(seen) == 1


def test_middle_button_pans_without_emitting_clicks(view):
    clicks = []
    view.canvas_click.connect(lambda *args: clicks.append(args))
    press(view, 10, 10, Qt.MiddleButton)
    assert view._pan_button == Qt.MiddleButton
    move(view, 40, 25, Qt.NoButton, Qt.MiddleButton)
    release(view, 40, 25, Qt.MiddleButton)
    assert view._pan_button is None
    assert clicks == []


def test_draw_mode_sends_points_and_right_click_finishes(view):
    points, finished = [], []
    view.point_for_polygon.connect(lambda *args: points.append(args))
    view.finish_polygon.connect(lambda: finished.append(True))
    view.draw_mode = True
    press(view, 70, 80, Qt.LeftButton)
    press(view, 70, 80, Qt.RightButton)
    assert len(points) == 1
    assert finished == [True]


def test_label_mode_press_move_and_drop(view):
    events = []
    view.label_press.connect(lambda *args: events.append(("press", args)))
    view.label_move.connect(lambda *args: events.append(("move", args)))
    view.label_drop.connect(lambda *args: events.append(("drop", args)))
    view.label_mode = True
    press(view, 30, 30)
    move(view, 45, 55)
    release(view, 45, 55)
    assert [name for name, _ in events] == ["press", "move", "drop"]


def test_edit_mode_drags_the_nearest_vertex(view):
    committed = []
    view.vertex_commit.connect(lambda *args: committed.append(args))
    view.edit_mode = True
    scene_point = view.mapToScene(QPoint(100, 100))
    view.edit_points = [(scene_point.x(), -scene_point.y())]
    press(view, 100, 100)
    assert view.dragged_vertex == 0
    release(view, 110, 100)
    assert view.dragged_vertex is None
    assert len(committed) == 1 and committed[0][2] == 0
