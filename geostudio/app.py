"""First desktop prototype. Rendering is deliberately approximate, data is preserved.

Safety: never overwrite original MAP; saved files require a separate filename.
Full symbol / raster / export parity with GEO-MAP is NOT implemented.
"""
from __future__ import annotations
import sys
import math
import os
import tempfile
import hashlib
import json
from pathlib import Path
from collections import defaultdict

try:
    from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, QSettings, Signal
    from PySide6.QtGui import QAction, QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QImage, QTransform, QActionGroup
    from PySide6.QtWidgets import (QApplication, QMainWindow, QFileDialog, QGraphicsView, QGraphicsScene,
        QGraphicsPathItem, QGraphicsEllipseItem, QGraphicsPixmapItem, QGraphicsSimpleTextItem, QGraphicsItem, QDockWidget,
        QTreeWidget, QTreeWidgetItem, QToolBar, QMessageBox, QStatusBar, QInputDialog, QMenu,
        QLabel, QWidget, QVBoxLayout, QHeaderView, QSplitter, QComboBox,
        QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QHBoxLayout, QPushButton, QSpinBox, QColorDialog)
except ImportError as exc:
    raise SystemExit('Zainstaluj GUI: python -m pip install -e .\nBrakuje PySide6') from exc

from .geomap import GeoMap, GeoObject, library_layers, library_symbols, library_colors, resolve_layer
from .interactions import find_snap, polygon_is_valid, closest_point_on_edge
from .geometry_index import GeometryIndex
from .object_search import search_objects
from .visual_styles import parse_fill_code, fill_code, load_styles, write_styles, sidecar_path

APP_QSS = """
QMainWindow, QDockWidget, QWidget { background-color: #101826; color: #dce7f5; font: 10pt 'Segoe UI'; }
QMenuBar, QMenu {background: #192437; color: #edf3ff; padding: 5px;}
QMenu::item:selected { background: #29446a; }
QToolBar { background: #1a2638; border: none; padding: 5px; spacing: 6px; }
QToolButton { border: 1px solid #31445d; border-radius: 6px; background: #26364e; color: #f3f7ff; padding: 7px; }
QToolButton:hover { background: #34527b; }
QDockWidget::title {background: #1a2638; padding: 9px; font-weight: 600;}
QTreeWidget {background: #162235; alternate-background-color: #192940; border: 0; selection-background-color: #2b547f; color: #e4ecf6;}
QHeaderView::section {background: #202f43; color: #cddbf0; padding: 8px; border: none; }
QStatusBar {background: #182437; color: #cbd8ed;}
QLabel {padding: 3px;}
QDialog, QMessageBox {background: #192437;}
QLineEdit {background: #23364f; color: white; border: 1px solid #466080; padding: 6px;}
"""


class MapView(QGraphicsView):
    """QGIS-style mutually exclusive canvas tools, no implicit scroll-hand dragging.

    The earlier code delegated selection to ScrollHandDrag, so a click could be
    treated as a pan. All edit actions now handle real viewport events directly.
    """
    coordinate = Signal(float, float)
    canvas_click = Signal(float, float, bool, bool)
    canvas_context = Signal(float, float)
    point_for_polygon = Signal(float, float)
    polygon_hover = Signal(float, float)
    finish_polygon = Signal()
    undo_polygon_point = Signal()
    cancel_action = Signal()
    vertex_hover = Signal(float, float, int)
    vertex_commit = Signal(float, float, int)
    edge_insert = Signal(float, float)
    zoom_changed = Signal()

    def __init__(self, scene):
        super().__init__(scene)
        self.draw_mode = False
        self.edit_mode = False
        self.pan_mode = False
        self.edit_points = []
        self.dragged_vertex = None
        self._pan_button = None
        self._pan_last = None
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.setBackgroundBrush(QBrush(QColor('#f7f9fb')))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.ArrowCursor)

    def _position(self, event):
        pt = self.mapToScene(event.position().toPoint())
        return pt.x(), -pt.y()

    def wheelEvent(self, event):
        """Zoom at cursor, independent of the active map tool or Qt anchor state."""
        delta = event.angleDelta().y()
        if not delta:
            event.accept()
            return
        factor = 1.2 ** (delta / 120.0)
        current = abs(self.transform().m11())
        if not (1e-5 <= current * factor <= 4000):
            event.accept()
            return
        cursor = event.position().toPoint()
        fixed_scene_point = self.mapToScene(cursor)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.scale(factor, factor)
        # Scrollbar correction is explicit: map the same world point after
        # scaling, then bring it back under the original cursor pixel.
        shifted = self.mapFromScene(fixed_scene_point)
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() + shifted.x() - cursor.x())
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() + shifted.y() - cursor.y())
        self.zoom_changed.emit()
        event.accept()

    def scrollContentsBy(self, dx, dy):
        # Panning moves scrollbars many times; it is NOT a zoom change.
        # Calling the expensive label layout here made wheel/pan unstable.
        super().scrollContentsBy(dx, dy)

    def mouseMoveEvent(self, event):
        if self._pan_button is not None:
            # Middle-button drag is temporary pan in SELECT/DRAW/EDIT/PAN.
            pos = event.position().toPoint()
            step = pos - self._pan_last
            self._pan_last = pos
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - step.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - step.y())
            event.accept()
            return
        x, y = self._position(event)
        self.coordinate.emit(x, y)
        if self.draw_mode:
            self.polygon_hover.emit(x, y)
        elif self.edit_mode and self.dragged_vertex is not None:
            self.vertex_hover.emit(x, y, self.dragged_vertex)
        event.accept()

    def mousePressEvent(self, event):
        self.setFocus()
        # Consistent explicit mouse handling avoids QGraphicsView.ScrollHandDrag
        # swallowing selection clicks and unexpectedly altering wheel anchors.
        if event.button() == Qt.MiddleButton or (self.pan_mode and event.button() == Qt.LeftButton):
            self._pan_button = event.button()
            self._pan_last = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        x, y = self._position(event)
        if self.draw_mode:
            if event.button() == Qt.RightButton:
                self.finish_polygon.emit()
            elif event.button() == Qt.LeftButton:
                self.point_for_polygon.emit(x, y)
        elif self.edit_mode:
            if event.button() == Qt.LeftButton:
                pos = event.position().toPoint()
                distances = [(self.mapFromScene(QPointF(px, -py)) - pos).manhattanLength()
                             for px, py in self.edit_points]
                if distances:
                    idx = min(range(len(distances)), key=distances.__getitem__)
                    if distances[idx] <= 18:
                        self.dragged_vertex = idx
                        self.vertex_hover.emit(x, y, idx)
                    else:
                        self.edge_insert.emit(x, y)
                else:
                    self.edge_insert.emit(x, y)
        elif event.button() == Qt.RightButton:
            self.canvas_context.emit(x, y)
        elif event.button() == Qt.LeftButton:
            self.canvas_click.emit(x, y, bool(event.modifiers() & Qt.AltModifier),
                                   bool(event.modifiers() & Qt.ControlModifier))
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._pan_button is not None and event.button() == self._pan_button:
            self._pan_button = None
            self._pan_last = None
            self.setCursor(Qt.OpenHandCursor if self.pan_mode else
                           Qt.CrossCursor if (self.draw_mode or self.edit_mode) else Qt.ArrowCursor)
            event.accept()
            return
        if self.edit_mode and self.dragged_vertex is not None and event.button() == Qt.LeftButton:
            x, y = self._position(event)
            idx = self.dragged_vertex
            self.dragged_vertex = None
            self.vertex_commit.emit(x, y, idx)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if self.draw_mode:
            self.finish_polygon.emit()
        elif self.pan_mode:
            super().mouseDoubleClickEvent(event)
        else:
            event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.draw_mode:
            self.finish_polygon.emit()
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            if self.draw_mode:
                self.undo_polygon_point.emit()
            elif self.edit_mode or self.pan_mode:
                self.cancel_action.emit()
            else:
                super().keyPressEvent(event)
                return
            event.accept()
            return
        super().keyPressEvent(event)


class GeoStudioWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('GeoStudio v0.6 — eksperymentalny edytor GEO-MAP')
        self.resize(1450, 900)
        self.settings = QSettings('GeoStudio', 'GeoStudio')
        self.doc: GeoMap | None=None
        self.catalog: dict[str,str]={}
        self.symbols: dict[str,str]={}
        self.palette: dict[str,tuple[int,int,int]]={}
        self.items_by_layer:dict[str,list]=defaultdict(list)
        self.graphics_for_uid={}
        self.visual_styles = {}
        self.selected_uids = []
        self.highlight_items = []
        self.labels=[]
        self.labels_enabled = True
        self.hide_multipart_connectors = True
        self.layer_for_uid = {}
        self.hidden_layers = set()
        self.geometry_index = GeometryIndex(())
        self.select_code_filter = None
        self._last_pick_pos = None
        self._last_pick_candidates = ()
        self._auto_copy_path = None
        self._auto_copy_digest = None
        self._auto_style_digest = None
        self.highlight_item=None
        self.draft_item=None
        self.snap_marker=None
        self.current_snap=None
        self.edit_uid=''
        self.edit_handles=[]
        self.draft_points=[]
        self.layers_tree=None
        self.current_polygon:list[tuple[float,float]]=[]
        self.polygon_code='5216'
        self.map_scene=QGraphicsScene(self)
        # Custom feature picking handles overlapping objects without Qt selection.
        self.view=MapView(self.map_scene)
        self.view.coordinate.connect(self.on_coordinate)
        self.view.canvas_click.connect(self.select_at)
        self.view.canvas_context.connect(self.show_objects_here)
        self.view.polygon_hover.connect(self.preview_polygon)
        self.view.vertex_hover.connect(self.preview_vertex)
        self.view.vertex_commit.connect(self.commit_vertex)
        self.view.edge_insert.connect(self.insert_vertex_at)
        self.view.cancel_action.connect(self.cancel_edit)
        self.view.zoom_changed.connect(self.update_label_visibility)
        self.view.point_for_polygon.connect(self.add_polygon_point)
        self.view.finish_polygon.connect(self.finish_polygon)
        self.view.undo_polygon_point.connect(self.undo_last_polygon_point)
        self.setCentralWidget(self.view)
        self._setup_menu()
        self._setup_docks()
        self.status=QStatusBar();self.setStatusBar(self.status)
        self.status.showMessage('Otwórz mapę GEO-MAP, aby rozpocząć. Zapis odbywa się tylko do nowego pliku.')
        self.setStyleSheet(APP_QSS)

    def _action(self,label,callback,shortcut=None):
        a=QAction(label,self)
        a.triggered.connect(callback)
        if shortcut:a.setShortcut(shortcut)
        return a

    def _setup_menu(self):
        fm=self.menuBar().addMenu('&Plik')
        actions=[('Otwórz MAP…',self.open_map,'Ctrl+O'),('Wczytaj biblioteki SYM/LAY/CDF…',self.open_catalogs,None),
                 ('Zapisz jako MAP…',self.save_map,'Ctrl+Shift+S'),('Dodaj raster z plikiem world…',self.add_raster,None),
                 ('Eksportuj obraz JPG/PNG/TIFF…',self.export_image,None),('Eksportuj DXF (uproszczony)…',self.export_dxf,None)]
        for label,fn,keys in actions: fm.addAction(self._action(label,fn,keys))
        fm.addSeparator();fm.addAction(self._action('Zakończ',self.close,'Ctrl+Q'))
        em=self.menuBar().addMenu('&Edycja')
        em.addAction(self._action('Zaznacz obiekt',self.cancel_edit,'S'))
        em.addAction(self._action('Przesuwanie mapy',self.start_pan,'H'))
        em.addAction(self._action('Rysuj poligon',self.start_polygon,'P'))
        em.addAction(self._action('Edytuj wierzchołki poligonu',self.start_vertex_edit,'E'))
        self.finish_action = self._action('Zakończ i zapisz poligon',self.finish_polygon,'Return')
        em.addAction(self.finish_action)
        self.finish_action.setEnabled(False)
        em.addAction(self._action('Zakończ narzędzie (S)',self.cancel_edit))
        em.addAction(self._action('Edytuj atrybut zaznaczonego obiektu…',self.edit_selected,'F2'))
        self.delete_action = self._action('Usuń zaznaczony obiekt', self.delete_selected, 'Delete')
        em.addAction(self.delete_action)
        em.addAction(self._action('Zaznacz wszystkie obiekty tego kodu', self.select_all_same_code, 'Ctrl+H'))
        em.addAction(self._action('Szukaj obiektu', self.show_search, 'Ctrl+F'))
        vm=self.menuBar().addMenu('&Widok')
        self.view_menu = vm
        vm.addAction(self._action('Dopasuj widok do mapy',self.fit_all,'Ctrl+0'))
        self.multipart_action = vm.addAction('Ukryj łączniki między częściami obiektu (P 0)')
        self.multipart_action.setCheckable(True)
        self.multipart_action.setChecked(True)
        self.multipart_action.toggled.connect(self.toggle_multipart_connectors)
        self.labels_action = vm.addAction('Podpisy A1/A2 (widoczność)')
        self.labels_action.setCheckable(True)
        self.labels_action.setChecked(True)
        self.labels_action.toggled.connect(self.set_labels_enabled)
        self.all_labels_action = vm.addAction('Pokaż wszystkie podpisy (również nakładające się)')
        self.all_labels_action.setCheckable(True)
        self.all_labels_action.setChecked(False)
        self.all_labels_action.toggled.connect(lambda _checked: self.update_label_visibility())
        self.snap_action = em.addAction('Przyciąganie do punktów i odcinków')
        self.snap_action.setCheckable(True)
        self.snap_action.setChecked(True)
        toolbar=QToolBar('Narzędzia',self)
        self.main_toolbar = toolbar
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        for label,fn in [('📂 Otwórz',self.open_map),('💾 Zapisz jako',self.save_map),
                         ('◎ Cała mapa',self.fit_all), ('▧ Raster',self.add_raster),
                         ('↗ DXF',self.export_dxf), ('⬇ Obraz',self.export_image)]:
            toolbar.addAction(self._action(label,fn))
        toolbar.addSeparator()
        self.tool_actions = {}
        group = QActionGroup(self)
        group.setExclusive(True)
        for key, label, fn in [
            ('select','⌖ Zaznacz [S]',self.cancel_edit),
            ('pan','✋ Przesuń [H]',self.start_pan),
            ('draw','⬡ Poligon [P]',self.start_polygon),
            ('edit','✥ Wierzchołki [E]',self.start_vertex_edit),
        ]:
            action = self._action(label, fn)
            action.setCheckable(True)
            group.addAction(action)
            toolbar.addAction(action)
            self.tool_actions[key] = action
        self.tool_actions['select'].setChecked(True)
        self.finish_toolbar_action = self._action('✓ Zakończ poligon [Enter]', self.finish_polygon)
        toolbar.addAction(self.finish_toolbar_action)
        self.finish_toolbar_action.setVisible(False)
        self.undo_toolbar_action = self._action('↶ Cofnij punkt [Esc]', self.undo_last_polygon_point)
        toolbar.addAction(self.undo_toolbar_action)
        self.undo_toolbar_action.setVisible(False)
        toolbar.addSeparator()
        toolbar.addAction(self.snap_action)
        toolbar.addAction(self.labels_action)
        self.selector = QComboBox()
        self.selector.setToolTip('Ogranicz zaznaczanie do określonych obiektów, jak w QGIS')
        self.selector.addItem('Wszystkie obiekty', None)
        self.selector.addItem('Działki 5216', '5216')
        self.selector.addItem('Użytki 5230', '5230')
        self.selector.currentIndexChanged.connect(self.change_select_filter)
        toolbar.addWidget(self.selector)

    def _setup_docks(self):
        self.selected_uid = ''
        self.layers_dock = QDockWidget('Warstwy GEO-MAP', self)
        self.layers_dock.setObjectName('GeoStudioLayersDock')
        self.layers_tree = QTreeWidget()
        self.layers_tree.setHeaderLabels(['Warstwa', 'Obiekty'])
        self.layers_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.layers_tree.itemChanged.connect(self.on_layer_toggle)
        self.layers_dock.setWidget(self.layers_tree)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.layers_dock)

        self.properties_dock = QDockWidget('Właściwości obiektu', self)
        self.properties_dock.setObjectName('GeoStudioPropertiesDock')
        prop_root = QWidget(self.properties_dock)
        prop_layout = QVBoxLayout(prop_root)
        self.props = QTreeWidget()
        self.props.setHeaderLabels(['Pole', 'Wartość'])
        self.props.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.props.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.props.itemDoubleClicked.connect(self.edit_property)
        prop_layout.addWidget(self.props, 3)
        self.selected_count_label = QLabel('Brak zaznaczenia')
        prop_layout.addWidget(self.selected_count_label)
        prop_layout.addWidget(QLabel('Wypełnienie poligonów (styl GeoStudio)'))
        form = QFormLayout()
        self.fill_entry = QLineEdit('#7899B5@25')
        self.fill_entry.setToolTip('Kod #RRGGBB@krycie%, np. #D94848@40')
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(0, 100)
        self.opacity_spin.setSuffix(' % krycia')
        self.opacity_spin.setValue(25)
        self.opacity_spin.valueChanged.connect(self._sync_fill_opacity)
        form.addRow('Kod koloru', self.fill_entry)
        form.addRow('Krycie', self.opacity_spin)
        prop_layout.addLayout(form)
        style_buttons = QHBoxLayout()
        for title, fn in [('🎨 Paleta', self.choose_fill_color),
                          ('Kopiuj kod', self.copy_fill_code),
                          ('Zastosuj', self.apply_fill_style)]:
            button = QPushButton(title)
            button.clicked.connect(fn)
            style_buttons.addWidget(button)
        prop_layout.addLayout(style_buttons)
        self.properties_dock.setWidget(prop_root)
        self.addDockWidget(Qt.RightDockWidgetArea, self.properties_dock)

        self.search_dock = QDockWidget('Wyszukaj obiekty', self)
        self.search_dock.setObjectName('GeoStudioSearchDock')
        search_root = QWidget(self.search_dock)
        search_layout = QVBoxLayout(search_root)
        search_form = QFormLayout()
        self.search_code = QLineEdit()
        self.search_code.setPlaceholderText('np. 5310 lub 5216')
        self.search_field = QComboBox()
        for field in ('A1','A2','A3','A4','A5','A6','TX','ID','*'):
            self.search_field.addItem('Dowolne pole' if field == '*' else field, field)
        self.search_value = QLineEdit()
        self.search_value.setPlaceholderText('np. bx albo 29/16')
        search_form.addRow('Kod obiektu', self.search_code)
        search_form.addRow('Atrybut', self.search_field)
        search_form.addRow('Wartość =', self.search_value)
        search_layout.addLayout(search_form)
        find_button = QPushButton('⌕ Znajdź na mapie')
        find_button.clicked.connect(self.run_search)
        search_layout.addWidget(find_button)
        self.search_value.returnPressed.connect(self.run_search)
        self.search_code.returnPressed.connect(self.run_search)
        self.search_summary = QLabel('Wpisz kod i wartość atrybutu')
        search_layout.addWidget(self.search_summary)
        self._search_uids = []
        self.search_results = QTreeWidget()
        self.search_results.setHeaderLabels(['Kod', 'A1', 'A2'])
        self.search_results.itemClicked.connect(self.select_search_result)
        search_layout.addWidget(self.search_results, 1)
        select_results = QPushButton('Zaznacz wszystkie wyniki')
        select_results.clicked.connect(self.select_search_results)
        search_layout.addWidget(select_results)
        self.search_dock.setWidget(search_root)
        self.addDockWidget(Qt.RightDockWidgetArea, self.search_dock)
        self.search_dock.hide()

        self.info_dock = self._help_dock()
        self.info_dock.setObjectName('GeoStudioInfoDock')
        self.addDockWidget(Qt.BottomDockWidgetArea, self.info_dock)

        panels = self.view_menu.addMenu('Panele')
        self.panel_toolbar = QToolBar('Pokaż/ukryj panele', self)
        self.panel_toolbar.setMovable(False)
        self.addToolBar(Qt.RightToolBarArea, self.panel_toolbar)
        for dock, title in ((self.layers_dock, '▤ Warstwy'),
                            (self.properties_dock, '▦ Właściwości'),
                            (self.search_dock, '⌕ Szukaj'),
                            (self.info_dock, 'ⓘ Pomoc')):
            action = dock.toggleViewAction()
            action.setText(title)
            panels.addAction(action)
            self.panel_toolbar.addAction(action)
        self.view_menu.addAction(self._action('Przywróć wszystkie panele',
                                              self.restore_panels))

    def restore_panels(self):
        for dock, area in ((self.layers_dock, Qt.LeftDockWidgetArea),
                           (self.properties_dock, Qt.RightDockWidgetArea),
                           (self.search_dock, Qt.RightDockWidgetArea),
                           (self.info_dock, Qt.BottomDockWidgetArea)):
            self.addDockWidget(area, dock)
            dock.show()
            dock.raise_()
        self.layers_dock.raise_()

    def show_search(self):
        self.search_dock.show()
        self.search_dock.raise_()
        self.search_code.setFocus()
        self.search_code.selectAll()

    def _help_dock(self):
        dock=QDockWidget('Informacja',self)
        dock.setMaximumHeight(110)
        label=QLabel('S: zaznacz, H: przesuń; środkowy przycisk przesuwa mapę zawsze. Kolejne kliknięcia przełączają nakładające się obiekty. '
                     'P: nowy poligon (kliknij pierwszy punkt lub Enter, aby zamknąć). '
                     'E: przeciągaj wierzchołki albo kliknij krawędź, aby wstawić nowy. Esc: zakończ. '
                     'Style GEO-MAP nadal są przybliżone.')
        label.setWordWrap(True)
        dock.setWidget(label)
        return dock

    def _recent_folder(self, key):
        saved = Path(str(self.settings.value(key, str(Path.home()))))
        return str(saved if saved.is_dir() else Path.home())

    def open_map(self):
        file,_=QFileDialog.getOpenFileName(
            self, 'Otwórz mapę GEO-MAP',
            self._recent_folder('last_map_dir'), 'GEO-MAP (*.MAP *.map)')
        if not file:return
        try:
            doc=GeoMap.open(file)
            if not doc.checksum_valid:
                answer=QMessageBox.warning(self,'Suma kontrolna','Suma MD5 pliku nie zgadza się z nagłówkiem. Otworzyć tylko do podglądu?',QMessageBox.Yes|QMessageBox.No)
                if answer!=QMessageBox.Yes:return
            self.doc=doc
            self.selected_uid = ''
            self.settings.setValue('last_map_dir', str(Path(file).parent))
            self.visual_styles = load_styles(file)
            self.selected_uids = []
            self._auto_copy_path = None
            self._auto_copy_digest = None
            self._auto_style_digest = None
            self._last_pick_pos = None
            self._last_pick_candidates = ()
            self._look_for_libraries(Path(file).parent)
            self.rebuild_scene()
            self.setWindowTitle('GeoStudio v0.6 — '+Path(file).name)
            self.status.showMessage(f'{len(doc.objects)} obiektów, {len(doc.lines)} wierszy | {file}')
        except Exception as exc: QMessageBox.critical(self,'Błąd odczytu mapy',str(exc))

    def _look_for_libraries(self,folder):
        for ext,handler in [('lay','layers'),('sym','symbols'),('cdf','palette')]:
            matches=sorted(folder.glob('*.'+ext))+sorted(folder.glob('*.'+ext.upper()))
            if matches:self.load_library(matches[0],handler)

    def load_library(self, path, kind):
        if kind=='layers':_,self.catalog=library_layers(path)
        elif kind=='symbols':self.symbols=library_symbols(path)
        elif kind=='palette':self.palette=library_colors(path)

    def open_catalogs(self):
        files,_=QFileDialog.getOpenFileNames(
            self, 'Wczytaj biblioteki',
            self._recent_folder('last_library_dir'),
            'Biblioteki (*.lay *.LAY *.sym *.SYM *.cdf *.CDF)')
        if not files:return
        try:
            self.settings.setValue('last_library_dir', str(Path(files[0]).parent))
            for f in files:
                kind={'.lay':'layers','.sym':'symbols','.cdf':'palette'}.get(Path(f).suffix.lower())
                if kind:self.load_library(f,kind)
            if self.doc:self.rebuild_scene()
            self.status.showMessage(f'Załadowano {len(files)} bibliotek; {len(self.catalog)} zdefiniowanych kodów warstw')
        except Exception as exc: QMessageBox.critical(self,'Błąd bibliotek',str(exc))

    @staticmethod
    def _path_for(obj, points_override=None, *, hide_connectors=False):
        points = points_override if points_override is not None else [(p.x, p.y) for p in obj.points]
        if not points:
            return QPainterPath()
        path = QPainterPath(QPointF(points[0][0], -points[0][1]))
        previous = obj.points[0] if obj.points else None
        for i, (x, y) in enumerate(points[1:], 1):
            if (hide_connectors and points_override is None and previous is not None
                    and previous.point_type == 0):
                path.moveTo(x, -y)
            else:
                path.lineTo(x, -y)
            if points_override is None:
                previous = obj.points[i]
        return path

    def toggle_multipart_connectors(self, checked):
        self.hide_multipart_connectors = bool(checked)
        selected = set(self.selected_uids)
        if self.doc:
            self.rebuild_scene(fit=False, reselect=selected)
        self.status.showMessage('Łączniki między częściami mapy: ' +
                                ('ukryte' if checked else 'widoczne') +
                                '. Zmiana jest tylko wizualna; plik MAP pozostaje bez zmian.')

    @staticmethod
    def _label_anchor(obj):
        """Area centroid for closed geometry, midpoint for other paths."""
        pts = obj.points[:-1] if obj.is_closed else obj.points
        if not pts:
            return None
        if not obj.is_closed or len(pts) < 3:
            return (sum(p.x for p in pts)/len(pts), sum(p.y for p in pts)/len(pts))
        x0, y0 = pts[0].x, pts[0].y
        double_area, cx, cy = 0.0, 0.0, 0.0
        for i, a in enumerate(pts):
            b = pts[(i+1) % len(pts)]
            ax, ay, bx, by = a.x-x0, a.y-y0, b.x-x0, b.y-y0
            cross = ax*by - bx*ay
            double_area += cross
            cx += (ax+bx)*cross
            cy += (ay+by)*cross
        if abs(double_area) < 1e-10:
            return (sum(p.x for p in pts)/len(pts), sum(p.y for p in pts)/len(pts))
        return (x0 + cx/(3*double_area), y0 + cy/(3*double_area))

    def rebuild_scene(self, *, fit=True, reselect=''):
        if not self.doc:
            return
        self.map_scene.clear()
        self.geometry_index = GeometryIndex(self.doc.objects, hide_connectors=self.hide_multipart_connectors)
        self.layer_for_uid = {}
        self.graphics_for_uid = {}
        self.items_by_layer = defaultdict(list)
        self.labels = []
        self.highlight_item = None
        self.draft_item = None
        self.snap_marker = None
        self.edit_handles = []
        self.draft_points = []
        self.current_snap = None
        for obj in self.doc.objects:
            if not obj.points:
                continue
            layer = resolve_layer(self.catalog, obj.code)
            self.layer_for_uid[obj.uid] = layer
            color = QColor(*obj.colorref)
            fill_style = self.visual_styles.get(obj.uid)
            if fill_style:
                fill_color = QColor(fill_style['fill'])
                fill_color.setAlpha(round(fill_style['opacity'] * 255 / 100))
            else:
                fill_color = QColor(color.red(), color.green(), color.blue(), 18)
            pen = QPen(color if obj.colorref != (0,0,0) else QColor('#31455d'))
            pen.setCosmetic(True)
            pen.setWidth(1)
            if len(obj.points) == 1:
                item = QGraphicsEllipseItem(-2.5, -2.5, 5, 5)
                item.setPos(obj.points[0].x, -obj.points[0].y)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
                item.setBrush(QBrush(color))
            else:
                item = QGraphicsPathItem(self._path_for(obj, hide_connectors=self.hide_multipart_connectors))
                parts = obj.display_parts
                is_multipart_area = bool(parts) and all(
                    len(part) >= 4 and (part[0].x, part[0].y) == (part[-1].x, part[-1].y)
                    for part in parts)
                if obj.is_closed or is_multipart_area:
                    item.setBrush(QBrush(fill_color))
            item.setPen(pen)
            # We handle picking ourselves; Qt's default selection draws an
            # unwanted bounding RECTANGLE instead of the exact contour.
            item.setAcceptedMouseButtons(Qt.NoButton)
            item.setData(0, obj.uid or f'index:{obj.start}')
            item.setToolTip(f'Kod {obj.code} • {self.symbols.get(obj.code,layer)}\n{obj.fields.get("A2","")}')
            self.map_scene.addItem(item)
            self.items_by_layer[layer].append(item)
            if obj.uid:
                self.graphics_for_uid[obj.uid] = item
            label_text = ''
            if obj.code == '5310':
                label_text = '\n'.join(v for v in (obj.fields.get('A1',''), obj.fields.get('A2','')) if v)
            elif obj.code == '5216':
                label_text = obj.fields.get('A2', '')
            elif obj.code in {'5220', '5230'}:
                label_text = obj.fields.get('A2', '')
            elif obj.code.startswith('7') and obj.fields.get('TX'):
                label_text = obj.fields['TX'].replace('||','\n').replace('|',' ')
            if label_text:
                anchor = self._label_anchor(obj)
                if anchor:
                    text_item = QGraphicsSimpleTextItem(label_text)
                    if obj.code == '5310':
                        text_item.setFont(QFont('Segoe UI', 12, QFont.Bold))
                        text_item.setBrush(QBrush(QColor('#C31E2B')))
                    elif obj.code == '5216':
                        text_item.setFont(QFont('Segoe UI', 9))
                        text_item.setBrush(QBrush(QColor('#21374c')))
                    else:
                        text_item.setFont(QFont('Segoe UI', 8))
                        muted = QColor('#587280')
                        muted.setAlpha(170)
                        text_item.setBrush(QBrush(muted))
                    text_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
                    text_item.setAcceptedMouseButtons(Qt.NoButton)
                    bounds = text_item.boundingRect()
                    text_item.setPos(anchor[0], -anchor[1])
                    # Local offset remains centered at any zoom level.
                    text_item.setTransform(QTransform().translate(-bounds.width()/2, -bounds.height()/2))
                    text_item.setData(0, obj.uid)
                    text_item.setZValue(20)
                    self.map_scene.addItem(text_item)
                    self.items_by_layer[layer].append(text_item)
                    self.labels.append(text_item)
        self._populate_layers()
        if fit:
            self.fit_all()
        else:
            self.map_scene.setSceneRect(self._navigation_scene_rect())
            self.update_label_visibility()
        if reselect:
            self._select_uid(reselect)

    def set_labels_enabled(self, enabled):
        self.labels_enabled = enabled
        self.update_label_visibility()

    def change_select_filter(self, _index):
        self.select_code_filter = self.selector.currentData()
        self._last_pick_pos = None
        self._last_pick_candidates = ()
        self._select_uid('')

    def update_label_visibility(self):
        """Screen-space label decluttering: no arbitrary zoom cutoff.

        A label may be omitted at full extent if it would overlap an existing
        one, but the selected feature's label is always displayed. Zooming
        reveals more labels; the toolbar allows toggling them explicitly.
        """
        if not hasattr(self, 'labels_action'):
            return
        if not self.labels_enabled:
            for item in self.labels:
                item.setVisible(False)
            return
        viewport = self.view.viewport().rect()
        occupied = set()
        selected = self.selected_uid
        # Parcel labels take priority over land-use labels, selected above all.
        def priority(item):
            uid = item.data(0)
            obj = self.doc.by_id.get(uid) if self.doc else None
            return (0 if uid in selected else
                    1 if obj and obj.code == '5310' else
                    2 if obj and obj.code == '5216' else 3)
        for item in sorted(self.labels, key=priority):
            uid = item.data(0)
            layer = self.layer_for_uid.get(uid, '')
            if layer in self.hidden_layers:
                item.setVisible(False)
                continue
            center = self.view.mapFromScene(item.pos())
            if not viewport.adjusted(-80,-80,80,80).contains(center):
                item.setVisible(False)
                continue
            if uid in selected:
                item.setVisible(True)
                continue
            # Map appearance is prioritized over flooding the canvas with
            # thousands of overlaid strings at the original whole-map scale.
            font_size = item.boundingRect().size()
            w = max(100, round(font_size.width() + 12))
            h = max(26, round(font_size.height() + 6))
            # Declutter via occupancy of 90 x 26 px cells. Only labels actually
            # visible on the screen participate.
            col = center.x() // 90
            row = center.y() // 26
            key = (col, row)
            visible = self.all_labels_action.isChecked() or key not in occupied
            item.setVisible(visible)
            if visible:
                occupied.add(key)

    def start_pan(self):
        self.cancel_edit()
        self.view.pan_mode = True
        self.view.setDragMode(QGraphicsView.NoDrag)
        self.view.setCursor(Qt.OpenHandCursor)
        self.tool_actions['pan'].setChecked(True)
        self.status.showMessage('Tryb przesuwania mapy (H). S lub Esc: powrót do zaznaczania.')

    def _visible_uids(self):
        return {uid for uid, layer in self.layer_for_uid.items()
                if layer not in self.hidden_layers and uid in self.doc.by_id}

    def _pick_candidates(self, x, y):
        if not self.doc:
            return []
        origin = self.view.mapToScene(QPoint(0, 0))
        offset = self.view.mapToScene(QPoint(8, 0))
        radius = max(abs(offset.x() - origin.x()), 1e-8)
        hits = self.geometry_index.pick(x, y, radius,
                  visible=self._visible_uids(),code_filter=self.select_code_filter)
        return [hit.obj for hit in hits if hit.obj.uid in self.doc.by_id]

    def show_objects_here(self, x, y):
        """Explicit chooser for all overlapping objects: right-click canvas."""
        candidates = self._pick_candidates(x, y)
        if not candidates:
            return
        menu = QMenu(self)
        for obj in candidates[:30]:
            title = f'{obj.code} — {obj.fields.get("A2") or obj.fields.get("A1") or obj.uid[:8]}'
            action = menu.addAction(title)
            action.triggered.connect(lambda checked=False, uid=obj.uid: self._select_uid(uid))
        pos = self.view.mapFromScene(QPointF(x,-y))
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _set_selected_uids(self, uids):
        """One highlight path can outline thousands of selected objects efficiently."""
        if not self.doc:
            return
        self.selected_uids = list(dict.fromkeys(uid for uid in uids if uid in self.doc.by_id))
        self.selected_uid = self.selected_uids[-1] if self.selected_uids else ''
        self.props.clear()
        if self.highlight_item is not None:
            self.map_scene.removeItem(self.highlight_item)
            self.highlight_item = None
        self.selected_count_label.setText(
            f'Zaznaczono: {len(self.selected_uids)} obiektów' if self.selected_uids
            else 'Brak zaznaczenia')
        if not self.selected_uids:
            self.update_label_visibility()
            return
        combined = QPainterPath()
        for uid in self.selected_uids:
            obj = self.doc.by_id[uid]
            if obj.points:
                combined.addPath(self._path_for(
                    obj, hide_connectors=self.hide_multipart_connectors))
        self.highlight_item = QGraphicsPathItem(combined)
        outline = QPen(QColor('#ffb000'), 3)
        outline.setCosmetic(True)
        self.highlight_item.setPen(outline)
        self.highlight_item.setBrush(QBrush(Qt.NoBrush))
        self.highlight_item.setZValue(1000)
        self.highlight_item.setAcceptedMouseButtons(Qt.NoButton)
        self.map_scene.addItem(self.highlight_item)
        obj = self.doc.by_id[self.selected_uid]
        if len(self.selected_uids) > 1:
            codes = sorted({self.doc.by_id[uid].code for uid in self.selected_uids})
            entries = [('Zaznaczono', str(len(self.selected_uids))),
                       ('Kody', ', '.join(codes)),
                       ('Operacje', 'Delete usuwa zaznaczone; Zastosuj zmienia wypełnienie')]
        else:
            entries = [('Kod', obj.code),
                       ('Nazwa symbolu', self.symbols.get(obj.code, '—')),
                       ('Warstwa', resolve_layer(self.catalog, obj.code)),
                       ('ID', obj.uid), ('Wierzchołki', str(len(obj.points)))]
            if obj.area_m2 is not None:
                entries.append(('Pole geometryczne',
                    f'{obj.area_m2:,.3f} m² / {obj.area_m2/10000:,.4f} ha'))
            # Show editable fields even when absent from the source record.
            for key in ('A1','A2','A3','A4','A5','A6','TX','MP','KR'):
                entries.append((key, obj.fields.get(key, '')))
            entries.extend((k,v) for k,v in obj.fields.items()
                           if k not in {'ID','A1','A2','A3','A4','A5','A6','TX','MP','KR'})
        for key, value in entries:
            self.props.addTopLevelItem(QTreeWidgetItem([key, str(value)]))
        current = self.visual_styles.get(self.selected_uid)
        if current:
            color_code = fill_code(current['fill'], current['opacity'])
            opacity = current['opacity']
        else:
            base = QColor(*obj.colorref)
            color_code = fill_code(base.name().upper(), 7)
            opacity = 7
        self.fill_entry.setText(color_code)
        self.opacity_spin.setValue(opacity)
        self.update_label_visibility()

    def _select_uid(self, uid):
        self._set_selected_uids([uid] if uid else [])

    def select_at(self, x, y, cycle=False, additive=False):
        if not self.doc:
            return
        candidates = self._pick_candidates(x, y)
        uids = [obj.uid for obj in candidates]
        if not uids:
            self._last_pick_pos = None
            self._last_pick_candidates = ()
            if not additive:
                self._set_selected_uids([])
            return
        screen = self.view.mapFromScene(QPointF(x, -y))
        repeat = (self._last_pick_pos is not None and
                  (screen - self._last_pick_pos).manhattanLength() <= 12 and
                  tuple(uids) == self._last_pick_candidates)
        self._last_pick_pos = screen
        self._last_pick_candidates = tuple(uids)
        current = self.selected_uid
        if (cycle or repeat) and current in uids:
            idx = (uids.index(current) + 1) % len(uids)
        else:
            idx = 0
        uid = uids[idx]
        if additive:
            updated = [x for x in self.selected_uids if x != uid]
            if uid not in self.selected_uids:
                updated.append(uid)
            self._set_selected_uids(updated)
        else:
            self._select_uid(uid)
        self.status.showMessage(
            f'Wybrano kod {self.doc.by_id[uid].code}. '
            f'Łącznie zaznaczono: {len(self.selected_uids)}. '
            'Ctrl+klik dodaje/usuwa, Ctrl+H zaznacza cały kod.')

    def select_all_same_code(self):
        if not self.doc or not self.selected_uid:
            self.status.showMessage('Zaznacz najpierw jeden obiekt, następnie naciśnij Ctrl+H.')
            return
        code = self.doc.by_id[self.selected_uid].code
        uids = [obj.uid for obj in self.doc.objects
                if obj.uid and obj.code == code
                and self.layer_for_uid.get(obj.uid, '') not in self.hidden_layers]
        self._set_selected_uids(uids)
        self.status.showMessage(
            f'Zaznaczono {len(uids)} obiektów kodu {code}. '
            'Delete usuwa wszystkie po potwierdzeniu; Zastosuj zmienia wypełnienie.')

    def _snap(self, x, y, *, exclude_uid=None):
        if not self.doc or not self.snap_action.isChecked():
            return None
        origin = self.view.mapToScene(QPoint(0,0))
        other = self.view.mapToScene(QPoint(12,0))
        radius = abs(other.x() - origin.x())
        if radius <= 0:
            return None
        candidates = [obj for obj in self.geometry_index.nearby(x, y, radius)
                      if self.layer_for_uid.get(obj.uid, '') not in self.hidden_layers]
        return find_snap(x, y, candidates, radius, exclude_uid=exclude_uid,
                         hide_connectors=self.hide_multipart_connectors)

    def _ensure_feedback_items(self):
        if self.draft_item is None:
            self.draft_item = QGraphicsPathItem()
            pen = QPen(QColor('#13a89e'), 2, Qt.DashLine)
            pen.setCosmetic(True)
            self.draft_item.setPen(pen)
            self.draft_item.setBrush(QBrush(Qt.NoBrush))
            self.draft_item.setZValue(1100)
            self.draft_item.setAcceptedMouseButtons(Qt.NoButton)
            self.map_scene.addItem(self.draft_item)
        if self.snap_marker is None:
            self.snap_marker = QGraphicsEllipseItem(-5,-5,10,10)
            self.snap_marker.setPen(QPen(QColor('#0d8079'),2))
            self.snap_marker.setBrush(QBrush(QColor('#9ae6d8')))
            self.snap_marker.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            self.snap_marker.setZValue(1101)
            self.snap_marker.setAcceptedMouseButtons(Qt.NoButton)
            self.map_scene.addItem(self.snap_marker)
            self.snap_marker.setVisible(False)

    def _populate_layers(self):
        self.layers_tree.blockSignals(True)
        self.layers_tree.clear()
        for name,items in sorted(self.items_by_layer.items()):
            node=QTreeWidgetItem([name,str(len(items))]);node.setCheckState(0,Qt.Unchecked if name in self.hidden_layers else Qt.Checked)
            self.layers_tree.addTopLevelItem(node)
        self.layers_tree.blockSignals(False)

    def on_layer_toggle(self,item,column):
        state=item.checkState(0)==Qt.Checked
        for graphic in self.items_by_layer.get(item.text(0),[]):graphic.setVisible(state)
        if state:self.hidden_layers.discard(item.text(0))
        else:self.hidden_layers.add(item.text(0))
        self.update_label_visibility()

    def _sync_fill_opacity(self, opacity):
        text = self.fill_entry.text().strip()
        try:
            color, _ = parse_fill_code(text, opacity)
            self.fill_entry.setText(fill_code(color, opacity))
        except ValueError:
            pass

    def choose_fill_color(self):
        try:
            color, _ = parse_fill_code(self.fill_entry.text(),
                                       self.opacity_spin.value())
        except ValueError:
            color = '#8AADC6'
        picked = QColorDialog.getColor(QColor(color), self, 'Wybierz kolor wypełnienia')
        if picked.isValid():
            self.fill_entry.setText(fill_code(picked.name().upper(),
                                              self.opacity_spin.value()))

    def copy_fill_code(self):
        try:
            color, alpha = parse_fill_code(self.fill_entry.text(),
                                           self.opacity_spin.value())
        except ValueError as exc:
            QMessageBox.warning(self, 'Kod koloru', str(exc))
            return
        code = fill_code(color, alpha)
        QApplication.clipboard().setText(code)
        self.status.showMessage('Skopiowano kod wypełnienia: ' + code)

    def apply_fill_style(self):
        """Apply GeoStudio-only fill appearance to one or many polygons."""
        if not self.doc or not self.selected_uids:
            QMessageBox.information(self, 'Wypełnienie',
                'Najpierw zaznacz poligon lub grupę poligonów.')
            return
        try:
            color, opacity = parse_fill_code(self.fill_entry.text(),
                                              self.opacity_spin.value())
        except ValueError as exc:
            QMessageBox.warning(self, 'Niepoprawny kod koloru', str(exc))
            return
        modified = []
        for uid in self.selected_uids:
            obj = self.doc.by_id.get(uid)
            if obj and (obj.is_closed or all(
                len(p) >= 4 and (p[0].x, p[0].y) == (p[-1].x, p[-1].y)
                for p in obj.display_parts)):
                self.visual_styles[uid] = {'fill': color, 'opacity': opacity}
                modified.append(uid)
        if not modified:
            QMessageBox.information(self, 'Wypełnienie',
                'Żaden zaznaczony obiekt nie jest zamkniętym poligonem.')
            return
        selected = list(self.selected_uids)
        self.rebuild_scene(fit=False)
        self._set_selected_uids(selected)
        saved = self._autosave_work_copy()
        self.status.showMessage(
            f'Ustawiono {color}@{opacity} dla {len(modified)} poligonów. '
            'Styl przechowywany w osobnym pliku *.geostudio.json.' +
            (f' Kopia: {saved}' if saved else ' Użyj Zapisz jako.'))

    def run_search(self):
        if not self.doc:
            self.search_summary.setText('Najpierw otwórz mapę.')
            return
        try:
            matches = search_objects(self.doc.objects, self.search_code.text(),
                self.search_field.currentData(), self.search_value.text())
        except ValueError as exc:
            QMessageBox.warning(self, 'Wyszukiwarka', str(exc))
            return
        self._search_uids = [obj.uid for obj in matches]
        self.search_results.clear()
        for obj in matches[:500]:
            row = QTreeWidgetItem([obj.code, obj.fields.get('A1',''),
                                   obj.fields.get('A2','')])
            row.setData(0, Qt.UserRole, obj.uid)
            self.search_results.addTopLevelItem(row)
        self.search_summary.setText(
            f'Znaleziono {len(matches)} obiektów' +
            (' (lista pokazuje pierwsze 500)' if len(matches) > 500 else ''))
        if matches:
            self.select_search_uid(matches[0].uid)

    def select_search_result(self, item, column):
        self.select_search_uid(item.data(0, Qt.UserRole))

    def select_search_uid(self, uid):
        if not self.doc or uid not in self.doc.by_id:
            return
        self.cancel_edit()
        self._select_uid(uid)
        obj = self.doc.by_id[uid]
        if obj.points:
            xs = [point.x for point in obj.points]
            ys = [point.y for point in obj.points]
            padding = max((max(xs)-min(xs)), (max(ys)-min(ys)), 1) * .3
            rect = QRectF(min(xs)-padding, -max(ys)-padding,
                max(xs)-min(xs)+2*padding, max(ys)-min(ys)+2*padding)
            self.view.fitInView(rect, Qt.KeepAspectRatio)
            self.update_label_visibility()
        self.status.showMessage(
            f'Wynik: {obj.code} • A1={obj.fields.get("A1","")} '
            f'• A2={obj.fields.get("A2","")}')

    def select_search_results(self):
        if not self.doc:
            return
        self.cancel_edit()
        self._set_selected_uids(self._search_uids)
        self.status.showMessage(
            f'Zaznaczono {len(self.selected_uids)} wyników wyszukiwania. '
            'Delete usuwa całą grupę po potwierdzeniu.')

    def edit_property(self,item,column):
        if item.text(0) in {'A1','A2','A3','A4','A5','A6','TX','MP','KR'}:
            self._edit_field(item.text(0),item.text(1))

    def edit_selected(self):
        if not self.selected_uid:return
        key,ok=QInputDialog.getItem(self,'Edytuj atrybut','Pole:',list(['A1','A2','A3','A4','A5','A6','TX','MP','KR']),1,False)
        if ok and self.doc:
            val=self.doc.by_id[self.selected_uid].fields.get(key,'')
            self._edit_field(key,val)

    def _edit_field(self,key,old):
        if not self.doc or not self.selected_uid:return
        text,ok=QInputDialog.getMultiLineText(self,'Edycja '+key,'Nowa wartość:',old)
        if not ok:return
        try:
            uid=self.selected_uid
            self.doc.update_field(uid,key,text)
            self.rebuild_scene(fit=False, reselect=uid)
            self.status.showMessage('Zmieniono '+key+' w pamięci. Użyj „Zapisz jako”, by utworzyć nowy plik.')
        except Exception as exc:QMessageBox.warning(self,'Nie udało się zmienić atrybutu',str(exc))

    def delete_selected(self):
        """Delete selected feature records (including bulk Ctrl+H selection)."""
        if not self.doc or not self.selected_uids:
            self.status.showMessage('Najpierw zaznacz obiekt lub grupę obiektów.')
            return
        selected = list(self.selected_uids)
        count = len(selected)
        sample = self.doc.by_id[selected[-1]]
        prompt = (f'Usunąć {count} zaznaczonych obiektów z mapy?\\n'
                  f'Ostatni: {sample.code}, A1={sample.fields.get("A1", "")}, '
                  f'A2={sample.fields.get("A2", "")}.\\n'
                  'Ta operacja usuwa CAŁE rekordy i nie ma jeszcze Cofnij.\\n'
                  'Oryginalny MAP pozostaje nietknięty.')
        answer = QMessageBox.question(self, 'Potwierdź usunięcie', prompt,
                                      QMessageBox.Yes | QMessageBox.No,
                                      QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.cancel_edit()
        self.doc.delete_objects(selected)
        for uid in selected:
            self.visual_styles.pop(uid, None)
        self.selected_uids = []
        self.selected_uid = ''
        self._last_pick_pos = None
        self._last_pick_candidates = ()
        self.rebuild_scene(fit=False)
        self._set_selected_uids([])
        saved = self._autosave_work_copy()
        self.status.showMessage(
            f'Usunięto {count} obiektów.' +
            (f' Kopia robocza: {saved}' if saved else ' Zapisz jako nową mapę.'))

    def save_map(self):
        if not self.doc:
            return
        source = Path(self.doc.filename) if self.doc.filename else Path.home() / 'mapa.MAP'
        default = source.with_name(source.stem + '_GeoStudio.MAP')
        file, _ = QFileDialog.getSaveFileName(self,
            'Zapisz zmodyfikowaną MAP (nowy plik)', str(default),
            'GEO-MAP (*.MAP)')
        if not file:
            return
        try:
            if self.visual_styles and sidecar_path(file).exists():
                raise FileExistsError('Plik stylów o tej nazwie już istnieje.')
            self.doc.save_as(file)
            if self.visual_styles:
                write_styles(file, self.visual_styles)
            QMessageBox.information(self, 'Zapisano eksperymentalną MAP',
                'Utworzono nowy plik MAP. Osobne wypełnienia (jeśli używane) '
                'są zapisane w towarzyszącym pliku *.geostudio.json i nie '
                'są interpretowane przez GEO-MAP. Sprawdź kopię w GEO-MAP. '
                'Oryginał nie został nadpisany.')
        except Exception as exc:
            QMessageBox.warning(self, 'Zapis przerwany', str(exc))

    def _world_scene_rect(self):
        """Fit real map geometry, never pixel-sized labels or edit markers."""
        if not self.doc:
            return QRectF()
        coordinates = [(p.x, p.y) for o in self.doc.objects for p in o.points]
        if not coordinates:
            return QRectF()
        xs, ys = zip(*coordinates)
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        padding = max((xmax - xmin), (ymax - ymin), 1.0) * .025
        return QRectF(xmin - padding, -(ymax + padding),
                      xmax - xmin + 2 * padding, ymax - ymin + 2 * padding)

    def _navigation_scene_rect(self):
        """Provide pan margin so wheel zoom can stay anchored even near map edges."""
        rect = self._world_scene_rect()
        if rect.isEmpty():
            return rect
        margin = max(rect.width(), rect.height(), 10.0)
        return rect.adjusted(-margin, -margin, margin, margin)

    def fit_all(self):
        if not self.doc:
            return
        rect = self._world_scene_rect()
        if rect.isEmpty():
            return
        self.map_scene.setSceneRect(self._navigation_scene_rect())
        self.view.fitInView(rect, Qt.KeepAspectRatio)
        self.update_label_visibility()

    def on_coordinate(self,x,y):
        self.status.showMessage(f'Współrzędne źródłowe: X={x:.3f} | Y={y:.3f} | {"tryb rysowania" if self.view.draw_mode else "tryb zaznaczania"}')

    def cancel_edit(self):
        self.view.draw_mode = False
        self.view.edit_mode = False
        self.view.pan_mode = False
        self.view.setCursor(Qt.ArrowCursor)
        if hasattr(self, "tool_actions"):
            self.tool_actions["select"].setChecked(True)
        self.view.dragged_vertex = None
        self.view.edit_points = []
        self.view.setDragMode(QGraphicsView.NoDrag)
        self.view._pan_button = None
        self.view._pan_last = None
        if hasattr(self, 'finish_toolbar_action'):
            self.finish_toolbar_action.setVisible(False)
            self.finish_action.setEnabled(False)
        self.current_polygon = []
        self.edit_uid = ''
        if hasattr(self, 'undo_toolbar_action'):
            self.undo_toolbar_action.setVisible(False)
        if self.draft_item:
            self.map_scene.removeItem(self.draft_item)
            self.draft_item = None
        if self.snap_marker:
            self.map_scene.removeItem(self.snap_marker)
            self.snap_marker = None
        for handle in self.edit_handles:
            self.map_scene.removeItem(handle)
        self.edit_handles = []
        for marker in self.draft_points:
            self.map_scene.removeItem(marker)
        self.draft_points = []
        self.status.showMessage('Zaznaczanie [S]. Prawy przycisk pokazuje listę obiektów w miejscu kliknięcia.')

    def start_polygon(self):
        if not self.doc:
            return
        self.cancel_edit()
        code,ok = QInputDialog.getText(self,'Nowy poligon','Kod GEO-MAP:',text='5216')
        if not ok:
            return
        if not code.isdigit() or len(code)!=4:
            QMessageBox.warning(self,'Kod','Kod musi składać się z czterech cyfr')
            return
        self.polygon_code = code
        self.current_polygon = []
        self.view.draw_mode = True
        self.view.setCursor(Qt.CrossCursor)
        self.tool_actions['draw'].setChecked(True)
        self.view.setDragMode(QGraphicsView.NoDrag)
        self._ensure_feedback_items()
        self.finish_toolbar_action.setVisible(True)
        self.undo_toolbar_action.setVisible(True)
        self.finish_action.setEnabled(True)
        self.status.showMessage('Poligon: klikaj wierzchołki, kliknij PIERWSZY punkt lub Enter/prawy przycisk, aby zakończyć i zapisać kopię.')

    def preview_polygon(self, x, y):
        if not self.view.draw_mode:
            return
        self._ensure_feedback_items()
        snap = self._snap(x, y)
        self.current_snap = snap
        px, py = (snap.x, snap.y) if snap else (x, y)
        if len(self.current_polygon) >= 3:
            start = self.current_polygon[0]
            cursor = self.view.mapFromScene(QPointF(x, -y))
            anchor = self.view.mapFromScene(QPointF(start[0], -start[1]))
            if math.hypot(cursor.x() - anchor.x(), cursor.y() - anchor.y()) <= 14:
                px, py = start
        pts = self.current_polygon + [(px,py)]
        if pts:
            path = QPainterPath(QPointF(pts[0][0], -pts[0][1]))
            for vx, vy in pts[1:]:
                path.lineTo(vx,-vy)
            self.draft_item.setPath(path)
        self.snap_marker.setVisible(bool(snap))
        if snap:
            self.snap_marker.setPos(snap.x, -snap.y)

    def add_polygon_point(self, x, y):
        # Close on a click within a 14-pixel radius of the FIRST point.
        # Screen coordinates are essential: one fixed map-unit tolerance
        # would behave unpredictably when the user zooms.
        if len(self.current_polygon) >= 3:
            initial = self.current_polygon[0]
            cursor = self.view.mapFromScene(QPointF(x, -y))
            anchor = self.view.mapFromScene(QPointF(initial[0], -initial[1]))
            if math.hypot(cursor.x() - anchor.x(), cursor.y() - anchor.y()) <= 14:
                self.finish_polygon()
                return
        snap = self._snap(x, y)
        px, py = (snap.x, snap.y) if snap else (x, y)
        if len(self.current_polygon) >= 3 and (px, py) == self.current_polygon[0]:
            self.finish_polygon()
            return
        if self.current_polygon and self.current_polygon[-1] == (px,py):
            return
        self.current_polygon.append((px,py))
        # Persist placed vertices while drawing. The old implementation showed
        # only a segment whose origin could be nearly invisible at map scale.
        dot = QGraphicsEllipseItem(-4,-4,8,8)
        dot.setPos(px,-py)
        dot.setBrush(QBrush(QColor('#06a68e')))
        dot.setPen(QPen(QColor('white'),1))
        dot.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        dot.setAcceptedMouseButtons(Qt.NoButton)
        dot.setZValue(1200)
        self.map_scene.addItem(dot)
        self.draft_points.append(dot)
        self.preview_polygon(px, py)
        self.status.showMessage(f'Poligon: {len(self.current_polygon)} punkty. Kliknij początek, Enter, prawy przycisk lub ✓ Zakończ.')

    def undo_last_polygon_point(self):
        """Escape removes one point but leaves the polygon drawing tool active."""
        if not self.view.draw_mode:
            return
        if not self.current_polygon:
            self.status.showMessage('Brak punktów do cofnięcia. Narzędzie P nadal aktywne.')
            return
        self.current_polygon.pop()
        if self.draft_points:
            marker = self.draft_points.pop()
            self.map_scene.removeItem(marker)
        if self.draft_item:
            if not self.current_polygon:
                self.draft_item.setPath(QPainterPath())
            else:
                self.preview_polygon(*self.current_polygon[-1])
        if self.snap_marker:
            self.snap_marker.setVisible(False)
        self.status.showMessage(
            f'Cofnięto ostatni punkt. Pozostało {len(self.current_polygon)} punktów. Esc cofa kolejne.')

    def _ask_polygon_attributes(self):
        """Full form for new-object attributes; blanks are stored as editable empty fields."""
        dialog = QDialog(self)
        dialog.setWindowTitle(f'Nowy poligon {self.polygon_code} — atrybuty')
        dialog.resize(560, 480)
        layout = QFormLayout(dialog)
        entries = {}
        for key, title in (
            ('A1', 'A1 — atrybut 1'),
            ('A2', 'A2 — numer / opis'),
            ('A3', 'A3 — identyfikator'),
            ('A4', 'A4 — informacje'),
            ('A5', 'A5 — dodatkowe dane'),
            ('A6', 'A6 — powierzchnie / użytki'),
            ('TX', 'TX — uwagi'),
            ('MP', 'MP — parametr'),
            ('DT', 'DT — data'),
            ('KR', 'KR — referencje'),
        ):
            entry = QLineEdit(dialog)
            entry.setText('0' if key == 'MP' else '')
            entry.setPlaceholderText('Wpisz wartość (może pozostać puste)')
            layout.addRow(title, entry)
            entries[key] = entry
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        if dialog.exec() != QDialog.Accepted:
            return None
        return {key: widget.text() for key, widget in entries.items()}

    def finish_polygon(self):
        if not self.view.draw_mode:
            return
        points = self.current_polygon[:]
        if len(points) > 1 and points[0] == points[-1]:
            points.pop()
        if not polygon_is_valid(points):
            QMessageBox.warning(self, 'Poligon',
                'Wymagane co najmniej 3 różne, niewspółliniowe punkty.')
            return
        attrs = self._ask_polygon_attributes()
        if attrs is None:
            return
        try:
            uid = self.doc.append_polygon(points, self.polygon_code, fields=attrs)
            self.cancel_edit()
            self.rebuild_scene(fit=False, reselect=uid)
            saved = self._autosave_work_copy()
            self.status.showMessage('Zamknięto poligon i zapisano pola A1–A6, TX i metadane.' +
                (f' Kopia robocza: {saved}' if saved else ' Użyj Zapisz jako, by zapisać kopię mapy.'))
        except Exception as exc:
            QMessageBox.warning(self, 'Błąd rysowania', str(exc))

    def _persist_work_copy_styles(self):
        """Protect app-owned style sidecars against out-of-band edits."""
        if not self._auto_copy_path:
            return
        target = sidecar_path(self._auto_copy_path)
        if not self.visual_styles and self._auto_style_digest is None:
            return
        if self._auto_style_digest is None:
            write_styles(self._auto_copy_path, self.visual_styles, overwrite=False)
        else:
            if not target.is_file() or hashlib.sha256(
                    target.read_bytes()).digest() != self._auto_style_digest:
                raise RuntimeError('Plik stylów zmieniono poza GeoStudio; nie nadpisuję go.')
            write_styles(self._auto_copy_path, self.visual_styles, overwrite=True)
        self._auto_style_digest = hashlib.sha256(target.read_bytes()).digest()

    def _autosave_work_copy(self):
        """Automatically persist edits to a NEW work-copy, never the source file.

        Rewrites ONLY a copy generated by this application instance; atomic
        replace protects against interruption. User-supplied .MAP is untouched.
        """
        if not self.doc or not self.doc.filename:
            return None
        source = Path(self.doc.filename).resolve()
        encoded = self.doc.to_bytes()
        try:
            if self._auto_copy_path is None:
                # Exclusive creation avoids overwriting any existing user file.
                for number in range(1, 1000):
                    suffix = '' if number == 1 else f'_{number}'
                    candidate = source.with_name(source.stem + '_GeoStudio_robocza' + suffix + source.suffix)
                    try:
                        with candidate.open('xb') as output:
                            output.write(encoded)
                        self._auto_copy_path = candidate
                        self._auto_copy_digest = hashlib.sha256(encoded).digest()
                        break
                    except FileExistsError:
                        continue
                else:
                    raise FileExistsError('Brak wolnej nazwy kopii roboczej')
            else:
                target = self._auto_copy_path
                if not target.is_file() or target.resolve() == source:
                    raise RuntimeError('Kopia robocza została przeniesiona; ponowny zapis zablokowany')
                if hashlib.sha256(target.read_bytes()).digest() != self._auto_copy_digest:
                    raise RuntimeError('Kopia robocza została zmieniona poza GeoStudio; odmawiam nadpisania')
                fd, temporary = tempfile.mkstemp(prefix='.geostudio-', suffix='.tmp', dir=target.parent)
                try:
                    with os.fdopen(fd, 'wb') as output:
                        output.write(encoded)
                        output.flush()
                        os.fsync(output.fileno())
                    os.replace(temporary, target)
                    self._auto_copy_digest = hashlib.sha256(encoded).digest()
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            self._persist_work_copy_styles()
            return self._auto_copy_path
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self,'Kopia robocza nie została zapisana',
                f'Zmiana pozostaje w pamięci. Zapisz ją ręcznie przez Zapisz jako.\n{exc}')
            return None

    def insert_vertex_at(self, x, y):
        """Click near an edge in E mode: split its segment with a new vertex."""
        if not self.view.edit_mode or not self.edit_uid or not self.doc:
            return
        obj = self.doc.by_id.get(self.edit_uid)
        if not obj or not obj.is_closed:
            return
        origin = self.view.mapToScene(QPoint(0, 0))
        edge = self.view.mapToScene(QPoint(14, 0))
        tolerance = abs(edge.x() - origin.x())
        best = None
        for i, (a, b) in enumerate(zip(obj.points, obj.points[1:])):
            px, py = closest_point_on_edge(x, y, a.x, a.y, b.x, b.y)
            dist = math.hypot(x - px, y - py)
            if dist <= tolerance and (best is None or dist < best[0]):
                best = (dist, i, px, py)
        if best is None:
            return
        _dist, index, px, py = best
        uid = self.edit_uid
        try:
            self.doc.insert_polygon_vertex(uid, index, px, py)
            self.cancel_edit()
            self.rebuild_scene(fit=False, reselect=uid)
            self.start_vertex_edit()
            saved = self._autosave_work_copy()
            self.status.showMessage('Dodano wierzchołek na krawędzi.' +
                                    (f' Kopia: {saved}' if saved else ' Zapisz jako nowy MAP.'))
        except (ValueError, IndexError) as exc:
            self.status.showMessage('Nie wstawiono wierzchołka: ' + str(exc))

    def start_vertex_edit(self):
        if not self.doc or not self.selected_uid:
            QMessageBox.information(self,'Edycja wierzchołków','Zaznacz najpierw poligon (np. działkę 5216).')
            return
        obj = self.doc.by_id[self.selected_uid]
        if not obj.is_closed:
            QMessageBox.warning(self,'Edycja','Wybrany obiekt nie jest zamkniętym poligonem.')
            return
        uid = self.selected_uid
        self.cancel_edit()
        self.edit_uid = uid
        self.view.edit_mode = True
        self.view.setCursor(Qt.CrossCursor)
        self.tool_actions['edit'].setChecked(True)
        self.view.edit_points = [(p.x,p.y) for p in obj.points[:-1]]
        self.view.setDragMode(QGraphicsView.NoDrag)
        self._ensure_feedback_items()
        self.draft_item.setPath(self._path_for(obj))
        for px,py in self.view.edit_points:
            handle = QGraphicsEllipseItem(-4,-4,8,8)
            handle.setPos(px,-py)
            handle.setPen(QPen(QColor('#ffffff'),1))
            handle.setBrush(QBrush(QColor('#0d9a90')))
            handle.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations,True)
            handle.setAcceptedMouseButtons(Qt.NoButton)
            handle.setZValue(1200)
            self.map_scene.addItem(handle)
            self.edit_handles.append(handle)
        self.status.showMessage('Tryb edycji wierzchołków: przeciągnij punkt poligonu. Przyciąganie do innych obiektów. Esc kończy.')

    def preview_vertex(self, x, y, index):
        if not self.view.edit_mode or not self.edit_uid:
            return
        snap = self._snap(x, y, exclude_uid=self.edit_uid)
        px, py = (snap.x,snap.y) if snap else (x,y)
        pts = self.view.edit_points[:]
        if not 0 <= index < len(pts):
            return
        pts[index] = (px,py)
        if index < len(self.edit_handles):
            self.edit_handles[index].setPos(px,-py)
        self._ensure_feedback_items()
        self.draft_item.setPath(self._path_for(self.doc.by_id[self.edit_uid], pts + [pts[0]]))
        self.snap_marker.setVisible(True)
        self.snap_marker.setPos(px, -py)

    def commit_vertex(self, x, y, index):
        if not self.view.edit_mode or not self.edit_uid:
            return
        snap = self._snap(x, y, exclude_uid=self.edit_uid)
        px, py = (snap.x,snap.y) if snap else (x,y)
        try:
            uid = self.edit_uid
            self.doc.move_polygon_vertex(uid,index,px,py)
            # Preserve current scale/position; do not zoom out after every edit.
            self.cancel_edit()
            self.rebuild_scene(fit=False,reselect=uid)
            self.start_vertex_edit()
            saved = self._autosave_work_copy()
            self.status.showMessage('Wierzchołek przesunięty.' +
                                    (f' Kopia: {saved}' if saved else ' Zapisz jako nowy MAP.'))
        except Exception as exc:
            QMessageBox.warning(self,'Nie zmieniono geometrii',str(exc))
            self.cancel_edit()
            self.rebuild_scene(fit=False,reselect=self.selected_uid)

    def add_raster(self):
        file,_=QFileDialog.getOpenFileName(self,'Otwórz raster z georeferencją',str(Path.home()),'Obrazy (*.png *.jpg *.jpeg *.tif *.tiff)')
        if not file:return
        path=Path(file)
        pix=QPixmap(file)
        if pix.isNull():QMessageBox.warning(self,'Raster','Nie udało się odczytać obrazu.');return
        wf=None
        for ext in [path.suffix[1:2]+'w',path.suffix[1:2]+path.suffix[-1:]+'w', 'wld', 'tfw', 'jgw', 'pgw']:
            candidate=path.with_suffix('.'+ext)
            if candidate.exists():wf=candidate;break
        if wf is None:
            QMessageBox.information(self,'Wymagana georeferencja','Raster nie ma pliku world (.tfw/.jgw/.pgw/.wld). Kalibracja ręczna jest na liście następnych etapów.');return
        try:
            vals=[float(v.strip()) for v in wf.read_text().splitlines()[:6]]
            if len(vals)!=6:raise ValueError('Plik world powinien zawierać sześć współczynników')
            a,d,b,e,c,f=vals
            item=QGraphicsPixmapItem(pix)
            item.setTransform(QTransform(a,-d,b,-e,c,-f))
            item.setOpacity(0.62)
            item.setZValue(-100)
            self.map_scene.addItem(item)
            self.status.showMessage(f'Dodano raster: {path.name}. Przejrzystość 62%, podkład pod wektorami.')
        except Exception as exc:QMessageBox.warning(self,'Błąd georeferencji',str(exc))

    def export_image(self):
        if not self.doc:return
        file,_=QFileDialog.getSaveFileName(self,'Eksport widoku mapy',str(Path.home()/'mapa.png'),
            'PNG (*.png);;JPEG (*.jpg);;TIFF (*.tif)')
        if not file:return
        try:
            rect=self.map_scene.itemsBoundingRect()
            if rect.isEmpty():return
            width=2600; height=max(400,min(5000,round(width*rect.height()/max(rect.width(),1))))
            img=QImage(width,height,QImage.Format_RGB32)
            img.fill(QColor('white'))
            painter=QPainter(img); painter.setRenderHint(QPainter.Antialiasing)
            self.map_scene.render(painter,QRectF(0,0,width,height),rect,Qt.KeepAspectRatio)
            painter.end()
            suffix=Path(file).suffix.lower()
            if not img.save(file):
                # TIFF writer availability is platform-dependent.
                raise RuntimeError('Format niedostępny w tej instalacji Qt; wybierz PNG/JPG.')
            self.status.showMessage('Zapisano obraz: '+file)
        except Exception as exc:QMessageBox.warning(self,'Błąd eksportu',str(exc))

    def export_dxf(self):
        if not self.doc:return
        file,_=QFileDialog.getSaveFileName(self,'Eksport uproszczonego DXF',str(Path.home()/'mapa.dxf'),'AutoCAD DXF (*.dxf)')
        if not file:return
        try:
            import ezdxf
            d=ezdxf.new('R2010',setup=True);model=d.modelspace()
            for obj in self.doc.objects:
                if not obj.points:continue
                layer=resolve_layer(self.catalog,obj.code)
                layer=''.join(c if c not in '<>/\\":;?*|,=' else '_' for c in layer)[:100]
                if layer not in d.layers:d.layers.new(name=layer)
                vertices=[(p.x,p.y) for p in obj.points]
                if len(vertices)>1:model.add_lwpolyline(vertices,dxfattribs={'layer':layer})
                else:model.add_point(vertices[0],dxfattribs={'layer':layer})
            d.saveas(file)
            QMessageBox.information(self,'Zapisano DXF','Zapisano podstawową geometrię i warstwy. Eksport NIE odtwarza jeszcze symboli, kreskowań, opisów ani wszystkich atrybutów GEO-MAP.')
        except ImportError:QMessageBox.warning(self,'Wymagana biblioteka','Zainstaluj ezdxf: pip install ezdxf')
        except Exception as exc:QMessageBox.warning(self,'Błąd DXF',str(exc))


def main():
    app=QApplication(sys.argv)
    app.setStyle('Fusion')
    window=GeoStudioWindow()
    window.show()
    if len(sys.argv)>1:
        path=Path(sys.argv[1])
        if path.exists():
            window.doc=GeoMap.open(path)
            window.visual_styles=load_styles(path)
            window.settings.setValue('last_map_dir',str(path.parent))
            window._look_for_libraries(path.parent)
            window.rebuild_scene()
    sys.exit(app.exec())
