"""GeoStudio application workspace: document context, tool rail and map canvas.

This is a structural Qt layout (not a QSS-only theme). The existing MapView,
QActions, menus and docks are reused unchanged; geometry/editing remain owned
by the application window.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (QFrame, QWidget, QLabel, QHBoxLayout,
                               QVBoxLayout, QToolButton, QGraphicsView)


class MapWorkspace(QWidget):
    """A map-first central work area with a contextual document header."""

    def __init__(self, map_view: QGraphicsView, edit_toolbar: QWidget,
                 select_filter: QWidget, *, on_fit, on_focus):
        super().__init__()
        self.setObjectName("GeoStudioWorkspace")
        self.setMinimumSize(320, 240)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame(self)
        header.setObjectName("GeoStudioDocumentHeader")
        head = QHBoxLayout(header)
        head.setContentsMargins(13, 4, 8, 4)
        head.setSpacing(8)

        heading = QVBoxLayout()
        heading.setSpacing(1)
        self.document_hint = QLabel("WIDOK MAPY")
        self.document_hint.setObjectName("GeoStudioDocumentEyebrow")
        heading.addWidget(self.document_hint)
        self.document_name = QLabel("Otwórz plik MAP, aby rozpocząć")
        self.document_name.setObjectName("GeoStudioDocumentName")
        self.document_name.setToolTip("Brak otwartego dokumentu")
        self.document_name.setMinimumWidth(50)
        heading.addWidget(self.document_name)
        head.addLayout(heading, 1)

        self.filter_caption = QLabel("ZAZNACZANIE")
        self.filter_caption.setObjectName("GeoStudioHeaderCaption")
        head.addWidget(self.filter_caption)

        self.select_filter = select_filter
        self.select_filter.setObjectName("GeoStudioCanvasFilter")
        self.select_filter.setMinimumWidth(130)
        self.select_filter.setMaximumWidth(200)
        # The selection filter lives in the ribbon's Map / Selection group.

        self.fit_button = self._button("Cała mapa", "Dopasuj widok do mapy")
        self.fit_button.clicked.connect(on_fit)
        self.fit_button.hide()  # Available in the Map ribbon navigation group.

        self.focus_button = self._button("Skupienie", "Pokaż tylko mapę (F11)")
        self.focus_button.setObjectName("GeoStudioFocusButton")
        self.focus_button.clicked.connect(on_focus)
        head.addWidget(self.focus_button)
        root.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(0)
        body.setContentsMargins(0, 0, 0, 0)

        self.tool_rail = QFrame(self)
        self.tool_rail.setObjectName("GeoStudioToolRail")
        self.tool_rail.setFixedWidth(104)
        self.tool_rail.hide()  # Edit commands are in the ArcGIS-style ribbon.
        rail = QVBoxLayout(self.tool_rail)
        rail.setContentsMargins(5, 9, 5, 7)
        rail.setSpacing(2)
        edit_toolbar.setParent(self.tool_rail)
        edit_toolbar.setFixedWidth(94)
        rail.addWidget(edit_toolbar, 0, Qt.AlignTop)
        rail.addStretch(1)
        rail_caption = QLabel("S · H · P · E · L")
        rail_caption.setObjectName("GeoStudioRailFootnote")
        rail_caption.setAlignment(Qt.AlignCenter)
        rail.addWidget(rail_caption)
        body.addWidget(self.tool_rail)

        canvas_frame = QFrame(self)
        canvas_frame.setObjectName("GeoStudioMapSurface")
        canvas_layout = QVBoxLayout(canvas_frame)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(0)
        map_view.setParent(canvas_frame)
        canvas_layout.addWidget(map_view, 1)
        self.map_view = map_view
        body.addWidget(canvas_frame, 1)
        root.addLayout(body, 1)

        self.canvas_footer = QLabel(
            "Środkowy przycisk — przesuwanie  ·  Rolka — przybliżanie  ·  "
            "Prawy przycisk — obiekty pod kursorem")
        self.canvas_footer.setObjectName("GeoStudioCanvasFooter")
        self.canvas_footer.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        root.addWidget(self.canvas_footer)
        self.canvas_footer.hide()  # Context tips are already in the status bar.

    @staticmethod
    def _button(text: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        button.setCursor(Qt.PointingHandCursor)
        return button

    def set_document(self, filename: str | None, *, dirty: bool = False):
        name = Path(filename).name if filename else "Otwórz plik MAP, aby rozpocząć"
        self.document_name.setText(name + (" • zmieniono" if dirty else ""))
        self.document_name.setToolTip(filename or "Brak otwartego dokumentu")
        self.document_hint.setText(
            "NIEZAPISANE ZMIANY" if dirty else
            "WIDOK MAPY" if filename else "GOTOWE DO PRACY")

    def set_tool(self, name: str):
        self.filter_caption.setText(name)
        instructions = {
            "ZAZNACZANIE": "Kliknij obiekt, aby zobaczyć szczegóły  ·  Ctrl+klik — wiele obiektów  ·  PPM — wybór spod kursora",
            "PRZESUWANIE": "Przeciągnij mapę  ·  Rolka — przybliżanie  ·  S — powrót do zaznaczania",
            "RYSOWANIE POLIGONU": "Klikaj wierzchołki  ·  Enter — zamknij  ·  Esc — cofnij punkt",
            "RYSOWANIE LINII": "Klikaj punkty linii  ·  Enter — zakończ bez zamykania",
            "EDYCJA WIERZCHOŁKÓW": "Przeciągnij węzeł lub kliknij krawędź  ·  Esc — zakończ",
            "PRZESUWANIE ETYKIET": "Przeciągnij napis A1/A2  ·  Po puszczeniu zapisze się nowe położenie",
        }
        self.canvas_footer.setText(instructions.get(
            name, "Środkowy przycisk — przesuwanie  ·  Rolka — przybliżanie"))

    def set_focus_mode(self, focused: bool):
        # A command ribbon replaces the old vertical palette in every mode.
        self.tool_rail.hide()
        self.canvas_footer.hide()
        self.focus_button.setText("Powrót do edycji" if focused else "Skupienie")
        self.focus_button.setToolTip(
            "Przywróć narzędzia i panele (F11)" if focused else
            "Ukryj panele i paletę narzędzi (F11)")
