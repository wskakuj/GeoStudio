"""GeoStudio desktop workspace theme.

Only Qt widgets are styled here. GEO-MAP scene items, colours, line widths and
exported imagery are deliberately left untouched.
"""
from __future__ import annotations

from PySide6.QtGui import QIcon
from .ui_icons import draw_icon


PALETTES = {
    "light": {
        "window": "#EDF2F8",
        "surface": "#FFFFFF",
        "toolbar": "#F8FAFD",
        "text": "#1B293C",
        "muted": "#61758D",
        "border": "#D7E1EB",
        "hover": "#EAF2FC",
        "accent": "#1267B1",
        "accent_hover": "#095392",
        "accent_soft": "#DFEDFA",
        "selection": "#D8E9FB",
        "selection_text": "#173A60",
        "input": "#FFFFFF",
        "alt": "#F5F8FC",
        "scroll": "#C6D3E1",
        "disabled": "#9AABBA",
    },
    "dark": {
        "window": "#0E131C",
        "surface": "#1B2430",
        "toolbar": "#141C27",
        "text": "#F0F4FA",
        "muted": "#A6B5C8",
        "border": "#334254",
        "hover": "#26364A",
        "accent": "#82BDFF",
        "accent_hover": "#60A8F2",
        "accent_soft": "#203C58",
        "selection": "#284661",
        "selection_text": "#FFFFFF",
        "input": "#17212E",
        "alt": "#202C3B",
        "scroll": "#3B5069",
        "disabled": "#8294A9",
    },
}


STYLE_CLASSIC = "classic"
STYLE_MODERN = "modern"
STYLES = (STYLE_CLASSIC, STYLE_MODERN)
STYLE_TITLES = {STYLE_CLASSIC: "Klasyczny", STYLE_MODERN: "Nowoczesny"}

# Palette of the modern style, taken from the prototype the project owner
# supplied. Keys mirror PALETTES so the same QSS selectors keep working; the
# extra keys (elevated, accent_alt, warning, danger, overlay) are used by the
# overlay below.
MODERN_PALETTES = {
    "dark": {
        "window": "#0F141A",
        "surface": "#161D26",
        "toolbar": "#1C2531",
        "elevated": "#222D3C",
        "text": "#F1F5F9",
        "muted": "#94A3B8",
        "dim": "#7C8DA3",
        "border": "rgba(148, 163, 184, 0.16)",
        "border_strong": "rgba(148, 163, 184, 0.30)",
        "hover": "rgba(148, 163, 184, 0.10)",
        "accent": "#10B981",
        "accent_hover": "#34D399",
        "accent_soft": "rgba(16, 185, 129, 0.14)",
        "accent_alt": "#38BDF8",
        "accent_alt_soft": "rgba(56, 189, 248, 0.15)",
        "selection": "rgba(56, 189, 248, 0.20)",
        "selection_text": "#E8F6FF",
        "input": "#0B1015",
        "alt": "#131A23",
        "scroll": "#2B3947",
        "disabled": "#5A6A7D",
        "warning": "#F59E0B",
        "danger": "#FB7185",
    },
    "light": {
        "window": "#F8FAFC",
        "surface": "#FFFFFF",
        "toolbar": "#F1F5F9",
        "elevated": "#E2E8F0",
        "text": "#0F172A",
        "muted": "#475569",
        "dim": "#64748B",
        "border": "#E2E8F0",
        "border_strong": "#CBD5E1",
        "hover": "rgba(15, 23, 42, 0.05)",
        "accent": "#059669",
        "accent_hover": "#047857",
        "accent_soft": "rgba(5, 150, 105, 0.11)",
        "accent_alt": "#0284C7",
        "accent_alt_soft": "rgba(2, 132, 199, 0.12)",
        "selection": "rgba(2, 132, 199, 0.16)",
        "selection_text": "#0B2A45",
        "input": "#F1F5F9",
        "alt": "#F8FAFC",
        "scroll": "#CBD5E1",
        "disabled": "#94A3B8",
        "warning": "#D97706",
        "danger": "#E11D48",
    },
}

