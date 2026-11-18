"""Search-and-run command palette for the desktop GeoStudio workspace.

Uses the existing QAction instances and never duplicates map/edit behavior.
"""
from __future__ import annotations

import unicodedata

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QVBoxLayout,
)


def _fold(text: str) -> str:
    # Accent-insensitive matches are useful for Polish GIS commands.
    return "".join(char for char in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(char)).replace("ł", "l")


class CommandPalette(QDialog):
    """Accessible Ctrl+K palette: fuzzy-enough search without GIS dependencies."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GeoStudioCommandPalette")
        self.setWindowTitle("Znajdź polecenie")
        self.setMinimumWidth(440)
        self.resize(550, 450)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        self._commands = []
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(11)

        heading = QLabel("Wyszukaj i uruchom narzędzie")
        heading.setObjectName("GeoStudioPaletteHeading")
        root.addWidget(heading)

        self.query = QLineEdit()
        self.query.setObjectName("GeoStudioPaletteQuery")
        self.query.setPlaceholderText("Np. skala, poligon, DXF, warstwy…")
        self.query.setClearButtonEnabled(True)
        self.query.textChanged.connect(self._refresh)
        self.query.installEventFilter(self)
        self.query.returnPressed.connect(self.activate_current)
        root.addWidget(self.query)

        self.results = QListWidget()
        self.results.setObjectName("GeoStudioPaletteResults")
        self.results.itemActivated.connect(self._activate)
        self.results.itemDoubleClicked.connect(self._activate)
        root.addWidget(self.results, 1)

        footer = QFrame()
        footer.setObjectName("GeoStudioPaletteFooter")
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(4, 4, 4, 4)
        footer_row.addWidget(QLabel("↑ ↓  Wybierz     Enter  Uruchom     Esc  Zamknij"))
        root.addWidget(footer)

    def eventFilter(self, watched, event):
        if watched is self.query and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                direction = 1 if key == Qt.Key.Key_Down else -1
                current = self.results.currentRow()
                for offset in range(1, self.results.count() + 1):
                    candidate = (current + direction * offset) % self.results.count()
                    item = self.results.item(candidate)
                    if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                        self.results.setCurrentRow(candidate)
                        break
                return True
        return super().eventFilter(watched, event)

    def set_commands(self, commands):
        """Load (label, QAction) pairs, retaining exact original action objects."""
        seen = set()
        self._commands = []
        for label, action in commands:
            if action is None or id(action) in seen or not label.strip():
                continue
            seen.add(id(action))
            self._commands.append((label.replace("&", "").strip(), action))
        self._refresh()

    def _refresh(self, *_):
        query = _fold(self.query.text().strip())
        tokens = query.split()
        matches = []
        for position, (name, action) in enumerate(self._commands):
            text = _fold(name)
            if all(token in text for token in tokens):
                priority = 0 if text.startswith(query) else 1
                matches.append((priority, position, name, action))
        matches.sort(key=lambda row: (row[0], row[1]))
        self.results.clear()
        for _priority, _position, name, action in matches:
            shortcut = action.shortcut().toString()
            title = name + (f"    ·    {shortcut}" if shortcut else "")
            item = QListWidgetItem(title)
            item.setToolTip(action.toolTip() or action.statusTip() or name)
            item.setData(Qt.ItemDataRole.UserRole, action)
            if not action.isEnabled():
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.results.addItem(item)
        for row in range(self.results.count()):
            if self.results.item(row).flags() & Qt.ItemFlag.ItemIsEnabled:
                self.results.setCurrentRow(row)
                break

    def activate_current(self):
        item = self.results.currentItem()
        if item is not None:
            self._activate(item)

    def _activate(self, item):
        action = item.data(Qt.ItemDataRole.UserRole)
        if action is None or not action.isEnabled():
            return
        self.accept()
        action.trigger()

    def open_palette(self):
        self.query.clear()
        self._refresh()
        self.open()
        self.query.setFocus(Qt.FocusReason.ShortcutFocusReason)
