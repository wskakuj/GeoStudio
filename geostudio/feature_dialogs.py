"""Small GEO-MAP-inspired selection, creation and text-replacement dialogs.

These dialogs operate on the existing native GEO-MAP code/attribute model.
They do not persist changes directly; the window owns the History transaction
and stores copies rather than overwriting the original .MAP.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import hypot

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
    QScrollArea, QTabWidget, QTreeWidget, QTreeWidgetItem, QHeaderView,
)

from .object_search import search_objects

FIELDS = ("A1", "A2", "A3", "A4", "A5", "A6", "TX")


def find_by_attributes(objects, code="", first=("A2", ""), second=("A1", ""),
                       join="and", *, case_sensitive=False, partial=False):
    """Select by code and up to two optional native attributes; blank = any."""
    code = code.strip()
    if code and (len(code) != 4 or not code.isdigit()):
        raise ValueError("Kod musi mieć dokładnie cztery cyfry.")
    if first[0] not in FIELDS or second[0] not in FIELDS:
        raise ValueError("Niedozwolona nazwa atrybutu.")
    if join not in {"and", "or"}:
        raise ValueError("Nieprawidłowy operator warunków.")
    result = []
    for obj in objects:
        if not obj.uid or (code and obj.code != code):
            continue
        tests = []
        for field, expected in (first, second):
            if not expected.strip():
                continue
            actual = obj.fields.get(field, "").strip()
            needle = expected.strip()
            if not case_sensitive:
                actual, needle = actual.casefold(), needle.casefold()
            tests.append(needle in actual if partial else actual == needle)
        if not tests or (all(tests) if join == "and" else any(tests)):
            result.append(obj)
    return result


class CodePickerDialog(QDialog):
    """Compact GEO-MAP-like code picker; use T to open, then draw."""

    def __init__(self, symbols, objects, *, default="5216", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Podaj kod tworzonego obiektu")
        self.resize(520, 215)
        layout = QVBoxLayout(self)
        layout.setSpacing(11)
        layout.addWidget(QLabel(
            "Wybierz symbol GEO-MAP albo wpisz jego czterocyfrowy kod. "
            "Nazwa i lista podpowiedzi aktualizują się automatycznie."))
        form = QFormLayout()
        self.code = QLineEdit(default)
        self.code.setMaxLength(4)
        self.code.setPlaceholderText("np. 5310")
        self.name = QLineEdit()
        self.name.setReadOnly(True)
        self.name.setPlaceholderText("Nazwa symbolu GEO-MAP")
        options = dict(symbols)
        for obj in objects:
            options.setdefault(obj.code, "Kod występujący na mapie")
        options.setdefault(default, "Kod obiektu")
        self.list = QComboBox()
        for code in sorted(options):
            self.list.addItem(f"{code} — {options[code]}", code)
        self.list.currentIndexChanged.connect(self._from_list)
        self.code.textChanged.connect(self._from_code)
        form.addRow("Kod", self.code)
        form.addRow("Nazwa", self.name)
        form.addRow("Wybór z listy", self.list)
        layout.addLayout(form)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                         QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._accept_code)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._options = options
        self._from_code(self.code.text())

    def _from_list(self, index):
        if index >= 0:
            self.code.setText(str(self.list.itemData(index)))

    def _from_code(self, text):
        self.name.setText(self._options.get(text, "Kod bez nazwy w bibliotece SYM"))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            len(text) == 4 and text.isdigit())
        index = self.list.findData(text)
        self.list.blockSignals(True)
        self.list.setCurrentIndex(index)
        self.list.blockSignals(False)

    def _accept_code(self):
        if len(self.code.text()) == 4 and self.code.text().isdigit():
            self.accept()


class AttributeQueryDialog(QDialog):
    """Query by code and optional A1/A2 conditions, then select or navigate."""

    def __init__(self, objects, *, code="", select_all=False, parent=None):
        super().__init__(parent)
        self.objects = objects
        self.matches = []
        self.setWindowTitle("Wyszukiwanie i zaznaczanie obiektów")
        self.resize(555, 300)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Wpisz kod, opcjonalnie podaj A1/A2. Puste warunki oznaczają wszystkie "
            "obiekty o danym kodzie."))
        form = QFormLayout()
        self.code = QLineEdit(code)
        self.code.setMaxLength(4)
        self.code.setPlaceholderText("np. 5310 — puste = wszystkie kody")
        form.addRow("Kod obiektu", self.code)
        self.field1, self.value1 = QComboBox(), QLineEdit()
        self.field2, self.value2 = QComboBox(), QLineEdit()
        for field in FIELDS:
            self.field1.addItem(field, field)
            self.field2.addItem(field, field)
        self.field1.setCurrentIndex(self.field1.findData("A2"))
        self.field2.setCurrentIndex(self.field2.findData("A1"))
        row1 = QWidget(); row1_layout = QHBoxLayout(row1)
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.addWidget(self.field1)
        row1_layout.addWidget(self.value1, 1)
        form.addRow("Warunek 1", row1)
        row2 = QWidget(); row2_layout = QHBoxLayout(row2)
        row2_layout.setContentsMargins(0, 0, 0, 0)
        row2_layout.addWidget(self.field2)
        row2_layout.addWidget(self.value2, 1)
        form.addRow("Warunek 2", row2)
        self.join = QComboBox()
        self.join.addItem("Oba warunki (I)", "and")
        self.join.addItem("Dowolny warunek (LUB)", "or")
        form.addRow("Łączenie", self.join)
        layout.addLayout(form)
        self.partial = QCheckBox("Wartość zawiera wpisany tekst (zamiast dokładnego dopasowania)")
        layout.addWidget(self.partial)
        self.case_sensitive = QCheckBox("Rozróżniaj wielkość liter")
        layout.addWidget(self.case_sensitive)
        self.select_all = QCheckBox("Zaznacz wszystkie znalezione obiekty")
        self.select_all.setChecked(select_all)
        layout.addWidget(self.select_all)
        self.preview = QLabel("Wpisz warunki i kliknij Znajdź.")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                    QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Znajdź i zaznacz")
        buttons.accepted.connect(self._accept_query)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_query(self):
        try:
            self.matches = find_by_attributes(
                self.objects, self.code.text(),
                (self.field1.currentData(), self.value1.text()),
                (self.field2.currentData(), self.value2.text()),
                self.join.currentData(),
                case_sensitive=self.case_sensitive.isChecked(),
                partial=self.partial.isChecked())
        except ValueError as exc:
            self.preview.setText("Błąd: " + str(exc))
            return
        self.preview.setText(f"Znaleziono: {len(self.matches)} obiektów.")
        self.accept()


@dataclass(frozen=True)
class ReplaceSpecification:
    field: str
    needle: str
    replacement: str
    all_objects: bool
    case_sensitive: bool


class ReplaceTextDialog(QDialog):
    def __init__(self, *, has_selection=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Zamiana frazy w atrybutach")
        self.resize(480, 210)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.old = QLineEdit()
        self.new = QLineEdit()
        self.field = QComboBox()
        for field in FIELDS:
            self.field.addItem(("Numer / opis (A2)" if field == "A2" else field), field)
        self.field.setCurrentIndex(self.field.findData("A2"))
        form.addRow("Fraza", self.old)
        form.addRow("W polu", self.field)
        form.addRow("Zamień na", self.new)
        self.scope = QComboBox()
        if has_selection:
            self.scope.addItem("Tylko zaznaczone obiekty", False)
        self.scope.addItem("Wszystkie obiekty na mapie", True)
        form.addRow("Zakres", self.scope)
        layout.addLayout(form)
        self.case_sensitive = QCheckBox("Rozróżniaj wielkość liter")
        layout.addWidget(self.case_sensitive)
        info = QLabel(
            "Przed zmianą GeoStudio pokaże liczbę pasujących obiektów i poprosi "
            "o potwierdzenie. Wszystkie zamiany można cofnąć jednym Ctrl+Z.")
        info.setWordWrap(True)
        layout.addWidget(info)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                    QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_replace)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept_replace(self):
        if self.old.text():
            self.accept()

    def specification(self):
        return ReplaceSpecification(
            self.field.currentData(), self.old.text(), self.new.text(),
            bool(self.scope.currentData()), self.case_sensitive.isChecked())


def replacement_plan(objects, spec: ReplaceSpecification):
    """Calculate exact new field values without changing any input object."""
    import re
    if spec.field not in FIELDS or not spec.needle:
        raise ValueError("Podaj poprawny atrybut i frazę do zamiany.")
    if any(c in spec.replacement for c in "\r\n]"):
        raise ValueError("Zamiennik nie może zawierać nowej linii ani ']'.")
    pattern = re.compile(re.escape(spec.needle), 0 if spec.case_sensitive else re.IGNORECASE)
    result = {}
    for obj in objects:
        old = obj.fields.get(spec.field, "")
        new = pattern.sub(lambda _match: spec.replacement, old)
        if old != new:
            result[(obj.uid, spec.field)] = new
    return result


class ObjectParametersDialog(QDialog):
    """Parameters for one GEO-MAP object; attributes editable, geometry read-only.

    Coordinates are deliberately not edited here. The P vertex tool applies
    topology validation and preserves the full undo history.
    """

    EDITABLE_FIELDS = ("A1", "A2", "A3", "A4", "A5", "A6", "TX", "MP", "KR")

    def __init__(self, obj, *, symbols=None, layer_name="", parent=None):
        super().__init__(parent)
        self.setObjectName("GeoStudioObjectParameters")
        self.setWindowTitle("Parametry aktywnego obiektu")
        self.resize(640, 600)
        self._original = {key: obj.fields.get(key, "")
                          for key in self.EDITABLE_FIELDS}
        self.entries = {}

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        name = (symbols or {}).get(obj.code, "Obiekt GEO-MAP")
        header = QLabel(f"<b>Kod {obj.code}</b> — {name}")
        header.setWordWrap(True)
        layout.addWidget(header)
        layer = QLabel(f"Warstwa: {layer_name or 'Nieznana'}    |    ID: {obj.uid or 'brak'}")
        layer.setWordWrap(True)
        layout.addWidget(layer)

        perimeter = sum(hypot(b.x - a.x, b.y - a.y)
                        for a, b in zip(obj.points, obj.points[1:]))
        metrics = f"Liczba punktów: {len(obj.points)}    |    Długość / obwód: {perimeter:.3f} m"
        if obj.area_m2 is not None:
            metrics += f"    |    Pole geometryczne: {obj.area_m2:,.2f} m²"
        metrics_label = QLabel(metrics)
        metrics_label.setWordWrap(True)
        layout.addWidget(metrics_label)

        tabs = QTabWidget(self)
        tabs.setObjectName("GeoStudioObjectParametersTabs")
        fields_scroll = QScrollArea(tabs)
        fields_scroll.setWidgetResizable(True)
        fields_scroll.setFrameShape(QScrollArea.NoFrame)
        fields_page = QWidget(fields_scroll)
        form = QFormLayout(fields_page)
        form.setSpacing(9)
        for key in self.EDITABLE_FIELDS:
            entry = QLineEdit(obj.fields.get(key, ""), fields_page)
            entry.setObjectName(f"object_field_{key}")
            entry.setPlaceholderText("—")
            form.addRow(key, entry)
            self.entries[key] = entry
        other = {k: v for k, v in obj.fields.items()
                 if k not in self.EDITABLE_FIELDS}
        for key, value in sorted(other.items()):
            if key == "ID":
                continue
            label = QLabel(value)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(key + " (tylko odczyt)", label)
        fields_scroll.setWidget(fields_page)
        tabs.addTab(fields_scroll, "Atrybuty opisowe")

        coords = QTreeWidget(tabs)
        coords.setObjectName("GeoStudioObjectCoordinates")
        coords.setHeaderLabels(["Nr", "X", "Y", "P", "Oznaczenie"])
        coords.setAlternatingRowColors(True)
        coords.setRootIsDecorated(False)
        coords.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        coords.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        coords.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        coords.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        coords.header().setSectionResizeMode(4, QHeaderView.Stretch)
        for idx, point in enumerate(obj.points, 1):
            QTreeWidgetItem(coords, [str(idx), f"{point.x:.3f}",
                                     f"{point.y:.3f}", str(point.point_type),
                                     point.label])
        tabs.addTab(coords, "Współrzędne punktów")
        layout.addWidget(tabs, 1)
        hint = QLabel("Współrzędne zmieniaj narzędziem Węzły [P]. "
                      "Zmiany atrybutów można cofnąć przez Ctrl+Z.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Save |
                                    QDialogButtonBox.Cancel, parent=self)
        buttons.button(QDialogButtonBox.Save).setText("Zapisz zmiany")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def changed_fields(self):
        """Return only changed supported attributes, never synthetic defaults."""
        return {key: entry.text() for key, entry in self.entries.items()
                if entry.text() != self._original[key]}
