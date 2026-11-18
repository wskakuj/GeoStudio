"""ArcGIS Pro-inspired, task-oriented ribbon for the GeoStudio Qt workspace.

The ribbon displays existing QAction objects instead of reimplementing any
operations. It has no dependencies on the GEO-MAP parser or the map scene.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
    QTabWidget, QToolButton, QVBoxLayout, QWidget,
)
from .ui_theme import ui_icon


class RibbonGroup(QFrame):
    """A labelled group of large commands and compact vertical command stacks."""

    def __init__(self, title: str, ribbon: "GISRibbon"):
        super().__init__(ribbon)
        self.setObjectName("GeoStudioRibbonGroup")
        self._ribbon = ribbon
        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 7, 9, 3)
        layout.setSpacing(4)
        self.commands = QHBoxLayout()
        self.commands.setSpacing(3)
        self.commands.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(self.commands, 1)
        caption = QLabel(title)
        caption.setObjectName("GeoStudioRibbonGroupCaption")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(caption)

    def action(self, command, icon: str, *, large: bool = False,
               text: str | None = None):
        button = QToolButton(self)
        button.setObjectName("GeoStudioRibbonLarge" if large else "GeoStudioRibbonSmall")
        button.setAutoRaise(False)
        button.setDefaultAction(command)
        if text:
            button.setText(text)
        button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextUnderIcon if large
            else Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setIconSize(QSize(24, 24) if large else QSize(17, 17))
        if large:
            button.setMinimumSize(84, 66)
            button.setMaximumHeight(72)
        else:
            button.setMinimumSize(115, 28)
            button.setMaximumHeight(30)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setIcon(ui_icon(icon, self._ribbon.theme))
        self._ribbon._icons.append((button, icon))
        self.commands.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        return button

    def menu(self, title: str, menu, icon: str, *, large: bool = False):
        button = QToolButton(self)
        button.setObjectName("GeoStudioRibbonLarge" if large else "GeoStudioRibbonSmall")
        button.setText(title)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextUnderIcon if large
            else Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        button.setIconSize(QSize(24, 24) if large else QSize(17, 17))
        if large:
            button.setMinimumSize(84, 66)
            button.setMaximumHeight(72)
        else:
            button.setMinimumSize(115, 28)
            button.setMaximumHeight(30)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setIcon(ui_icon(icon, self._ribbon.theme))
        self._ribbon._icons.append((button, icon))
        self.commands.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        return button

    def stack(self, *commands):
        """Stack up to three compact buttons in the same ribbon column."""
        stack = QWidget(self)
        stack.setObjectName("GeoStudioRibbonStack")
        layout = QVBoxLayout(stack)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for command, icon, text in commands:
            button = QToolButton(stack)
            button.setObjectName("GeoStudioRibbonSmall")
            button.setDefaultAction(command)
            if text:
                button.setText(text)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setIconSize(QSize(16, 16))
            button.setMinimumWidth(124)
            button.setMinimumHeight(27)
            button.setMaximumHeight(28)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setIcon(ui_icon(icon, self._ribbon.theme))
            self._ribbon._icons.append((button, icon))
            layout.addWidget(button)
        layout.addStretch(1)
        self.commands.addWidget(stack, 0, Qt.AlignmentFlag.AlignVCenter)
        return stack

    def control(self, widget, *, minimum_width: int = 160):
        widget.setMinimumWidth(minimum_width)
        self.commands.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        return widget


class GISRibbon(QWidget):
    """Ribbon navigation with Map/Edit/Data/View/Export pages and reusable actions."""

    TAB_NAMES = ("Mapa", "Edycja", "Dane", "Widok", "Eksport")

    def __init__(self, theme: str = "light", parent=None):
        super().__init__(parent)
        self.setObjectName("GeoStudioGISRibbon")
        self.theme = theme
        self._icons = []
        self.collapsed = False
        self._pages: dict[str, tuple[QWidget, QHBoxLayout]] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame(self)
        header.setObjectName("GeoStudioRibbonHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 4, 13, 4)
        row.setSpacing(12)
        brand = QLabel("GeoStudio")
        brand.setObjectName("GeoStudioRibbonBrand")
        row.addWidget(brand)
        division = QLabel("GIS  /  EDYTOR MAP")
        division.setObjectName("GeoStudioRibbonSubtitle")
        row.addWidget(division)
        self.quick_access = QHBoxLayout()
        self.quick_access.setSpacing(2)
        row.addLayout(self.quick_access)
        row.addStretch(1)
        self.command_search = QToolButton(self)
        self.command_search.setObjectName("GeoStudioCommandSearch")
        self.command_search.setText("Szukaj poleceń   Ctrl+K")
        self.command_search.setIcon(ui_icon("search", theme))
        self.command_search.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.command_search.setCursor(Qt.CursorShape.PointingHandCursor)
        self.command_search.setToolTip("Wyszukaj i uruchom dowolne polecenie GeoStudio (Ctrl+K)")
        row.addWidget(self.command_search)
        self.document_state = QLabel("Brak otwartej mapy")
        self.document_state.setObjectName("GeoStudioRibbonDocument")
        self.document_state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.document_state)
        self.collapse_button = QToolButton(self)
        self.collapse_button.setObjectName("GeoStudioRibbonCollapse")
        self.collapse_button.setText("Zwiń")
        self.collapse_button.setToolTip("Zwiń lub rozwiń wstążkę (Ctrl+F1)")
        self.collapse_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.collapse_button.clicked.connect(self.toggle_collapsed)
        row.addWidget(self.collapse_button)
        outer.addWidget(header)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("GeoStudioRibbonTabs")
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.TabPosition.North)
        self.tabs.setMinimumHeight(151)
        self.tabs.setMaximumHeight(164)
        self.tabs.tabBarDoubleClicked.connect(
            lambda index: self.toggle_collapsed() if index >= 0 else None)
        self.tabs.tabBarClicked.connect(self._on_tab_clicked)
        outer.addWidget(self.tabs)

        for title in self.TAB_NAMES:
            scroll = QScrollArea()
            scroll.setObjectName("GeoStudioRibbonScroller")
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            surface = QWidget()
            surface.setObjectName("GeoStudioRibbonSurface")
            groups = QHBoxLayout(surface)
            groups.setContentsMargins(9, 3, 9, 2)
            groups.setSpacing(2)
            groups.setAlignment(Qt.AlignmentFlag.AlignLeft)
            scroll.setWidget(surface)
            self.tabs.addTab(scroll, title)
            self._pages[title] = (surface, groups)

    def add_quick_action(self, action, icon: str):
        """Reuse an existing QAction in a compact Quick Access Toolbar."""
        button = QToolButton(self)
        button.setObjectName("GeoStudioQuickAccessButton")
        button.setAutoRaise(True)
        button.setDefaultAction(action)
        button.setIcon(ui_icon(icon, self.theme))
        button.setIconSize(QSize(17, 17))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._icons.append((button, icon))
        self.quick_access.addWidget(button)
        return button

    def set_command_search(self, callback):
        self.command_search.clicked.connect(callback)

    def _on_tab_clicked(self, index: int):
        if index >= 0 and self.collapsed:
            self.set_collapsed(False)

    def toggle_collapsed(self):
        self.set_collapsed(not self.collapsed)

    def set_collapsed(self, collapsed: bool):
        """Reduce ribbon height to its tab strip without removing QAction state."""
        self.collapsed = bool(collapsed)
        height = 35 if self.collapsed else 151
        self.tabs.setMinimumHeight(height)
        self.tabs.setMaximumHeight(36 if self.collapsed else 164)
        self.collapse_button.setText("Rozwiń" if self.collapsed else "Zwiń")
        self.collapse_button.setToolTip(
            "Rozwiń wstążkę (Ctrl+F1)" if self.collapsed
            else "Zwiń wstążkę (Ctrl+F1)")

    def group(self, tab: str, title: str) -> RibbonGroup:
        group = RibbonGroup(title, self)
        self._pages[tab][1].addWidget(group)
        return group

    def select_tab(self, title: str):
        if title in self.TAB_NAMES:
            self.tabs.setCurrentIndex(self.TAB_NAMES.index(title))
            if self.collapsed:
                self.set_collapsed(False)

    def set_document(self, name: str | None, *, dirty: bool = False):
        from pathlib import Path
        name = Path(name).name if name else "Brak otwartej mapy"
        self.document_state.setText(name + ("  •  niezapisane zmiany" if dirty else ""))
        self.document_state.setToolTip(name)

    def refresh_icons(self, theme: str):
        self.theme = theme
        for button, name in self._icons:
            button.setIcon(ui_icon(name, theme))
        self.command_search.setIcon(ui_icon("search", theme))
