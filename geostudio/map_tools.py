"""Canvas widget: mouse, wheel and keyboard handling for the map view.

Extracted verbatim from ``geostudio.app`` in v0.14.0. The class is a plain
``QGraphicsView`` subclass: it owns no document state, never touches the map
model, and communicates with the window exclusively through the fifteen
signals declared below. Moving it changes no behaviour — the same signals are
emitted from the same events, with the same coordinates and modifiers.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QTransform
from PySide6.QtWidgets import QGraphicsView


class MapView(QGraphicsView):
    """QGIS-style mutually exclusive canvas tools, no implicit scroll-hand dragging.

    The earlier code delegated selection to ScrollHandDrag, so a click could be
    treated as a pan. All edit actions now handle real viewport events directly.
    """
    coordinate = Signal(float, float)
    canvas_click = Signal(float, float, bool, bool)
    canvas_context = Signal(float, float)
    point_for_polygon = Signal(float, float)
    polygon_hover = Signal(float, float)
    finish_polygon = Signal()
    undo_polygon_point = Signal()
    cancel_action = Signal()
    vertex_hover = Signal(float, float, int)
    vertex_activate = Signal(float, float)
    vertex_commit = Signal(float, float, int)
    edge_insert = Signal(float, float)
    label_press = Signal(float, float)
    label_move = Signal(float, float)
    label_drop = Signal(float, float)
    zoom_changed = Signal()
    viewport_changed = Signal()  # Pan, zoom, resize and programmatic navigation.

    def __init__(self, scene):
        super().__init__(scene)
        self.draw_mode = False
        self.edit_mode = False
        self.pan_mode = False
        self.label_mode = False
        self._label_down = False
        self.edit_points = []
        self.dragged_vertex = None
        self._pan_button = None
        self._pan_last = None
        self._drag_decoration = False
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.setBackgroundBrush(QBrush(QColor('#f7f9fb')))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        # The GEO-MAP file stores X (northing) before Y (easting).
        # Existing scene uses (X, -Y); geodetic orientation on screen is
        # (Y, -X). Swapping the axes here preserves all scene geometry,
        # snapping, area calculations and original MAP record coordinates.
        self.setTransform(QTransform(0, -1, -1, 0, 0, 0))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.ArrowCursor)

    def _position(self, event):
        pt = self.mapToScene(event.position().toPoint())
        return pt.x(), -pt.y()

    def wheelEvent(self, event):
        """Zoom at cursor, independent of the active map tool or Qt anchor state."""
        delta = event.angleDelta().y()
        if not delta:
            event.accept()
            return
        factor = 1.2 ** (delta / 120.0)
        # m11 can be ZERO at a correct 90-degree rotation. Its absolute
        # value is not a zoom factor. Use the length of a transformed unit.
        transform = self.transform()
        current = math.hypot(transform.m11(), transform.m12())
        if not (1e-5 <= current * factor <= 4000):
            event.accept()
            return
        cursor = event.position().toPoint()
        fixed_scene_point = self.mapToScene(cursor)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.scale(factor, factor)
        # Scrollbar correction is explicit: map the same world point after
        # scaling, then bring it back under the original cursor pixel.
        shifted = self.mapFromScene(fixed_scene_point)
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() + shifted.x() - cursor.x())
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() + shifted.y() - cursor.y())
        self.zoom_changed.emit()
        self.viewport_changed.emit()
        event.accept()

    def scrollContentsBy(self, dx, dy):
        # Panning moves scrollbars many times; it is NOT a zoom change.
        # Emit only a cheap signal; background WMS uses a debounce timer,
        # never performs HTTP requests directly from this event.
        super().scrollContentsBy(dx, dy)
        if dx or dy:
            self.viewport_changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.viewport_changed.emit()

    def mouseMoveEvent(self, event):
        if self._drag_decoration:
            # Qt's scene drag machinery moves the vector layout item.
            super().mouseMoveEvent(event)
            event.accept()
            return
        if self._pan_button is not None:
            # Middle-button drag is temporary pan in SELECT/DRAW/EDIT/PAN.
            pos = event.position().toPoint()
            step = pos - self._pan_last
            self._pan_last = pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - step.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - step.y())
            event.accept()
            return
        x, y = self._position(event)
        self.coordinate.emit(x, y)
        if self.label_mode and self._label_down:
            self.label_move.emit(x, y)
        elif self.draw_mode:
            self.polygon_hover.emit(x, y)
        elif self.edit_mode and self.dragged_vertex is not None:
            self.vertex_hover.emit(x, y, self.dragged_vertex)
        event.accept()

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() == Qt.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if item is not None and item.data(0) == "geostudio-decoration":
                self._drag_decoration = True
                super().mousePressEvent(event)
                event.accept()
                return
        # Consistent explicit mouse handling avoids QGraphicsView.ScrollHandDrag
        # swallowing selection clicks and unexpectedly altering wheel anchors.
        if event.button() == Qt.MiddleButton or (self.pan_mode and event.button() == Qt.LeftButton):
            self._pan_button = event.button()
            self._pan_last = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        x, y = self._position(event)
        if self.label_mode:
            if event.button() == Qt.LeftButton:
                self._label_down = True
                self.label_press.emit(x, y)
            event.accept()
            return
        if self.draw_mode:
            if event.button() == Qt.RightButton:
                self.finish_polygon.emit()
            elif event.button() == Qt.LeftButton:
                self.point_for_polygon.emit(x, y)
        elif self.edit_mode:
            if event.button() == Qt.LeftButton:
                pos = event.position().toPoint()
                distances = [(self.mapFromScene(QPointF(px, -py)) - pos).manhattanLength()
                             for px, py in self.edit_points]
                near_current = bool(distances) and min(distances) <= 18
                if not near_current:
                    # Synchronously switch to a polygon of the *same code*
                    # under the mouse. The very same press can then begin
                    # dragging its vertex; a second selection is not required.
                    self.vertex_activate.emit(x, y)
                    distances = [(self.mapFromScene(QPointF(px, -py)) - pos).manhattanLength()
                                 for px, py in self.edit_points]
                if distances:
                    idx = min(range(len(distances)), key=distances.__getitem__)
                    if distances[idx] <= 18:
                        self.dragged_vertex = idx
                        self.vertex_hover.emit(x, y, idx)
                    else:
                        self.edge_insert.emit(x, y)
                else:
                    self.edge_insert.emit(x, y)
        elif event.button() == Qt.RightButton:
            self.canvas_context.emit(x, y)
        elif event.button() == Qt.LeftButton:
            self.canvas_click.emit(x, y, bool(event.modifiers() & Qt.AltModifier),
                                   bool(event.modifiers() & Qt.ControlModifier))
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag_decoration and event.button() == Qt.LeftButton:
            super().mouseReleaseEvent(event)
            self._drag_decoration = False
            event.accept()
            return
        if self._pan_button is not None and event.button() == self._pan_button:
            self._pan_button = None
            self._pan_last = None
            self.setCursor(Qt.OpenHandCursor if self.pan_mode else
                           Qt.CrossCursor if (self.draw_mode or self.edit_mode) else Qt.ArrowCursor)
            event.accept()
            return
        if self.label_mode and self._label_down and event.button() == Qt.LeftButton:
            self._label_down = False
            x, y = self._position(event)
            self.label_drop.emit(x, y)
            event.accept()
            return
        if self.edit_mode and self.dragged_vertex is not None and event.button() == Qt.LeftButton:
            x, y = self._position(event)
            idx = self.dragged_vertex
            self.dragged_vertex = None
            self.vertex_commit.emit(x, y, idx)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item is not None and item.data(0) == "geostudio-decoration":
            super().mouseDoubleClickEvent(event)
            event.accept()
            return
        if self.draw_mode:
            self.finish_polygon.emit()
        elif self.pan_mode:
            super().mouseDoubleClickEvent(event)
        else:
            event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.draw_mode:
            self.finish_polygon.emit()
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            if self.draw_mode:
                self.undo_polygon_point.emit()
            elif self.edit_mode or self.pan_mode or self.label_mode:
                self.cancel_action.emit()
            else:
                super().keyPressEvent(event)
                return
            event.accept()
            return
        super().keyPressEvent(event)
