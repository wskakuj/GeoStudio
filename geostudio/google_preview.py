"""Optional official Google Maps Embed API preview in a standalone browser pane.

No screenshot/tiles are downloaded, cached, exported, or placed inside the
GEO-MAP graphics scene. Google branding and attribution remain in the iframe.
The user supplies an API key each session; it is never written to QSettings.
"""
from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from .coordinates import CRS_CHOICES
from .wms_service import (
    google_maps_embed_url, google_maps_reference_url, google_earth_browser_url,
)


class GoogleMapsPreviewDialog(QDialog):
    """Interactive Google Maps pane, using only Google's sanctioned Embed API."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.setWindowTitle("Google Maps — podgląd referencyjny")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(880, 690)

        root = QVBoxLayout(self)
        root.setContentsMargins(15, 15, 15, 12)
        root.setSpacing(10)
        description = QLabel(
            "Mapa Google otwiera się jako oficjalny, niezależny podgląd. "
            "Do wyświetlania w GeoStudio potrzebny jest własny klucz Google "
            "Maps Embed API. Dane mapowe i logotypy pozostają w widoku Google; "
            "nie są kopiowane do pliku GEO-MAP ani pobierane jako kafelki.")
        description.setWordWrap(True)
        root.addWidget(description)

        form = QFormLayout()
        self.crs = QComboBox()
        self.crs.addItem("Wybierz zweryfikowany CRS mapy", None)
        for title, code in CRS_CHOICES:
            self.crs.addItem(title, code)
        idx = self.crs.findData(window.current_crs_epsg)
        if idx > 0:
            self.crs.setCurrentIndex(idx)
        form.addRow("Układ MAP", self.crs)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Klucz Maps Embed API (nie jest zapisywany)")
        form.addRow("Klucz Google API", self.key)
        self.map_type = QComboBox()
        self.map_type.addItem("Zdjęcia satelitarne", "satellite")
        self.map_type.addItem("Mapa drogowa", "roadmap")
        form.addRow("Widok", self.map_type)
        self.zoom = QSpinBox()
        self.zoom.setRange(1, 21)
        self.zoom.setValue(17)
        form.addRow("Przybliżenie", self.zoom)
        root.addLayout(form)

        buttons = QHBoxLayout()
        open_embed = QPushButton("Pokaż mapę Google w GeoStudio")
        open_embed.setObjectName("GeoStudioPrimaryButton")
        open_embed.clicked.connect(self.show_embed)
        buttons.addWidget(open_embed)
        browser = QPushButton("Google Maps — przeglądarka (bez API)")
        browser.clicked.connect(self.open_browser)
        buttons.addWidget(browser)
        earth = QPushButton("Google Earth — przeglądarka (bez API)")
        earth.clicked.connect(self.open_earth)
        buttons.addWidget(earth)
        root.addLayout(buttons)

        self.note = QLabel(
            "Usługa Google Maps Embed API wymaga włączenia w Google Cloud "
            "i odpowiednich ograniczeń klucza API. W razie odmowy autoryzacji "
            "możesz otworzyć Google Maps w przeglądarce.")
        self.note.setWordWrap(True)
        root.addWidget(self.note)
        self.map_container = QWidget(self)
        self.map_container.setMinimumHeight(300)
        self.map_layout = QVBoxLayout(self.map_container)
        self.map_layout.setContentsMargins(0, 0, 0, 0)
        self.map_view = None
        root.addWidget(self.map_container, 1)

    def _coordinates(self):
        epsg = self.crs.currentData()
        if epsg is None:
            raise ValueError("Wybierz poprawny układ współrzędnych MAP.")
        rect = self.window.view.mapToScene(
            self.window.view.viewport().rect()).boundingRect()
        return rect.center().x(), -rect.center().y(), epsg

    def show_embed(self):
        try:
            x, y, epsg = self._coordinates()
            url = google_maps_embed_url(x, y, epsg, self.key.text(),
                                        self.zoom.value(), self.map_type.currentData())
        except ValueError as exc:
            QMessageBox.warning(self, "Google Maps", str(exc))
            return
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except ImportError:
            QMessageBox.information(
                self, "Qt WebEngine niedostępny",
                "Zainstaluj pełne PySide6 z WebEngine lub skorzystaj z przeglądarki.")
            return
        if self.map_view is None:
            self.map_view = QWebEngineView(self.map_container)
            self.map_layout.addWidget(self.map_view)
        # Google supplies attribution and control UI inside the unmodified
        # iframe. No extra overlays may cover the provider's copyright notices.
        safe_url = escape(url, quote=True)
        self.map_view.setHtml(
            '<!doctype html><html lang="pl"><head><meta charset="utf-8">'
            '<style>html,body,iframe{margin:0;width:100%;height:100%;border:0;'
            'overflow:hidden}</style></head><body><iframe '
            'referrerpolicy="no-referrer-when-downgrade" '
            'loading="eager" allowfullscreen '
            f'src="{safe_url}"></iframe></body></html>',
            QUrl("https://www.google.com/"))
        self.note.setText("Widok pochodzi z oficjalnego Maps Embed API. "
                          "Podkład Google nie jest częścią obrazu eksportowanego z GeoStudio.")

    def open_browser(self):
        try:
            x, y, epsg = self._coordinates()
            link = google_maps_reference_url(x, y, epsg, self.zoom.value())
            if not QDesktopServices.openUrl(QUrl(link)):
                raise ValueError("Nie udało się otworzyć przeglądarki.")
        except ValueError as exc:
            QMessageBox.warning(self, "Google Maps", str(exc))


    def open_earth(self):
        """Open the official Google Earth site; no key or imagery extraction."""
        try:
            x, y, epsg = self._coordinates()
            link = google_earth_browser_url(x, y, epsg)
            if not QDesktopServices.openUrl(QUrl(link)):
                raise ValueError("Nie udało się otworzyć Google Earth.")
        except ValueError as exc:
            QMessageBox.warning(self, "Google Earth", str(exc))