# Overlay applied on top of the classic selectors. Only properties Qt can
# actually render are used: no shadows, no transitions, no letter-spacing.
_MODERN_QSS = """
/* --- modern style overlay: compact chrome, pill controls, cards --- */
QWidget { font-family: 'Segoe UI'; font-size: 9.5pt; }
QMainWindow, QDialog { background-color: @window@; }
QMenuBar { background: @surface@; border-bottom: 1px solid @border@; padding: 3px 8px; }
QMenuBar::item { padding: 5px 10px; border-radius: 6px; }
QMenu { background: @elevated@; border: 1px solid @border_strong@; border-radius: 8px; padding: 6px; }
QMenu::item { padding: 6px 26px 6px 12px; border-radius: 6px; }
QMenu::separator { background: @border@; margin: 5px 10px; }

QToolBar { background: @surface@; border: none; spacing: 4px; padding: 4px 8px; }
QToolBar#GeoStudioToolsToolbar { border-top: 1px solid @border@; }
QToolBar::separator { background: @border@; width: 1px; height: 18px; margin: 2px 6px; }
QToolButton { border: 1px solid transparent; border-radius: 7px; padding: 6px 9px; font-weight: 600; }
QToolButton:hover { background: @hover@; border-color: @border@; }
QToolButton:pressed, QToolButton:checked { background: @accent_soft@; border-color: @accent@; color: @accent@; }

QDockWidget { border: 1px solid @border@; }
QDockWidget::title { background: @surface@; padding: 8px 11px; border-bottom: 1px solid @border@; font-size: 9pt; font-weight: 700; }

QTreeWidget, QTreeView, QListWidget { background: @surface@; border: 1px solid @border@; border-radius: 8px; padding: 2px; }
QTreeView::item { min-height: 26px; padding: 4px 6px; border-radius: 5px; }
QHeaderView::section { background: @toolbar@; border: 0; border-bottom: 1px solid @border@; padding: 6px; color: @dim@; font-size: 8.5pt; }

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit { background: @input@; border: 1px solid @border@; border-radius: 7px; padding: 6px 8px; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus { border: 1px solid @accent@; }
QComboBox QAbstractItemView { background: @elevated@; border: 1px solid @border_strong@; border-radius: 6px; }

QPushButton { background: @toolbar@; border: 1px solid @border@; border-radius: 7px; padding: 6px 10px; font-weight: 600; }
QPushButton:hover { background: @hover@; border-color: @accent@; }
QPushButton:pressed { background: @accent_soft@; }
QPushButton#GeoStudioPrimaryButton { background: @accent@; color: #04120C; border-color: @accent@; font-weight: 700; }
QPushButton#GeoStudioPrimaryButton:hover { background: @accent_hover@; }

QStatusBar { background: @surface@; border-top: 1px solid @border@; min-height: 26px; }
QStatusBar QLabel { color: @dim@; padding: 2px 8px; }
QLabel#GeoStudioModeBadge, QLabel#GeoStudioSelectionBadge { background: @accent_soft@; color: @accent@; border-radius: 999px; padding: 4px 10px; font-weight: 700; }
QLabel#GeoStudioBrand { font-size: 13pt; font-weight: 750; }
QLabel#GeoStudioBrandAccent { color: @accent@; font-size: 8pt; font-weight: 700; }
QLabel#GeoStudioToolbarCaption, QLabel#GeoStudioSectionHeading { color: @dim@; font-size: 8pt; font-weight: 700; padding: 4px 5px; }
QLabel#GeoStudioPanelHint { color: @dim@; font-size: 8.5pt; }
QLabel#GeoStudioCompilationScale { color: @accent@; font-weight: 700; }

QScrollBar:vertical { background: transparent; width: 9px; }
QScrollBar:horizontal { background: transparent; height: 9px; }
QScrollBar::handle { background: @scroll@; border-radius: 4px; min-height: 24px; min-width: 24px; margin: 1px; }
QScrollBar::handle:hover { background: @muted@; }

QTabBar::tab { padding: 8px 13px; font-size: 9pt; border-bottom: 2px solid transparent; color: @dim@; }
QTabBar::tab:selected { color: @accent@; border-bottom: 2px solid @accent@; }
QTabWidget::pane { border: 1px solid @border@; border-radius: 8px; top: -1px; }

QFrame#GeoStudioMapTabsFrame { background: @surface@; border-bottom: 1px solid @border@; }
QTabBar#GeoStudioMapDocumentTabs::tab {
    background: transparent; border: 1px solid transparent; border-bottom: 2px solid transparent;
    border-top-left-radius: 7px; border-top-right-radius: 7px;
    padding: 6px 16px 6px 11px; margin-right: 2px; min-width: 96px; max-width: 230px;
    font-size: 8.5pt; color: @dim@;
}
QTabBar#GeoStudioMapDocumentTabs::tab:selected {
    background: @toolbar@; border-color: @border@; border-bottom: 2px solid @accent@; color: @text@; font-weight: 700;
}
QToolButton#GeoStudioNewMapTabButton { min-width: 26px; min-height: 24px; font-size: 14pt; border-radius: 6px; }
QGraphicsView#GeoStudioCanvas { border: 1px solid @border@; border-radius: 8px; }

QDialog#GeoStudioCommandPalette { background: @surface@; border: 1px solid @border_strong@; border-radius: 10px; }
QLineEdit#GeoStudioPaletteQuery { min-height: 32px; padding: 6px 10px; font-size: 10.5pt; border: 1px solid @accent@; border-radius: 7px; }
QListWidget#GeoStudioPaletteResults::item { min-height: 28px; padding: 5px 8px; border-radius: 5px; }
"""


