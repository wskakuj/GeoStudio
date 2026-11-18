"""GeoStudio desktop workspace theme.

Only Qt widgets are styled here. GEO-MAP scene items, colours, line widths and
exported imagery are deliberately left untouched.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap


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
        "window": "#111927",
        "surface": "#1A2636",
        "toolbar": "#172232",
        "text": "#E7EEF8",
        "muted": "#A0B0C4",
        "border": "#33455C",
        "hover": "#263B54",
        "accent": "#70B7FF",
        "accent_hover": "#4F9BEB",
        "accent_soft": "#213E5A",
        "selection": "#294765",
        "selection_text": "#F3F9FF",
        "input": "#162233",
        "alt": "#202F43",
        "scroll": "#435A75",
        "disabled": "#73859B",
    },
}


def theme_stylesheet(theme: str) -> str:
    """Return a Windows-friendly Qt stylesheet for the specified mode."""
    c = PALETTES[theme if theme in PALETTES else "light"]
    # Use token replacement instead of brace interpolation: QSS uses braces
    # extensively, and this makes the whole design palette easy to tune.
    css = """
QMainWindow, QDialog { background-color: @window@; color: @text@; }
QWidget { color: @text@; font-family: 'Segoe UI'; font-size: 10pt; }
QMenuBar { background: @toolbar@; padding: 5px 9px; border-bottom: 1px solid @border@; }
QMenuBar::item { padding: 7px 12px; border-radius: 6px; background: transparent; }
QMenuBar::item:selected, QMenuBar::item:pressed { background: @hover@; }
QMenu { background: @surface@; border: 1px solid @border@; padding: 7px; }
QMenu::item { padding: 7px 28px 7px 14px; border-radius: 5px; }
QMenu::item:selected { background: @selection@; color: @selection_text@; }
QMenu::separator { height: 1px; background: @border@; margin: 6px 12px; }

QToolBar { background: @toolbar@; border: none; spacing: 5px; padding: 6px 9px; }
QToolBar#GeoStudioToolsToolbar { border-top: 1px solid @border@; padding-top: 5px; padding-bottom: 6px; }
QToolBar#GeoStudioPanelToolbar { border-left: 1px solid @border@; padding: 8px 5px; spacing: 7px; }
QToolBar::separator { background: @border@; width: 1px; height: 20px; margin: 3px 8px; }
QToolButton { border: 1px solid transparent; border-radius: 7px; padding: 8px 11px; background: transparent; color: @text@; font-weight: 550; }
QToolButton:hover { background: @hover@; border-color: @border@; }
QToolButton:pressed, QToolButton:checked { background: @accent_soft@; border-color: @accent@; color: @accent@; }
QToolButton:disabled { color: @disabled@; }
QToolButton::menu-indicator { image: none; }

QDockWidget { background: @surface@; border: 1px solid @border@; font-weight: 600; }
QDockWidget::title { background: @toolbar@; padding: 13px 12px; border-bottom: 1px solid @border@; text-align: left; }
QDockWidget::close-button, QDockWidget::float-button { background: transparent; }
QMainWindow::separator { background: @window@; width: 5px; height: 5px; }

QTreeWidget, QTreeView, QListWidget { background: @surface@; alternate-background-color: @alt@; border: 1px solid @border@; border-radius: 7px; padding: 3px; outline: none; }
QTreeView::item { min-height: 25px; padding: 3px 5px; }
QTreeView::item:hover { background: @hover@; }
QTreeView::item:selected { background: @selection@; color: @selection_text@; }
QHeaderView::section { background: @toolbar@; border: 0; border-right: 1px solid @border@; border-bottom: 1px solid @border@; padding: 8px; color: @muted@; font-weight: 650; }

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit { background: @input@; color: @text@; border: 1px solid @border@; border-radius: 7px; padding: 7px 9px; selection-background-color: @accent_soft@; }
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
QLabel#GeoStudioBrand { color: @text@; font-size: 16pt; font-weight: 750; padding: 2px 8px 2px 3px; }
QLabel#GeoStudioBrandAccent { color: @accent@; font-size: 9pt; font-weight: 700; padding: 0 2px; }
QLabel#GeoStudioToolbarCaption, QLabel#GeoStudioSectionHeading { color: @muted@; font-size: 9pt; font-weight: 700; padding: 5px 6px; }
QLabel#GeoStudioPanelHint { color: @muted@; font-size: 9pt; padding: 2px 5px; }
QLabel#GeoStudioCompilationScale { color: @accent@; font-weight: 700; border-left: 1px solid @border@; padding-left: 12px; }
QComboBox#GeoStudioScale { min-height: 24px; }
QGraphicsView#GeoStudioCanvas { border: 1px solid @border@; border-radius: 9px; }

QScrollBar:vertical { background: @alt@; width: 11px; margin: 0; }
QScrollBar:horizontal { background: @alt@; height: 11px; margin: 0; }
QScrollBar::handle { background: @scroll@; border-radius: 5px; min-height: 28px; min-width: 28px; margin: 2px; }
QScrollBar::handle:hover { background: @muted@; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QSplitter::handle { background: @window@; }
QToolTip { background: @surface@; color: @text@; border: 1px solid @border@; padding: 7px; }
"""
    for key, value in c.items():
        css = css.replace(f"@{key}@", value)
    return css


def ui_icon(glyph: str, theme: str = "light") -> QIcon:
    """Small monochrome tool icons without external graphics or font assets."""
    palette = PALETTES[theme if theme in PALETTES else "light"]
    pixmap = QPixmap(44, 44)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(2)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QColor(palette["accent"]))
    font = QFont("Segoe UI Symbol")
    font.setPixelSize(27)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    return QIcon(pixmap)
