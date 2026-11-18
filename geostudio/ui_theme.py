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
        "window": "#121B28",
        "surface": "#1D2A39",
        "toolbar": "#1A2534",
        "text": "#EDF4FC",
        "muted": "#B1C0D1",
        "border": "#394D65",
        "hover": "#293D55",
        "accent": "#72BFFF",
        "accent_hover": "#4BA9F8",
        "accent_soft": "#244969",
        "selection": "#305273",
        "selection_text": "#FFFFFF",
        "input": "#182434",
        "alt": "#233246",
        "scroll": "#506783",
        "disabled": "#899CB1",
    },
}


def theme_stylesheet(theme: str) -> str:
    """Return a Windows-friendly Qt stylesheet for the specified mode."""
    c = PALETTES[theme if theme in PALETTES else "light"]
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
    for key, value in c.items():
        css = css.replace(f"@{key}@", value)
    return css


def ui_icon(glyph: str, theme: str = "light") -> QIcon:
    """Render semantic vector pictograms; legacy symbols remain accepted."""
    c = PALETTES[theme if theme in PALETTES else "light"]
    return draw_icon(glyph, c["text"])
