"""ArcGIS-style raster manager and non-modal ground control point workspace."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPen, QPixmap, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QGraphicsPixmapItem,
    QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSlider, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .raster_georef import GroundControlPoint, fit_affine


class RasterPixelView(QGraphicsView):
    """Wheel-zoomable raster image; clicking returns original pixel coordinates."""

    picked = Signal(float, float)

    def __init__(self, image_path: Path):
        self.scene_image = QGraphicsScene()
        super().__init__(self.scene_image)
        image = QPixmap(str(image_path))
        if image.isNull():
            raise ValueError("Nie udało się otworzyć obrazu rastra.")
        self.image = image
        self.canvas = QGraphicsPixmapItem(image)
        self.scene_image.addItem(self.canvas)
        self.setSceneRect(0, 0, image.width(), image.height())
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMouseTracking(True)
        self.setMinimumHeight(280)
        self._markers = []
        self._pending = None

    def fit(self):
        self.fitInView(self.canvas, Qt.AspectRatioMode.KeepAspectRatio)

    def show_points(self, points, pending=None):
        for item in self._markers:
            self.scene_image.removeItem(item)
        self._markers.clear()
        for n, point in enumerate(points, 1):
            self._add_marker(point.u, point.v, str(n), QColor("#1267B1"))
        if pending:
            self._add_marker(pending[0], pending[1], "+", QColor("#E35C35"))

    def _add_marker(self, u, v, label, color):
        radius = max(self.image.width(), self.image.height()) * 0.004
        radius = max(3, min(30, radius))
        pen = QPen(color, max(1., radius / 3.))
        pen.setCosmetic(True)
        marker = self.scene_image.addEllipse(u - radius, v - radius,
                                             radius * 2, radius * 2,
                                             pen, QBrush(Qt.BrushStyle.NoBrush))
        marker.setZValue(100)
        text = self.scene_image.addSimpleText(label)
        text.setBrush(QBrush(color))
        text.setPos(u + radius, v + radius)
        text.setZValue(101)
        self._markers.extend((marker, text))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            scene_point = self.mapToScene(event.position().toPoint())
            if self.canvas.contains(scene_point):
                self.picked.emit(scene_point.x(), scene_point.y())
                event.accept()
                return
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
        current = abs(self.transform().m11())
        if 0.015 < current * factor < 180:
            self.scale(factor, factor)
        event.accept()


class RasterCalibrationDialog(QDialog):
    """Non-modal GCP picker: raster click, then map click, repeat 3+ times."""

    def __init__(self, window, layer):
        super().__init__(window)
        self.window = window
        self.layer = layer
        self.points = list(layer.gcps)
        self.pending_pixel: tuple[float, float] | None = None
        self.fit_result = None
        self.setWindowTitle(f"Kalibracja rastra — {layer.path.name}")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.resize(730, 770)

        root = QVBoxLayout(self)
        root.setContentsMargins(15, 15, 15, 12)
        root.setSpacing(9)
        explanation = QLabel(
            "1. Kliknij charakterystyczny punkt na obrazie.  "
            "2. Kliknij «Punkt na mapie», a następnie jego odpowiednik w głównym oknie.  "
            "3. Powtórz co najmniej 3 razy (zalecane 6–10, rozłożone po całej mapie).")
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        self.pixel_view = RasterPixelView(layer.path)
        self.pixel_view.picked.connect(self._pixel_clicked)
        root.addWidget(self.pixel_view, 3)

        guidance = QHBoxLayout()
        self.pending_label = QLabel("Wskaż punkt na skanie rastra.")
        self.pending_label.setWordWrap(True)
        guidance.addWidget(self.pending_label, 1)
        self.pick_map_button = QPushButton("Wybierz odpowiednik na mapie")
        self.pick_map_button.setEnabled(False)
        self.pick_map_button.clicked.connect(self.request_map_click)
        guidance.addWidget(self.pick_map_button)
        root.addLayout(guidance)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Nr", "Raster U", "Raster V", "Mapa X", "Mapa Y", "Odchyłka [m]"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 2)

        adjustments = QHBoxLayout()
        self.remove_button = QPushButton("Usuń wybraną parę")
        self.remove_button.clicked.connect(self.remove_selected)
        adjustments.addWidget(self.remove_button)
        adjustments.addStretch(1)
        adjustments.addWidget(QLabel("Widoczność rastra:"))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(round(layer.opacity * 100))
        self.opacity.setMaximumWidth(180)
        adjustments.addWidget(self.opacity)
        self.opacity_label = QLabel(f"{self.opacity.value()}%")
        self.opacity.valueChanged.connect(
            lambda value: self.opacity_label.setText(f"{value}%"))
        adjustments.addWidget(self.opacity_label)
        root.addLayout(adjustments)

        self.metrics = QLabel("Brak kalibracji — wymagane co najmniej 3 pary punktów.")
        self.metrics.setWordWrap(True)
        root.addWidget(self.metrics)
        actions = QHBoxLayout()
        self.fit_button = QPushButton("Oblicz dopasowanie")
        self.fit_button.clicked.connect(self.calculate)
        actions.addWidget(self.fit_button)
        self.apply_button = QPushButton("Zastosuj i zapisz podkład")
        self.apply_button.setObjectName("GeoStudioPrimaryButton")
        self.apply_button.clicked.connect(self.apply_calibration)
        actions.addWidget(self.apply_button)
        close = QPushButton("Zamknij")
        close.clicked.connect(self.close)
        actions.addWidget(close)
        root.addLayout(actions)
        self._rebuild_table()

    def showEvent(self, event):
        super().showEvent(event)
        if not self.pixel_view.transform().m11() == 0:
            self.pixel_view.fit()

    def closeEvent(self, event):
        if self.window._raster_map_picker == self.take_map_coordinate:
            self.window._raster_map_picker = None
        super().closeEvent(event)

    def _pixel_clicked(self, u: float, v: float):
        self.pending_pixel = (u, v)
        self.pending_label.setText(
            f"Raster: U={u:.1f}, V={v:.1f}. Kliknij «Wybierz odpowiednik na mapie».")
        self.pick_map_button.setEnabled(True)
        self.pixel_view.show_points(self.points, self.pending_pixel)

    def request_map_click(self):
        if self.pending_pixel is None:
            return
        # MapView sends canvas_click only in selection mode. Changing tools
        # does not commit or modify any GEO-MAP objects.
        self.window.cancel_edit()
        self.window._raster_map_picker = self.take_map_coordinate
        self.pending_label.setText(
            "Teraz kliknij odpowiedni punkt na MAPIE w głównym oknie GeoStudio.")
        self.pick_map_button.setText("Oczekiwanie na kliknięcie…")
        self.window.activateWindow()
        self.window.view.setFocus()

    def take_map_coordinate(self, x: float, y: float):
        self.window._raster_map_picker = None
        self.pick_map_button.setText("Wybierz odpowiednik na mapie")
        if self.pending_pixel is None:
            return
        self.points.append(GroundControlPoint(
            self.pending_pixel[0], self.pending_pixel[1], x, y))
        self.pending_pixel = None
        self.pixel_view.show_points(self.points)
        self.pick_map_button.setEnabled(False)
        self.pending_label.setText(
            f"Dodano {len(self.points)} par punktów. Wybierz kolejny punkt na rastrze.")
        self.fit_result = None
        self._rebuild_table()
        self.show()
        self.raise_()
        self.activateWindow()

    def remove_selected(self):
        index = self.table.currentRow()
        if 0 <= index < len(self.points):
            self.points.pop(index)
            self.fit_result = None
            self.pixel_view.show_points(self.points, self.pending_pixel)
            self._rebuild_table()

    def _rebuild_table(self):
        self.table.setRowCount(len(self.points))
        for row, point in enumerate(self.points):
            error = (f"{self.fit_result.residuals[row]:.3f}"
                     if self.fit_result and row < len(self.fit_result.residuals) else "—")
            for column, value in enumerate((
                    str(row + 1), f"{point.u:.1f}", f"{point.v:.1f}",
                    f"{point.x:.3f}", f"{point.y:.3f}", error)):
                self.table.setItem(row, column, QTableWidgetItem(value))
        if self.fit_result is None:
            self.metrics.setText(
                f"{len(self.points)} par punktów. Co najmniej 3 do kalibracji; "
                "im lepsze rozmieszczenie, tym dokładniejsze dopasowanie.")
        self.apply_button.setEnabled(len(self.points) >= 3)

    def calculate(self):
        try:
            self.fit_result = fit_affine(self.points)
        except (ValueError, OverflowError) as exc:
            QMessageBox.warning(self, "Nie można skalibrować rastra", str(exc))
            self.fit_result = None
            return
        self._rebuild_table()
        self.metrics.setText(
            f"Kalibracja afiniczna — RMS = {self.fit_result.rmse:.3f} m, "
            f"maksymalna odchyłka = {max(self.fit_result.residuals):.3f} m. "
            "Jeśli odchyłki są wysokie, usuń błędne punkty lub użyj lepszego skanu.")

    def apply_calibration(self):
        if self.fit_result is None:
            self.calculate()
        if self.fit_result is None:
            return
        self.layer.coefficients = self.fit_result.coefficients
        self.layer.gcps = list(self.points)
        self.layer.opacity = self.opacity.value() / 100.
        self.layer.visible = True
        self.window._raster_overlay.attach(self.window.map_scene)
        self.window._refresh_raster_panel()
        try:
            self.window._save_raster_settings()
        except OSError as exc:
            QMessageBox.warning(
                self, "Nie zapisano ustawień", str(exc) +
                "\nRaster jest jednak skalibrowany w bieżącej sesji.")
        self.window.status.showMessage(
            f"Nałożono {self.layer.path.name} pod mapą, RMS {self.fit_result.rmse:.3f} m.")
        self.close()


class RasterLayerPanel(QWidget):
    """Dock content for raster visibility, ordering and opacity."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 12, 10, 10)
        heading = QLabel("PODKŁADY POD MAPĄ")
        heading.setObjectName("GeoStudioSectionHeading")
        root.addWidget(heading)
        note = QLabel("Rastry są wyświetlane pod poligonami i liniami GEO-MAP. "
                      "Włączenie podkładu nie zmienia pliku MAP.")
        note.setWordWrap(True)
        root.addWidget(note)
        self.layers = QListWidget()
        self.layers.itemChanged.connect(self._visibility_changed)
        root.addWidget(self.layers, 1)

        buttons = QHBoxLayout()
        add = QPushButton("Dodaj raster…")
        add.clicked.connect(window.add_raster)
        buttons.addWidget(add)
        calibrate = QPushButton("Kalibruj…")
        calibrate.clicked.connect(window.calibrate_selected_raster)
        buttons.addWidget(calibrate)
        root.addLayout(buttons)
        second = QHBoxLayout()
        remove = QPushButton("Usuń podkład")
        remove.clicked.connect(self.remove_selected)
        second.addWidget(remove)
        second.addStretch(1)
        root.addLayout(second)

        root.addWidget(QLabel("Krycie wybranego podkładu"))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.valueChanged.connect(self.change_opacity)
        self.opacity.sliderReleased.connect(self._commit_opacity)
        root.addWidget(self.opacity)
        self.refresh()

    def selected_layer(self):
        item = self.layers.currentItem()
        if item is None:
            return None
        try:
            return self.window._raster_overlay.by_id(item.data(Qt.ItemDataRole.UserRole))
        except KeyError:
            return None

    def refresh(self):
        store = self.window._raster_overlay
        selected = self.selected_layer()
        previous = selected.uid if selected else None
        self.layers.blockSignals(True)
        try:
            self.layers.clear()
            for layer in store.layers:
                name = layer.path.name
                suffix = "" if layer.calibrated else " — wymaga kalibracji"
                item = QListWidgetItem(name + suffix)
                item.setData(Qt.ItemDataRole.UserRole, layer.uid)
                item.setToolTip(str(layer.path))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if layer.visible
                                   else Qt.CheckState.Unchecked)
                self.layers.addItem(item)
                if layer.uid == previous:
                    self.layers.setCurrentItem(item)
            if self.layers.currentItem() is None and self.layers.count():
                self.layers.setCurrentRow(0)
        finally:
            self.layers.blockSignals(False)
        self.opacity.blockSignals(True)
        current = self.selected_layer()
        self.opacity.setValue(round(current.opacity * 100) if current else 60)
        self.opacity.blockSignals(False)

    def _visibility_changed(self, item):
        layer = self.window._raster_overlay.by_id(item.data(Qt.ItemDataRole.UserRole))
        layer.visible = item.checkState() == Qt.CheckState.Checked
        self.window._raster_overlay.update_layer(layer)
        self.window._save_raster_settings()

    def change_opacity(self, value):
        layer = self.selected_layer()
        if layer is not None:
            layer.opacity = value / 100.
            self.window._raster_overlay.update_layer(layer)
            # Save once the user finishes moving the slider.
            self.window._raster_opacity_pending = True

    def _commit_opacity(self):
        if getattr(self.window, '_raster_opacity_pending', False):
            self.window._raster_opacity_pending = False
            try:
                self.window._save_raster_settings()
            except OSError as exc:
                QMessageBox.warning(self, 'Nie zapisano ustawień', str(exc))

    def remove_selected(self):
        layer = self.selected_layer()
        if layer is None:
            return
        self.window._raster_overlay.remove(layer.uid, self.window.map_scene)
        self.refresh()
        self.window._save_raster_settings()