def _build_stylesheet(c: dict) -> str:
    """Build the full QSS for one palette.

    Kept separate from the palette lookup so a second visual style can reuse
    exactly the same selectors and differ only by colours and an overlay.
    """
    # Use token replacement instead of brace interpolation: QSS uses braces
    # extensively, and this makes the whole design palette easy to tune.
    css = """
QMainWindow, QDialog { background-color: @window@; color: @text@; }
QWidget { color: @text@; font-family: 'Segoe UI'; font-size: 10.5pt; }
QMenuBar { background: @toolbar@; padding: 5px 9px; border-bottom: 1px solid @border@; }
QMenuBar::item { padding: 7px 12px; border-radius: 6px; background: transparent; }
QMenuBar::item:selected, QMenuBar::item:pressed { background: @hover@; }
QMenu { background: @surface@; border: 1px solid @border@; padding: 7px; }
QMenu::item { padding: 7px 28px 7px 14px; border-radius: 5px; }
QMenu::item:selected { background: @selection@; color: @selection_text@; }
QMenu::separator { height: 1px; background: @border@; margin: 6px 12px; }

QToolBar { background: @toolbar@; border: none; spacing: 6px; padding: 7px 12px; }
QToolBar#GeoStudioToolsToolbar { border-top: 1px solid @border@; padding-top: 5px; padding-bottom: 6px; }
QToolBar#GeoStudioPanelToolbar { border-left: 1px solid @border@; padding: 10px 4px; spacing: 8px; }
QToolBar::separator { background: @border@; width: 1px; height: 20px; margin: 3px 8px; }
QToolButton { border: 1px solid transparent; border-radius: 8px; padding: 9px 12px; background: transparent; color: @text@; font-weight: 600; }
QToolButton:hover { background: @hover@; border-color: @border@; }
QToolButton:pressed, QToolButton:checked { background: @accent_soft@; border-color: @accent@; color: @accent@; }
QToolButton:disabled { color: @disabled@; }
QToolButton::menu-indicator { image: none; }

QDockWidget { background: @surface@; border: 1px solid @border@; font-weight: 600; }
QDockWidget::title { background: @toolbar@; padding: 12px 14px; border-bottom: 1px solid @border@; text-align: left; font-size: 10.5pt; font-weight: 700; }
QDockWidget::close-button, QDockWidget::float-button { background: transparent; }
QMainWindow::separator { background: @window@; width: 5px; height: 5px; }

QTreeWidget, QTreeView, QListWidget { background: @surface@; alternate-background-color: @alt@; border: 1px solid @border@; border-radius: 7px; padding: 3px; outline: none; }
QTreeView::item { min-height: 29px; padding: 5px 7px; }
QTreeView::item:hover { background: @hover@; }
QTreeView::item:selected { background: @selection@; color: @selection_text@; }
QHeaderView::section { background: @toolbar@; border: 0; border-right: 1px solid @border@; border-bottom: 1px solid @border@; padding: 8px; color: @muted@; font-weight: 650; }

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit { background: @input@; color: @text@; border: 1px solid @border@; border-radius: 8px; padding: 9px 10px; selection-background-color: @accent_soft@; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus { border: 1px solid @accent@; }
QComboBox::drop-down { border: none; width: 23px; }
QComboBox QAbstractItemView { background: @surface@; color: @text@; selection-background-color: @selection@; selection-color: @selection_text@; border: 1px solid @border@; }
QPushButton { background: @toolbar@; border: 1px solid @border@; border-radius: 7px; padding: 9px 12px; font-weight: 600; }
QPushButton:hover { background: @hover@; border-color: @accent@; }
QPushButton:pressed { background: @accent_soft@; }
QPushButton:disabled { color: @disabled@; }
QPushButton#GeoStudioPrimaryButton { background: @accent@; color: #FFFFFF; border-color: @accent@; }
QPushButton#GeoStudioPrimaryButton:hover { background: @accent_hover@; border-color: @accent_hover@; }

QStatusBar { background: @surface@; border-top: 1px solid @border@; color: @muted@; min-height: 30px; }
QStatusBar::item { border: none; }
QStatusBar QLabel { color: @muted@; padding: 4px 8px; }
QLabel#GeoStudioModeBadge, QLabel#GeoStudioSelectionBadge { background: @accent_soft@; color: @accent@; border-radius: 6px; padding: 6px 10px; font-weight: 700; }
QLabel#GeoStudioBrand { color: @text@; font-size: 15pt; font-weight: 750; padding: 2px 5px 2px 3px; }
QLabel#GeoStudioBrandAccent { color: @accent@; font-size: 9pt; font-weight: 700; padding: 0 2px; }
QLabel#GeoStudioToolbarCaption, QLabel#GeoStudioSectionHeading { color: @muted@; font-size: 9pt; font-weight: 700; padding: 5px 6px; }
QLabel#GeoStudioPanelHint { color: @muted@; font-size: 9pt; padding: 2px 5px; }
QLabel#GeoStudioCompilationScale { color: @accent@; font-weight: 700; border-left: 1px solid @border@; padding-left: 12px; }
QComboBox#GeoStudioScale { min-height: 24px; }
QGraphicsView#GeoStudioCanvas { border: 1px solid @border@; border-radius: 6px; }

QScrollBar:vertical { background: @alt@; width: 11px; margin: 0; }
QScrollBar:horizontal { background: @alt@; height: 11px; margin: 0; }
QScrollBar::handle { background: @scroll@; border-radius: 5px; min-height: 28px; min-width: 28px; margin: 2px; }
QScrollBar::handle:hover { background: @muted@; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QSplitter::handle { background: @window@; }
QTabWidget#GeoStudioInspectorTabs::pane { background: @surface@; border: 0; border-top: 1px solid @border@; }
QTabBar::tab { background: transparent; color: @muted@; border: none; border-bottom: 2px solid transparent; padding: 11px 16px; font-size: 10pt; font-weight: 600; }
QTabBar::tab:selected { color: @accent@; border-bottom: 2px solid @accent@; }
QTabBar::tab:hover:!selected { background: @hover@; color: @text@; }
QFrame#GeoStudioSelectionCard { background: @alt@; border: 1px solid @border@; border-radius: 9px; }
QLabel#GeoStudioObjectTitle { color: @text@; font-size: 13pt; font-weight: 750; padding: 1px 2px; }
QLabel#GeoStudioObjectMetrics { color: @accent@; font-size: 10pt; font-weight: 700; padding: 9px 1px 5px 1px; }
QPushButton#GeoStudioQuickEdit, QPushButton#GeoStudioQuickCopy {
    border: 1px solid @border@; border-radius: 8px; background: @surface@;
    padding: 9px 11px; font-size: 9pt; font-weight: 700;
}
QPushButton#GeoStudioQuickEdit:hover, QPushButton#GeoStudioQuickCopy:hover {
    background: @hover@; border-color: @accent@; color: @accent@;
}
QLabel#GeoStudioObjectDetails { color: @muted@; font-size: 9.5pt; padding: 1px 2px; }
QLabel#GeoStudioLayerSummary { color: @muted@; font-size: 9pt; }
QLabel#GeoStudioEmptyHint { color: @muted@; font-size: 10pt; padding: 5px; }
QLabel#GeoStudioColorPreview { border: 1px solid @border@; border-radius: 9px; min-height: 58px; padding: 9px; font-size: 10pt; font-weight: 700; }
QLabel#GeoStudioCoordinateReadout { color: @text@; font-family: 'Consolas'; font-size: 10pt; padding: 3px 9px; }
QLabel#GeoStudioFileHint { color: @muted@; font-size: 9pt; padding: 3px 8px; }
QToolBar#GeoStudioFileToolbar QToolButton#GeoStudioPrimaryTool { background: @accent@; color: #FFFFFF; border: 1px solid @accent@; border-radius: 8px; padding: 9px 14px; }
QToolBar#GeoStudioFileToolbar QToolButton#GeoStudioPrimaryTool:hover { background: @accent_hover@; border-color: @accent_hover@; }
QPushButton#GeoStudioSubtleButton { background: transparent; color: @muted@; border: 1px solid @border@; padding: 6px 9px; }
QPushButton#GeoStudioSubtleButton:hover { color: @text@; background: @hover@; }
QLabel#GeoStudioInspectorHint { color: @muted@; font-size: 9pt; padding: 6px 1px; }

QToolTip { background: @surface@; color: @text@; border: 1px solid @border@; padding: 7px; }
"""
    css += """
/* Modern GIS workspace: structural surfaces and contextual rail */
QWidget#GeoStudioWorkspace { background: @window@; }
QFrame#GeoStudioDocumentHeader {
    background: @surface@; border: 1px solid @border@; border-radius: 12px;
}
QLabel#GeoStudioDocumentEyebrow {
    color: @muted@; font-size: 8pt; letter-spacing: 1px; font-weight: 750;
}
QLabel#GeoStudioDocumentName {
    color: @text@; font-size: 12.5pt; font-weight: 750; padding-top: 2px;
}
QLabel#GeoStudioHeaderCaption {
    color: @muted@; font-size: 8pt; font-weight: 750;
    padding-right: 4px;
}
QComboBox#GeoStudioCanvasFilter {
    border: 1px solid @border@; background: @alt@; padding: 7px 11px;
    border-radius: 7px; min-height: 25px;
}
QFrame#GeoStudioToolRail {
    background: @surface@; border: 1px solid @border@; border-radius: 12px;
}
QToolBar#GeoStudioToolPalette {
    background: transparent; padding: 0; margin: 0; spacing: 3px;
    border: none; min-width: 90px;
}
QToolBar#GeoStudioToolPalette QToolButton {
    background: transparent; border: 1px solid transparent;
    border-radius: 9px; font-size: 9pt; font-weight: 600;
    padding: 8px 2px; margin: 0 3px;
    min-height: 42px; color: @muted@;
}
QToolBar#GeoStudioToolPalette QToolButton:hover {
    background: @hover@; color: @text@; border-color: @border@;
}
QToolBar#GeoStudioToolPalette QToolButton:checked {
    color: @accent@; background: @accent_soft@;
    border-color: @accent@;
}
QToolBar#GeoStudioToolPalette::separator {
    background: @border@; height: 1px; width: 64px; margin: 5px 10px;
}
QLabel#GeoStudioRailFootnote {
    color: @muted@; font-size: 8pt; border-top: 1px solid @border@;
    padding: 7px 0; font-weight: 600;
}
QFrame#GeoStudioMapSurface {
    background: #FFFFFF; border: 1px solid @border@; border-radius: 9px;
}
QGraphicsView#GeoStudioCanvas {
    border: none; border-radius: 8px; background: #FFFFFF;
}
QLabel#GeoStudioCanvasFooter {
    color: @muted@; font-size: 8.5pt; padding: 1px 8px;
}
QFrame#GeoStudioDocumentHeader QToolButton {
    color: @text@; background: @alt@; border: 1px solid @border@;
    border-radius: 8px; padding: 9px 13px; font-size: 9.5pt;
}
QFrame#GeoStudioDocumentHeader QToolButton:hover {
    background: @hover@; border-color: @accent@;
}
QToolButton#GeoStudioFocusButton {
    color: @accent@; background: @accent_soft@;
    border: 1px solid @accent@; font-weight: 700;
}
QToolBar#GeoStudioFileToolbar {
    padding: 9px 14px; spacing: 6px; background: @toolbar@;
    border-bottom: 1px solid @border@;
}
QToolBar#GeoStudioFileToolbar QToolButton {
    border-radius: 8px; font-weight: 650; padding: 9px 11px;
}
QDockWidget { border: none; background: @surface@; }
QDockWidget::title {
    background: @surface@; color: @text@;
    padding: 14px 13px; font-size: 10pt;
    border-bottom: 1px solid @border@;
}
QTreeView, QTreeWidget, QListWidget {
    background: @surface@; alternate-background-color: @alt@;
    border: 1px solid @border@; border-radius: 9px; padding: 4px;
}
QHeaderView::section {
    background: @surface@; border: 0; border-bottom: 1px solid @border@;
    color: @muted@; padding: 9px; font-size: 9pt; font-weight: 700;
}
QFrame#GeoStudioSelectionCard {
    background: @alt@; border: 1px solid @border@; border-radius: 11px;
}
QLineEdit, QSpinBox, QComboBox {
    border: 1px solid @border@; border-radius: 8px;
    padding: 9px 10px; background: @input@;
}
QPushButton#GeoStudioPrimaryButton {
    border-radius: 8px; min-height: 24px; padding: 10px 14px;
    background: @accent@; color: #0C1B2A; font-weight: 750;
}
QPushButton#GeoStudioPrimaryButton:hover { background: @accent_hover@; }
QStatusBar {
    background: @surface@; color: @muted@;
    border-top: 1px solid @border@; min-height: 32px;
}
"""
    css += """
/* ArcGIS-inspired command ribbon: task tabs above grouped tools. */
QToolBar#GeoStudioRibbonToolbar {
    background: @surface@; border: 0; padding: 0; margin: 0; spacing: 0;
}
QWidget#GeoStudioGISRibbon {
    background: @surface@; border: 0;
}
QFrame#GeoStudioRibbonHeader {
    background: @toolbar@; border-bottom: 1px solid @border@;
}
QLabel#GeoStudioRibbonBrand {
    color: @text@; font-size: 15pt; font-weight: 800;
    letter-spacing: -0.3px;
}
QLabel#GeoStudioRibbonSubtitle {
    color: @muted@; font-size: 8.5pt; font-weight: 700;
    padding-left: 12px; border-left: 1px solid @border@;
}
QLabel#GeoStudioRibbonDocument {
    color: @muted@; font-size: 9pt; padding: 2px 4px;
}
QTabWidget#GeoStudioRibbonTabs::pane {
    background: @surface@; border: 0; border-bottom: 1px solid @border@;
}
QTabWidget#GeoStudioRibbonTabs QTabBar {
    background: @toolbar@;
}
QTabWidget#GeoStudioRibbonTabs QTabBar::tab {
    background: @toolbar@; color: @muted@; border: 0;
    border-bottom: 3px solid transparent;
    padding: 9px 19px; margin: 0 2px;
    font-size: 10pt; font-weight: 650;
}
QTabWidget#GeoStudioRibbonTabs QTabBar::tab:selected {
    background: @surface@; color: @accent@;
    border-bottom: 3px solid @accent@;
}
QTabWidget#GeoStudioRibbonTabs QTabBar::tab:hover:!selected {
    background: @hover@; color: @text@;
}
QScrollArea#GeoStudioRibbonScroller,
QWidget#GeoStudioRibbonSurface {
    background: @surface@; border: none;
}
QFrame#GeoStudioRibbonGroup {
    border: 0; border-right: 1px solid @border@; background: transparent;
    margin-right: 2px;
}
QLabel#GeoStudioRibbonGroupCaption {
    font-size: 8pt; color: @muted@; font-weight: 600;
    padding: 2px 3px 0 3px;
}
QToolButton#GeoStudioRibbonLarge, QToolButton#GeoStudioRibbonSmall {
    background: transparent; border: 1px solid transparent; border-radius: 6px;
    color: @text@; font-weight: 550;
}
QToolButton#GeoStudioRibbonLarge {
    padding: 5px 6px; font-size: 9pt;
}
QToolButton#GeoStudioRibbonSmall {
    padding: 4px 7px; font-size: 9pt; text-align: left;
}
QToolButton#GeoStudioRibbonLarge:hover, QToolButton#GeoStudioRibbonSmall:hover {
    background: @hover@; border-color: @border@;
}
QToolButton#GeoStudioRibbonLarge:checked, QToolButton#GeoStudioRibbonSmall:checked,
QToolButton#GeoStudioRibbonLarge:pressed, QToolButton#GeoStudioRibbonSmall:pressed {
    background: @accent_soft@; border-color: @accent@; color: @accent@;
}
QToolButton#GeoStudioRibbonLarge:disabled, QToolButton#GeoStudioRibbonSmall:disabled {
    color: @disabled@;
}
QWidget#GeoStudioWorkspace { background: @surface@; }
QFrame#GeoStudioDocumentHeader {
    background: @surface@; border: none; border-bottom: 1px solid @border@;
    border-radius: 0;
}
QLabel#GeoStudioDocumentEyebrow {
    color: @accent@; font-size: 8pt; letter-spacing: 0.6px; font-weight: 700;
}
QLabel#GeoStudioDocumentName {
    color: @text@; font-size: 10.5pt; font-weight: 650; padding: 0;
}
QFrame#GeoStudioMapSurface {
    background: #FFFFFF; border: 0; border-radius: 0;
}
QGraphicsView#GeoStudioCanvas {
    background: #FFFFFF; border: none; border-radius: 0;
}
QDockWidget {
    border: none; background: @surface@;
}
QDockWidget::title {
    background: @toolbar@; color: @text@; font-size: 10pt;
    font-weight: 700; border-bottom: 1px solid @border@;
    padding: 12px 14px;
}
QTreeWidget#GeoStudioLayerTree {
    border: none; border-radius: 0;
}
"""
    css += """
/* Quick Access commands, search, and ribbon collapse -- compact GIS header. */
QToolButton#GeoStudioQuickAccessButton {
    background: transparent; border: 1px solid transparent;
    border-radius: 5px; padding: 4px;
    min-width: 24px; min-height: 24px;
}
QToolButton#GeoStudioQuickAccessButton:hover {
    background: @hover@; border-color: @border@;
}
QToolButton#GeoStudioQuickAccessButton:disabled { color: @disabled@; }
QToolButton#GeoStudioCommandSearch {
    background: @input@; color: @muted@; border: 1px solid @border@;
    border-radius: 7px; text-align: left;
    padding: 7px 12px; font-size: 9pt;
    min-width: 180px;
}
QToolButton#GeoStudioCommandSearch:hover {
    border-color: @accent@; background: @hover@; color: @text@;
}
QToolButton#GeoStudioRibbonCollapse {
    background: transparent; border-radius: 5px; padding: 5px 6px;
    color: @muted@; font-size: 9pt;
}
QToolButton#GeoStudioRibbonCollapse:hover {
    color: @text@; background: @hover@;
}
QDialog#GeoStudioCommandPalette {
    background: @surface@; border: 1px solid @border@;
}
QLabel#GeoStudioPaletteHeading {
    font-size: 14pt; font-weight: 750; color: @text@;
}
QLineEdit#GeoStudioPaletteQuery {
    min-height: 38px; padding: 7px 12px; font-size: 11pt;
    border: 1px solid @accent@; background: @input@;
}
QListWidget#GeoStudioPaletteResults {
    background: @surface@; border: 1px solid @border@;
    border-radius: 8px; padding: 4px;
}
QListWidget#GeoStudioPaletteResults::item {
    min-height: 30px; padding: 6px 9px; border-radius: 5px;
}
QListWidget#GeoStudioPaletteResults::item:selected {
    background: @selection@; color: @selection_text@;
}
QFrame#GeoStudioPaletteFooter {
    border-top: 1px solid @border@; color: @muted@;
}
"""
    css += """
/* Workspace document tabs: ArcGIS-like, compact and high-contrast. */
QFrame#GeoStudioMapTabsFrame {
    background: @toolbar@; border: none;
    border-bottom: 1px solid @border@;
}
QTabBar#GeoStudioMapDocumentTabs {
    background: transparent;
}
QTabBar#GeoStudioMapDocumentTabs::tab {
    background: @toolbar@; border: 1px solid @border@;
    border-bottom: 2px solid transparent; color: @muted@;
    border-top-left-radius: 7px; border-top-right-radius: 7px;
    padding: 8px 20px 8px 13px; margin-right: 3px;
    min-width: 105px; max-width: 245px;
    font-weight: 550; font-size: 9.5pt;
}
QTabBar#GeoStudioMapDocumentTabs::tab:selected {
    background: @surface@; color: @text@;
    border-bottom: 2px solid @accent@; font-weight: 700;
}
QTabBar#GeoStudioMapDocumentTabs::tab:hover:!selected {
    background: @hover@; color: @text@;
}
QToolButton#GeoStudioNewMapTabButton {
    background: transparent; color: @text@;
    font-size: 16pt; font-weight: 650;
    min-width: 32px; min-height: 28px;
    padding: 0px; border: 1px solid transparent;
    border-radius: 6px;
}
QToolButton#GeoStudioNewMapTabButton:hover {
    background: @hover@; border-color: @border@;
}
"""
    for key, value in c.items():
        css = css.replace(f"@{key}@", value)
    return css


def theme_stylesheet(theme: str) -> str:
    """Classic GeoStudio style (unchanged output)."""
    return _build_stylesheet(PALETTES[theme if theme in PALETTES else "light"])


def modern_stylesheet(theme: str) -> str:
    """Modern style: same selectors, new palette plus a compact overlay."""
    key = theme if theme in MODERN_PALETTES else "light"
    return _build_stylesheet(MODERN_PALETTES[key]) + _render_modern(_MODERN_QSS, MODERN_PALETTES[key])


def _render_modern(template: str, c: dict) -> str:
    css = template
    for token, value in c.items():
        css = css.replace(f"@{token}@", value)
    return css


def stylesheet(theme: str, style: str = STYLE_CLASSIC) -> str:
    """Single entry point used by the window."""
    if style == STYLE_MODERN:
        return modern_stylesheet(theme)
    return theme_stylesheet(theme)


def ui_icon(glyph: str, theme: str = "light") -> QIcon:
    """Render semantic vector pictograms; legacy symbols remain accepted."""
    c = PALETTES[theme if theme in PALETTES else "light"]
    return draw_icon(glyph, c["text"])
