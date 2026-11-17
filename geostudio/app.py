"""First desktop prototype. Rendering is deliberately approximate, data is preserved.

Safety: never overwrite original MAP; saved files require a separate filename.
Full symbol / raster / export parity with GEO-MAP is NOT implemented.
"""
from __future__ import annotations
import sys
import math
from pathlib import Path
from collections import defaultdict

try:
    from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, QSettings, Signal
    from PySide6.QtGui import QAction, QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QImage, QTransform, QActionGroup
    from PySide6.QtWidgets import (QApplication, QMainWindow, QFileDialog, QGraphicsView, QGraphicsScene,
        QGraphicsPathItem, QGraphicsEllipseItem, QGraphicsPixmapItem, QGraphicsSimpleTextItem, QGraphicsItem, QDockWidget,
        QTreeWidget, QTreeWidgetItem, QToolBar, QMessageBox, QStatusBar, QInputDialog, QMenu,
        QLabel, QWidget, QVBoxLayout, QHeaderView, QSplitter, QComboBox)
except ImportError as exc:
    raise SystemExit('Zainstaluj GUI: python -m pip install -e .\nBrakuje PySide6') from exc

from .geomap import GeoMap, GeoObject, library_layers, library_symbols, library_colors, resolve_layer
from .interactions import find_snap, polygon_is_valid
from .geometry_index import GeometryIndex

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
    canvas_click = Signal(float, float, bool)
    canvas_context = Signal(float, float)
    point_for_polygon = Signal(float, float)
    polygon_hover = Signal(float, float)
    finish_polygon = Signal()
    cancel_action = Signal()
    vertex_hover = Signal(float, float, int)
    vertex_commit = Signal(float, float, int)
    zoom_changed = Signal()

    def __init__(self, scene):
        super().__init__(scene)
        self.draw_mode = False
        self.edit_mode = False
        self.pan_mode = False
        self.edit_points = []
        self.dragged_vertex = None
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
        factor = 1.2 if event.angleDelta().y() > 0 else 1/1.2
        self.scale(factor, factor)
        self.zoom_changed.emit()
        event.accept()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self.zoom_changed.emit()

    def mouseMoveEvent(self, event):
        x, y = self._position(event)
        self.coordinate.emit(x, y)
        if self.draw_mode:
            self.polygon_hover.emit(x, y)
            event.accept()
            return
        if self.edit_mode and self.dragged_vertex is not None:
            self.vertex_hover.emit(x, y, self.dragged_vertex)
            event.accept()
            return
        if self.pan_mode:
            super().mouseMoveEvent(event)
        else:
            event.accept()

    def mousePressEvent(self, event):
        self.setFocus()
        x, y = self._position(event)
        if self.draw_mode:
            if event.button() == Qt.RightButton:
                self.finish_polygon.emit()
            elif event.button() == Qt.LeftButton:
                self.point_for_polygon.emit(x, y)
            event.accept()
            return
        if self.edit_mode:
            if event.button() == Qt.LeftButton:
                pos = event.position().toPoint()
                distances = [(self.mapFromScene(QPointF(px, -py))-pos).manhattanLength()
                             for px, py in self.edit_points]
                if distances:
                    idx = min(range(len(distances)), key=distances.__getitem__)
                    if distances[idx] <= 20:
                        self.dragged_vertex = idx
                        self.vertex_hover.emit(x, y, idx)
            event.accept()
            return
        if self.pan_mode:
            super().mousePressEvent(event)
            return
        if event.button() == Qt.RightButton:
            self.canvas_context.emit(x, y)
        elif event.button() == Qt.LeftButton:
            self.canvas_click.emit(x, y, bool(event.modifiers() & Qt.AltModifier))
        event.accept()

    def mouseReleaseEvent(self, event):
        if self.edit_mode:
            if self.dragged_vertex is not None and event.button() == Qt.LeftButton:
                x, y = self._position(event)
                idx = self.dragged_vertex
                self.dragged_vertex = None
                self.vertex_commit.emit(x, y, idx)
            event.accept()
            return
        if self.pan_mode:
            super().mouseReleaseEvent(event)
        else:
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if self.draw_mode:
            self.finish_polygon.emit()
        elif self.pan_mode:
            super().mouseDoubleClickEvent(event)
        else:
            event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and (self.draw_mode or self.edit_mode or self.pan_mode):
            self.cancel_action.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class GeoStudioWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('GeoStudio — eksperymentalny edytor GEO-MAP')
        self.resize(1450, 900)
        self.doc: GeoMap | None=None
        self.catalog: dict[str,str]={}
        self.symbols: dict[str,str]={}
        self.palette: dict[str,tuple[int,int,int]]={}
        self.items_by_layer:dict[str,list]=defaultdict(list)
        self.graphics_for_uid={}
        self.labels=[]
        self.labels_enabled = True
        self.layer_for_uid = {}
        self.hidden_layers = set()
        self.geometry_index = GeometryIndex(())
        self.select_code_filter = None
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
        self.view.cancel_action.connect(self.cancel_edit)
        self.view.zoom_changed.connect(self.update_label_visibility)
        self.view.point_for_polygon.connect(self.add_polygon_point)
        self.view.finish_polygon.connect(self.finish_polygon)
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
        em.addAction(self._action('Zakończ / anuluj narzędzie',self.cancel_edit,'Esc'))
        em.addAction(self._action('Edytuj atrybut zaznaczonego obiektu…',self.edit_selected,'F2'))
        vm=self.menuBar().addMenu('&Widok')
        vm.addAction(self._action('Dopasuj widok do mapy',self.fit_all,'Ctrl+0'))
        self.labels_action = vm.addAction('Podpisy A1/A2 (widoczność)')
        self.labels_action.setCheckable(True)
        self.labels_action.setChecked(True)
        self.labels_action.toggled.connect(self.set_labels_enabled)
        self.snap_action = em.addAction('Przyciąganie do punktów i odcinków')
        self.snap_action.setCheckable(True)
        self.snap_action.setChecked(True)
        toolbar=QToolBar('Narzędzia',self)
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
        left=QDockWidget('Warstwy GEO-MAP',self)
        self.layers_tree=QTreeWidget()
        self.layers_tree.setHeaderLabels(['Warstwa','Obiekty'])
        self.layers_tree.header().setSectionResizeMode(0,QHeaderView.Stretch)
        self.layers_tree.itemChanged.connect(self.on_layer_toggle)
        left.setWidget(self.layers_tree)
        self.addDockWidget(Qt.LeftDockWidgetArea,left)
        right=QDockWidget('Właściwości obiektu',self)
        self.props=QTreeWidget()
        self.props.setHeaderLabels(['Pole','Wartość'])
        self.props.header().setSectionResizeMode(0,QHeaderView.ResizeToContents)
        self.props.header().setSectionResizeMode(1,QHeaderView.Stretch)
        self.props.itemDoubleClicked.connect(self.edit_property)
        right.setWidget(self.props)
        self.addDockWidget(Qt.RightDockWidgetArea,right)
        self.selected_uid=''
        self.addDockWidget(Qt.BottomDockWidgetArea, self._help_dock())

    def _help_dock(self):
        dock=QDockWidget('Informacja',self)
        dock.setMaximumHeight(110)
        label=QLabel('S: wybierz obiekt, H: przesuń mapę, P: poligon, E: edytuj wierzchołki. Alt+klik lub prawy przycisk: nakładające się obiekty. '
                     'P: nowy poligon (wierzchołki przyciągają się do punktów i krawędzi). '
                     'E: przesuwaj wierzchołki wybranego poligonu. Esc: zakończ narzędzie. '
                     'Style GEO-MAP nadal są przybliżone.')
        label.setWordWrap(True)
        dock.setWidget(label)
        return dock

    def open_map(self):
        file,_=QFileDialog.getOpenFileName(self,'Otwórz mapę GEO-MAP',str(Path.home()),'GEO-MAP (*.MAP *.map)')
        if not file:return
        try:
            doc=GeoMap.open(file)
            if not doc.checksum_valid:
                answer=QMessageBox.warning(self,'Suma kontrolna','Suma MD5 pliku nie zgadza się z nagłówkiem. Otworzyć tylko do podglądu?',QMessageBox.Yes|QMessageBox.No)
                if answer!=QMessageBox.Yes:return
            self.doc=doc
            self._look_for_libraries(Path(file).parent)
            self.rebuild_scene()
            self.setWindowTitle('GeoStudio — '+Path(file).name)
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
        files,_=QFileDialog.getOpenFileNames(self,'Wczytaj biblioteki',str(Path.home()),'Biblioteki (*.lay *.LAY *.sym *.SYM *.cdf *.CDF)')
        if not files:return
        try:
            for f in files:
                kind={'.lay':'layers','.sym':'symbols','.cdf':'palette'}.get(Path(f).suffix.lower())
                if kind:self.load_library(f,kind)
            if self.doc:self.rebuild_scene()
            self.status.showMessage(f'Załadowano {len(files)} bibliotek; {len(self.catalog)} zdefiniowanych kodów warstw')
        except Exception as exc: QMessageBox.critical(self,'Błąd bibliotek',str(exc))

    @staticmethod
    def _path_for(obj, points_override=None):
        points = points_override if points_override is not None else [(p.x, p.y) for p in obj.points]
        if not points:
            return QPainterPath()
        path = QPainterPath(QPointF(points[0][0], -points[0][1]))
        for x, y in points[1:]:
            path.lineTo(x, -y)
        return path

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
        self.geometry_index = GeometryIndex(self.doc.objects)
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
            pen = QPen(color if obj.colorref != (0,0,0) else QColor('#31455d'))
            pen.setCosmetic(True)
            pen.setWidth(1)
            if len(obj.points) == 1:
                item = QGraphicsEllipseItem(-2.5, -2.5, 5, 5)
                item.setPos(obj.points[0].x, -obj.points[0].y)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
                item.setBrush(QBrush(color))
            else:
                item = QGraphicsPathItem(self._path_for(obj))
                if obj.is_closed:
                    item.setBrush(QBrush(QColor(color.red(),color.green(),color.blue(),18)))
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
            elif obj.code in {'5216', '5230'}:
                label_text = obj.fields.get('A2', '')
            elif obj.code.startswith('7') and obj.fields.get('TX'):
                label_text = obj.fields['TX'].replace('||','\n').replace('|',' ')
            if label_text:
                anchor = self._label_anchor(obj)
                if anchor:
                    text_item = QGraphicsSimpleTextItem(label_text)
                    text_item.setFont(QFont('Segoe UI', 9))
                    text_item.setBrush(QBrush(QColor('#21374c')))
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
            self.map_scene.setSceneRect(self._world_scene_rect())
            self.update_label_visibility()
        if reselect:
            self._select_uid(reselect)

    def set_labels_enabled(self, enabled):
        self.labels_enabled = enabled
        self.update_label_visibility()

    def change_select_filter(self, _index):
        self.select_code_filter = self.selector.currentData()
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
            return (0 if uid == selected else
                    1 if obj and obj.code == '5216' else
                    2 if obj and obj.code == '5310' else 3)
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
            if uid == selected:
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
            visible = key not in occupied
            item.setVisible(visible)
            if visible:
                occupied.add(key)

    def start_pan(self):
        self.cancel_edit()
        self.view.pan_mode = True
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
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

    def _select_uid(self, uid):
        self.selected_uid = uid if self.doc and uid in self.doc.by_id else ''
        self.props.clear()
        if self.highlight_item:
            self.map_scene.removeItem(self.highlight_item)
            self.highlight_item = None
        if not self.selected_uid:
            self.update_label_visibility()
            return
        obj = self.doc.by_id[self.selected_uid]
        self.highlight_item = QGraphicsPathItem(self._path_for(obj))
        outline = QPen(QColor('#ffb000'), 3)
        outline.setCosmetic(True)
        self.highlight_item.setPen(outline)
        self.highlight_item.setBrush(QBrush(Qt.NoBrush))
        self.highlight_item.setZValue(1000)
        self.highlight_item.setAcceptedMouseButtons(Qt.NoButton)
        self.map_scene.addItem(self.highlight_item)
        entries = [('Kod',obj.code),('Nazwa symbolu',self.symbols.get(obj.code,'—')),
                   ('Warstwa',resolve_layer(self.catalog,obj.code)),('ID',obj.uid),
                   ('Wierzchołki',str(len(obj.points)))]
        if obj.area_m2 is not None:
            entries.append(('Pole geometryczne',f'{obj.area_m2:,.3f} m² / {obj.area_m2/10000:,.4f} ha'))
        entries.extend((k,v) for k,v in obj.fields.items() if k!='ID')
        for k,v in entries:
            self.props.addTopLevelItem(QTreeWidgetItem([k,v]))
        self.update_label_visibility()

    def select_at(self, x, y, cycle=False):
        if not self.doc:
            return
        candidates = self._pick_candidates(x, y)
        uids = [obj.uid for obj in candidates]
        if not uids:
            self._select_uid('')
            return
        if cycle and self.selected_uid in uids:
            idx = (uids.index(self.selected_uid) + 1) % len(uids)
        else:
            idx = 0
        self._select_uid(uids[idx])
        obj = self.doc.by_id[uids[idx]]
        self.status.showMessage(f'Wybrano {obj.code} / {obj.fields.get("A2", "")}. '
                                f'Alt+klik lub prawy przycisk: inne obiekty ({idx+1}/{len(uids)}).')

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
        return find_snap(x, y, candidates, radius, exclude_uid=exclude_uid)

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

    def save_map(self):
        if not self.doc:return
        source=Path(self.doc.filename) if self.doc.filename else Path.home()/'mapa.MAP'
        default=source.with_name(source.stem+'_GeoStudio.MAP')
        file,_=QFileDialog.getSaveFileName(self,'Zapisz zmodyfikowaną MAP (nowy plik)',str(default),'GEO-MAP (*.MAP)')
        if not file:return
        try:
            self.doc.save_as(file)
            QMessageBox.information(self,'Zapisano eksperymentalną MAP',
                'Zapisano nowy plik z przeliczonym CHK i N. Przed użyciem operacyjnym sprawdź go w GEO-MAP. '
                'Oryginał pozostał niezmieniony.')
        except Exception as exc:QMessageBox.warning(self,'Zapis przerwany',str(exc))

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

    def fit_all(self):
        if not self.doc:
            return
        rect = self._world_scene_rect()
        if rect.isEmpty():
            return
        self.map_scene.setSceneRect(rect)
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
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.current_polygon = []
        self.edit_uid = ''
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
        self.status.showMessage('Rysowanie [P]: lewy = dodaj wierzchołek, prawy = zakończ, Esc = anuluj; przyciąganie włączone.')

    def preview_polygon(self, x, y):
        if not self.view.draw_mode:
            return
        self._ensure_feedback_items()
        snap = self._snap(x, y)
        self.current_snap = snap
        px, py = (snap.x, snap.y) if snap else (x, y)
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
        snap = self._snap(x, y)
        px, py = (snap.x, snap.y) if snap else (x, y)
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
        self.status.showMessage(f'Poligon: {len(self.current_polygon)} wierzchołki; prawy = zapisz, Esc = anuluj.')

    def finish_polygon(self):
        if not self.view.draw_mode:
            return
        points = self.current_polygon[:]
        if len(points)>1 and points[0]==points[-1]:
            points.pop()
        if not polygon_is_valid(points):
            QMessageBox.warning(self,'Poligon','Wymagane co najmniej 3 różne, niewspółliniowe punkty.')
            return
        label,ok=QInputDialog.getText(self,'Nowy poligon','Numer / opis (A2):')
        if not ok:
            return
        try:
            uid=self.doc.append_polygon(points,self.polygon_code,label)
            self.cancel_edit()
            self.rebuild_scene(fit=False,reselect=uid)
            self.status.showMessage('Dodano poligon. Zapisz jako NOWY plik MAP; sprawdź wynik w GEO-MAP.')
        except Exception as exc:
            QMessageBox.warning(self,'Błąd rysowania',str(exc))

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
            self.status.showMessage('Wierzchołek przesunięty. Zapisz jako kopię i zweryfikuj plik w GEO-MAP.')
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
            window._look_for_libraries(path.parent)
            window.rebuild_scene()
    sys.exit(app.exec())
