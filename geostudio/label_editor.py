"""Per-code map label editor. Keeps all edits in GeoStudio visual sidecars."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QFontComboBox, QSpinBox, QDialogButtonBox, QPushButton,
    QColorDialog, QHBoxLayout,
)

ATTRIBUTE_FIELDS = ("A1", "A2", "A3", "A4", "A5", "A6", "TX", "MP", "KR")


def default_label_fields(code: str):
    """Mimic the existing map renderer unless the user explicitly changes it."""
    if code == "5310":
        return {"A1", "A2"}
    if code in {"5216", "5220", "5230"}:
        return {"A2"}
    if code == "5214":
        return {"A3"}
    if code.startswith("7") or code in {"6900", "6000", "6301"}:
        return {"TX"}
    return set()


class AttributeLabelsDialog(QDialog):
    """Pick any attributes and their independent font, size, and color."""

    def __init__(self, code: str, current: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Etykietowanie atrybutów — kod {code}")
        self.setMinimumSize(725, 510)
        self.code = code
        current_fields = (current or {}).get("fields", {})
        root = QVBoxLayout(self)
        hint = QLabel(
            "Zaznacz pola widoczne na mapie. Każdy atrybut ma własną "
            "czcionkę, rozmiar i kolor. Zmiany dotyczą całego kodu, "
            "bez modyfikacji oryginalnego pliku MAP.")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.table = QTableWidget(len(ATTRIBUTE_FIELDS), 5, self)
        self.table.setObjectName("GeoStudioAttributeLabelsTable")
        self.table.setHorizontalHeaderLabels(
            ["Widoczny", "Atrybut", "Czcionka", "Rozmiar", "Kolor (HEX)"])
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(39)
        self.table.setWordWrap(False)
        self.table.setAlternatingRowColors(True)
        for row, field in enumerate(ATTRIBUTE_FIELDS):
            saved = current_fields.get(field, {})
            toggle = QTableWidgetItem()
            toggle.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            initial = field in default_label_fields(code)
            toggle.setCheckState(
                Qt.Checked if saved.get("visible", initial) else Qt.Unchecked)
            self.table.setItem(row, 0, toggle)
            name_item = QTableWidgetItem(field)
            name_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(row, 1, name_item)
            font = QFontComboBox(self.table)
            font.setCurrentFont(QFont(saved.get("font", "Segoe UI")))
            self.table.setCellWidget(row, 2, font)
            size = QSpinBox(self.table)
            size.setRange(6, 96)
            size.setValue(int(saved.get("size", 16)))
            self.table.setCellWidget(row, 3, size)
            color = QColor(saved.get("color", "#243A45"))
            color_item = QTableWidgetItem(
                color.name().upper() if color.isValid() else "#243A45")
            color_item.setBackground(color if color.isValid()
                                     else QColor("#243A45"))
            self.table.setItem(row, 4, color_item)
            picker = QPushButton(color_item.text(), self.table)
            picker.setObjectName(f"GeoStudioLabelColor_{field}")
            picker.setToolTip(f"Kliknij, aby wybrać kolor etykiety {field} z palety")
            picker.setStyleSheet(
                "QPushButton { background-color: " + color_item.text() +
                "; color: " + ("#FFFFFF" if color.lightness() < 140 else "#152231") +
                "; border: 1px solid #738393; border-radius: 5px; padding: 3px; }")
            picker.clicked.connect(lambda _checked=False, idx=row: self.change_color(idx))
            self.table.setCellWidget(row, 4, picker)
        root.addWidget(self.table)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Zastosuj etykiety")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def change_color(self, row=None):
        if row is None:
            row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 4)
        color = QColorDialog.getColor(
            QColor(item.text() if item else "#243A45"),
            self, "Kolor etykiety")
        if color.isValid():
            item.setText(color.name().upper())
            item.setBackground(color)
            picker = self.table.cellWidget(row, 4)
            if picker is not None:
                picker.setText(item.text())
                picker.setStyleSheet(
                    "QPushButton { background-color: " + item.text() +
                    "; color: " + ("#FFFFFF" if color.lightness() < 140
                                  else "#152231") +
                    "; border: 1px solid #738393; border-radius: 5px; padding: 3px; }")

    def specification(self):
        result = {}
        for row, field in enumerate(ATTRIBUTE_FIELDS):
            color = QColor(self.table.item(row, 4).text())
            if not color.isValid():
                raise ValueError(f"Nieprawidłowy kolor etykiety {field}.")
            font = self.table.cellWidget(row, 2).currentFont().family()
            size = self.table.cellWidget(row, 3).value()
            visible = self.table.item(row, 0).checkState() == Qt.Checked
            result[field] = {
                "visible": visible, "font": font[:100], "size": size,
                "color": color.name().upper(),
            }
        return {"fields": result}
