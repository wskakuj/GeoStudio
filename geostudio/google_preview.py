"""In-application Google Earth Web reference viewer (no Maps API key).

Google Earth Web runs directly as Google's own complete website inside Qt's
WebEngine browser. It is NOT a georeferenced raster under GEO-MAP polygons:
Google's imagery may not be scraped, extracted or traced into a GIS map.
For georeferenced tracing GeoStudio provides licensed WMS or local rasters.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QLabel, QMessageBox,
    QPushButton, QVBoxLayout,
)

from .coordinates import CRS_CHOICES
from .wms_service import google_earth_browser_url


class GoogleMapsPreviewDialog(QDialog):
    """Google Earth browser embedded in GeoStudio; no external browser buttons."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setObjectName("GeoStudioGoogleEarthDialog")
        self.setWindowTitle("Google Earth — podgląd w GeoStudio (bez API)")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(1040, 740)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 10)
        root.setSpacing(8)
        caption = QLabel(
            "Google Earth działa tutaj jako pełna strona Google w aplikacji, "
            "bez klucza API. Podkład nie jest częścią sceny GEO-MAP. "
            "Do odrysowywania użyj ortofotomapy WMS lub własnego rastra.")
        caption.setWordWrap(True)
        root.addWidget(caption)

        form = QFormLayout()
        self.crs = QComboBox()
        self.crs.addItem("Wybierz zweryfikowany układ MAP", None)
        for title, code in CRS_CHOICES:
            self.crs.addItem(title, code)
        idx = self.crs.findData(window.current_crs_epsg)
        if idx > 0:
            self.crs.setCurrentIndex(idx)
        form.addRow("Układ współrzędnych", self.crs)
        root.addLayout(form)

        self.sync_button = QPushButton("Pokaż aktualny obszar mapy w Google Earth")
        self.sync_button.setObjectName("GeoStudioPrimaryButton")
        self.sync_button.clicked.connect(self.sync_to_current_view)
        root.addWidget(self.sync_button)

        self.info = QLabel(
            "Wymagany Qt WebEngine i aktywne połączenie z Internetem. "
            "Google Earth może wymagać GPU/WebGL i własnego logowania Google.")
        self.info.setWordWrap(True)
        root.addWidget(self.info)

        self.web_view = None
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except ImportError:
            self.info.setText(
                "Brakuje Qt WebEngine. Zainstaluj kompletne PySide6 z modułem "
                "QtWebEngineWidgets, aby wyświetlać Google Earth w GeoStudio.")
            self.sync_button.setEnabled(False)
        else:
            self.web_view = QWebEngineView(self)
            self.web_view.setObjectName("GeoStudioEarthWebView")
            root.addWidget(self.web_view, 1)
            self.web_view.loadFinished.connect(self._on_load_finished)
            if self.crs.currentData() is not None:
                self.sync_to_current_view()
            else:
                self.web_view.setUrl(QUrl("https://earth.google.com/web/"))

    def _on_load_finished(self, success):
        if not success:
            self.info.setText(
                "Google Earth nie otworzył się w Qt WebEngine. "
                "Sprawdź połączenie sieciowe, obsługę WebGL/GPU i uprawnienia strony.")

    def sync_to_current_view(self):
        if self.web_view is None:
            return
        epsg = self.crs.currentData()
        if epsg is None:
            QMessageBox.warning(
                self, "Nieznany układ współrzędnych",
                "Najpierw wybierz poprawny EPSG źródłowej mapy.")
            return
        rect = self.window.view.mapToScene(
            self.window.view.viewport().rect()).boundingRect()
        map_x, map_y = rect.center().x(), -rect.center().y()
        try:
            url = google_earth_browser_url(map_x, map_y, epsg)
        except (ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Google Earth", str(exc))
            return
        # Load Google's site as the MAIN page; embedding it in an iframe
        # can be blocked by Google's framing rules and loses functionality.
        self.web_view.setUrl(QUrl(url))
        self.info.setText(
            "Wczytywanie Google Earth dla środka widoku GEO-MAP. "
            "Po zmianie obszaru kliknij ponownie synchronizację. "
            "W razie braku przejścia do punktu użyj wyszukiwarki Google Earth.")
