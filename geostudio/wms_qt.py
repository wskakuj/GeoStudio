"""Non-blocking WMS GetCapabilities/GetMap preview below GEO-MAP geometry.

The map source CRS must be chosen explicitly if there is no verified .prj.
WMS 1.3 axis order and GEO-MAP's X northing / Y easting order are handled in
wms_service. No web map data is included in saved MAPs or project sidecars.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QPixmap, QTransform, QDesktopServices
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSlider, QVBoxLayout, QGraphicsPixmapItem,
)

from .coordinates import CRS_CHOICES
from .wms_auto import WMSMapSource
from .wms_service import (
    WMSBounds, WMSLayerInfo, capabilities_url, getmap_url, parse_capabilities,
)


def scene_item_transform(bounds: WMSBounds, image_width: int, image_height: int) -> QTransform:
    """WMS raster (east-west, north-south) → GEO-MAP Qt scene (X,-Y)."""
    if image_width <= 0 or image_height <= 0:
        raise ValueError("Nieprawidłowe wymiary WMS.")
    metres_per_east_pixel = (bounds.max_y - bounds.min_y) / image_width
    metres_per_north_pixel = (bounds.max_x - bounds.min_x) / image_height
    return QTransform(0, -metres_per_east_pixel,
                      -metres_per_north_pixel, 0,
                      bounds.max_x, -bounds.min_y)


class WMSPreviewOverlay:
    """In-memory WMS image under polygons and above local raster underlays."""

    def __init__(self):
        self.image: QPixmap | None = None
        self.bounds: WMSBounds | None = None
        self.opacity = 0.70
        self.visible = True
        self.item: QGraphicsPixmapItem | None = None
        self.title = ""
        self.source: WMSMapSource | None = None

    def clear_items(self):
        self.item = None

    def clear(self, scene=None):
        if scene is not None and self.item is not None:
            try:
                if self.item.scene() is scene:
                    scene.removeItem(self.item)
            except RuntimeError:
                pass
        self.item = None
        self.image = None
        self.bounds = None
        self.title = ""
        self.source = None

    def set_image(self, data: bytes, bounds: WMSBounds, title: str):
        pixmap = QPixmap()
        if not pixmap.loadFromData(data) or pixmap.isNull():
            raise ValueError("Odpowiedź serwera WMS nie jest prawidłowym obrazem.")
        if pixmap.width() > 4096 or pixmap.height() > 4096:
            raise ValueError("Obraz WMS przekracza dopuszczalne rozmiary.")
        self.image = pixmap
        self.bounds = bounds
        self.title = title

    def attach(self, scene):
        if self.item is not None:
            try:
                if self.item.scene() is scene:
                    scene.removeItem(self.item)
            except RuntimeError:
                pass
            self.item = None
        if self.image is None or self.bounds is None:
            return
        item = QGraphicsPixmapItem(self.image)
        item.setTransform(scene_item_transform(
            self.bounds, self.image.width(), self.image.height()))
        item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        item.setZValue(-50_000)
        item.setOpacity(self.opacity)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, False)
        item.setVisible(self.visible)
        scene.addItem(item)
        self.item = item


class WMSDialog(QDialog):
    """Remote WMS browser with source layer and CRS explicitly selected."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Podgląd WMS — podkład mapy")
        self.setMinimumWidth(555)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self._layers: list[WMSLayerInfo] = []
        self.network = QNetworkAccessManager(self)
        self.pending: QNetworkReply | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 17, 18, 14)
        root.setSpacing(12)
        caption = QLabel(
            "Wprowadź adres serwera WMS, pobierz listę warstw, wybierz układ "
            "zgodny z Twoją mapą i wyświetl podkład pod obiektami.")
        caption.setWordWrap(True)
        root.addWidget(caption)
        form = QFormLayout()
        form.setSpacing(10)
        # Official GUGiK orthoimagery WMS is a practical starting point in PL.
        default_wms = ("https://mapy.geoportal.gov.pl/wss/service/"
                       "PZGIK/ORTO/WMS/StandardResolution")
        self.server_selector = QComboBox(self)
        self.server_selector.setObjectName("GeoStudioWMSServerPresets")
        self.server_selector.addItem(
            "Geoportal — ortofotomapa standardowa", default_wms)
        self.server_selector.addItem(
            "Geoportal — ortofotomapa wysokiej rozdzielczości",
            "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/HighResolution")
        self.server_selector.addItem("Własny adres serwera WMS…", "custom")
        self.server_selector.addItem(
            "SmartSDI — dane EGiB/PRG (wtyczka QGIS, nie WMS)", "smartsdi")
        self.server_selector.currentIndexChanged.connect(self._server_changed)
        form.addRow("Źródło danych", self.server_selector)
        self.address = QLineEdit(str(window.settings.value("wms/last_url", default_wms)))
        self.address.setObjectName("GeoStudioWMSAddress")
        self.address.setPlaceholderText("https://.../wms")
        self.address.textEdited.connect(self._custom_address_entered)
        form.addRow("Adres WMS", self.address)
        preset = self.server_selector.findData(self.address.text())
        self.server_selector.setCurrentIndex(preset if preset >= 0 else 2)
        # Ordinary users should select one of the actual server-advertised
        # layers, not guess an internal identifier in an editable text field.
        self.layer_selector = QComboBox()
        self.layer_selector.setObjectName("GeoStudioWMSLayerPicker")
        self.layer_selector.setEditable(False)
        self.layer_selector.setMinimumContentsLength(24)
        self.layer_selector.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.layer_selector.addItem("Kliknij «Pobierz warstwy»", None)
        self.layer_selector.setEnabled(False)
        self.layer_selector.setToolTip(
            "Lista dostępnych warstw pochodzi z serwera WMS (GetCapabilities).")
        form.addRow("Warstwa WMS", self.layer_selector)
        self.crs_selector = QComboBox()
        self.crs_selector.addItem("Wybierz układ współrzędnych MAP", None)
        for description, code in CRS_CHOICES:
            self.crs_selector.addItem(description, code)
        if window.current_crs_epsg is not None:
            idx = self.crs_selector.findData(window.current_crs_epsg)
            if idx >= 0:
                self.crs_selector.setCurrentIndex(idx)
        form.addRow("Układ MAP", self.crs_selector)
        root.addLayout(form)
        self.smartsdi_link = QPushButton("SmartSDI — informacje o wtyczce QGIS", self)
        self.smartsdi_link.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl("https://github.com/geo-system/qgis-smartsdi")))
        root.addWidget(self.smartsdi_link)

        controls = QHBoxLayout()
        self.capabilities_button = QPushButton("Pobierz warstwy")
        self.capabilities_button.clicked.connect(self.fetch_layers)
        controls.addWidget(self.capabilities_button)
        self.map_button = QPushButton("Pokaż WMS pod mapą")
        self.map_button.setObjectName("GeoStudioPrimaryButton")
        self.map_button.clicked.connect(self.fetch_map)
        self.map_button.setEnabled(False)
        controls.addWidget(self.map_button)
        root.addLayout(controls)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel("Krycie podkładu"))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(70)
        self.opacity.valueChanged.connect(self._opacity_changed)
        opacity_row.addWidget(self.opacity, 1)
        root.addLayout(opacity_row)
        self.message = QLabel(
            "WMS używa dokładnie wskazanego układu MAP. Nie wybieraj go na podstawie "
            "samej wielkości współrzędnych.")
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        actions = QHBoxLayout()
        clear = QPushButton("Usuń WMS z widoku")
        clear.clicked.connect(self.clear_wms)
        actions.addWidget(clear)
        close = QPushButton("Zamknij")
        close.clicked.connect(self.close)
        actions.addWidget(close)
        root.addLayout(actions)

    def _server_changed(self, _index):
        selected = self.server_selector.currentData()
        if selected == "smartsdi":
            self.address.setEnabled(False)
            self.capabilities_button.setEnabled(False) if hasattr(self, "capabilities_button") else None
            if hasattr(self, "message"):
                self.message.setText(
                    "SmartSDI jest wtyczką QGIS do pobierania danych EGiB i PRG, "
                    "nie udostępnia własnego adresu WMS. "
                    "Przycisk poniżej otwiera stronę projektu.")
            return
        self.address.setEnabled(True)
        if hasattr(self, "capabilities_button"):
            self.capabilities_button.setEnabled(True)
        if selected not in ("custom", None):
            self.address.setText(selected)
        if hasattr(self, "layer_selector"):
            self._show_layers_failure()

    def _custom_address_entered(self, _value):
        self.server_selector.blockSignals(True)
        self.server_selector.setCurrentIndex(
            self.server_selector.findData("custom"))
        self.server_selector.blockSignals(False)
        if hasattr(self, "layer_selector"):
            self._show_layers_failure()

    def _opacity_changed(self, value):
        self.window._wms_preview.opacity = value / 100.
        if self.window._wms_preview.item is not None:
            self.window._wms_preview.item.setOpacity(value / 100.)

    def _request(self, url: str, callback, *, fetching_layers=False):
        if self.pending is not None:
            return
        req = QNetworkRequest(QUrl(url))
        req.setTransferTimeout(20_000)
        req.setRawHeader(b"User-Agent", b"GeoStudio/0.14 WMS client")
        reply = self.network.get(req)
        self.pending = reply
        self.capabilities_button.setEnabled(False)
        self.map_button.setEnabled(False)
        self.message.setText("Oczekiwanie na odpowiedź serwera WMS…")

        def finished():
            self.pending = None
            self.capabilities_button.setEnabled(True)
            self.map_button.setEnabled(
                self.layer_selector.isEnabled() and self.layer_selector.currentData() is not None)
            if reply.error() != QNetworkReply.NetworkError.NoError:
                if fetching_layers:
                    self._show_layers_failure()
                self.message.setText("Błąd połączenia WMS: " + reply.errorString())
            else:
                payload = bytes(reply.readAll())
                if len(payload) > 15_000_000:
                    if fetching_layers:
                        self._show_layers_failure()
                    self.message.setText("WMS zwrócił zbyt duży plik.")
                else:
                    try:
                        callback(payload)
                    except (ValueError, TypeError) as exc:
                        if fetching_layers:
                            self._show_layers_failure()
                        self.message.setText("Błąd odpowiedzi WMS: " + str(exc))
            reply.deleteLater()

        reply.finished.connect(finished)

    def _show_layers_failure(self):
        self._layers = []
        self.layer_selector.clear()
        self.layer_selector.addItem("Nie pobrano warstw — spróbuj ponownie", None)
        self.layer_selector.setEnabled(False)
        self.map_button.setEnabled(False)

    def fetch_layers(self):
        if self.server_selector.currentData() == "smartsdi":
            QMessageBox.information(
                self, "SmartSDI",
                "SmartSDI to wtyczka QGIS, a nie adres WMS. "
                "Otwórz projekt SmartSDI lub wybierz serwer Geoportalu.")
            return
        try:
            url = capabilities_url(self.address.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Adres WMS", str(exc))
            return

        self._layers = []
        self.layer_selector.clear()
        self.layer_selector.addItem("Trwa pobieranie listy warstw…", None)
        self.layer_selector.setEnabled(False)
        self.map_button.setEnabled(False)

        def received(xml):
            self._layers = list(parse_capabilities(xml))
            self.layer_selector.clear()
            if not self._layers:
                self.layer_selector.addItem("Serwer nie udostępnia warstw", None)
                self.layer_selector.setEnabled(False)
                self.map_button.setEnabled(False)
                self.message.setText(
                    "Serwer odpowiedział, ale nie udostępnił żadnej warstwy WMS. "
                    "Sprawdź adres usługi GetCapabilities.")
                return
            for info in self._layers:
                label = info.title if info.title == info.name else f"{info.title}  ({info.name})"
                self.layer_selector.addItem(label, info.name)
                self.layer_selector.setItemData(
                    self.layer_selector.count() - 1,
                    f"Identyfikator: {info.name}\nCRS: {', '.join(info.crs) or 'brak danych'}",
                    Qt.ItemDataRole.ToolTipRole)
            self.layer_selector.setEnabled(True)
            self.layer_selector.setCurrentIndex(0)
            self.map_button.setEnabled(True)
            self.message.setText(
                f"Pobrano {len(self._layers)} warstw. Rozwiń listę «Warstwa WMS» "
                "i wybierz pozycję, następnie wskaż zgodny EPSG.")

        self._request(url, received, fetching_layers=True)

    def _selected_layer(self):
        stored = self.layer_selector.currentData()
        for info in self._layers:
            if info.name == stored:
                return info
        return None

    def fetch_map(self):
        if not self.window.doc:
            QMessageBox.information(self, "WMS", "Najpierw otwórz mapę GEO-MAP.")
            return
        epsg = self.crs_selector.currentData()
        if not epsg:
            QMessageBox.warning(self, "Układ WMS", "Wybierz sprawdzony układ współrzędnych MAP.")
            return
        if (self.window.current_crs_epsg is not None and
                epsg != self.window.current_crs_epsg):
            QMessageBox.warning(
                self, "Niezgodny układ",
                "WMS i dokument MAP muszą mieć ten sam CRS. "
                f"MAP ma EPSG:{self.window.current_crs_epsg}, wybrano EPSG:{epsg}.")
            return
        layer = self._selected_layer()
        if layer is None:
            QMessageBox.warning(
                self, "Wybierz warstwę WMS",
                "Najpierw kliknij «Pobierz warstwy», a następnie wybierz "
                "warstwę z rozwijanej listy. Nie trzeba wpisywać jej ręcznie.")
            return
        crs = f"EPSG:{epsg}"
        if layer.crs and crs not in layer.crs:
            QMessageBox.warning(self, "WMS nie obsługuje układu",
                                f"Warstwa {layer.name} nie deklaruje obsługi {crs}.")
            return
        self.window.settings.setValue("wms/last_url", self.address.text())
        self.window._wms_preview.opacity = self.opacity.value() / 100.
        source = WMSMapSource(
            self.address.text(), layer.name, crs,
            layer.attribution or layer.title)
        # The controller is owned by the main window, not this dialog.
        # Closing the WMS dialog must NOT stop updates after pan or zoom.
        self.window._wms_auto.configure(source)
        self.message.setText(
            f"WMS: {layer.title}. Podkład odświeża się automatycznie po "
            "przesunięciu lub zmianie skali. Nie trzeba ponownie klikać.")

    def clear_wms(self):
        self.window._wms_auto.cancel()
        self.window._wms_preview.clear(self.window.map_scene)
        self.window._update_wms_attribution()
        self.message.setText("Usunięto podkład WMS z bieżącego widoku.")
