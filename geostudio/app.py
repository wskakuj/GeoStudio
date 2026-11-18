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
    from PySide6.QtCore import Qt, QPoint, QPointF, QRectF, QSize, QSettings, Signal, QTimer
    from PySide6.QtGui import QAction, QBrush, QColor, QFont, QPainterPath, QPen, QPixmap, QTransform, QActionGroup
    from PySide6.QtWidgets import (QApplication, QMainWindow, QFileDialog, QGraphicsView, QGraphicsScene,
        QGraphicsPathItem, QGraphicsEllipseItem, QGraphicsRectItem, QGraphicsPixmapItem, QGraphicsSimpleTextItem, QGraphicsItem, QDockWidget,
        QTreeWidget, QTreeWidgetItem, QToolBar, QMessageBox, QStatusBar, QInputDialog, QMenu,
        QLabel, QWidget, QVBoxLayout, QHeaderView, QSplitter, QComboBox,
        QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QHBoxLayout, QPushButton, QSpinBox, QSlider, QColorDialog, QToolButton, QFrame, QTabWidget)
except ImportError as exc:
    raise SystemExit('Zainstaluj GUI: python -m pip install -e .\nBrakuje PySide6') from exc

from .geomap import GeoMap, GeoObject, library_layers, library_symbols, library_colors, resolve_layer
from .interactions import polygon_is_valid, closest_point_on_edge
from .geometry_index import GeometryIndex, point_in_ring
from .topology_edit import linked_vertex_moves
from .scene_builder import RenderContext, build_scene, label_anchor, object_path, object_fill_brush
from .map_tools import MapView
from .selection import (SelectionContext, highlight_path, pick_candidates,
                        resolve_click, snap_at, toggle_selection, visible_uids)
from .exporters import render_scene_image, save_image, write_dxf
from .history import History, HistoryConflict
from .map_layout import (detect_source_compilation_scale, validated_compilation_scale,
    label_ratio, source_text_height, text_line_offset, DEFAULT_SCALE)
from .coordinates import (CRS_CHOICES, MODERN_EPSG, transform_xy,
    transform_map_copy, output_prj_text, transform_label_positions,
    detected_crs_from_prj)
from .object_search import search_objects
from .feature_dialogs import (
    CodePickerDialog, AttributeQueryDialog, ReplaceTextDialog, ObjectParametersDialog,
    replacement_plan,
)
from .visual_styles import (parse_fill_code, fill_code, load_styles,
    load_label_positions, write_styles, sidecar_path)
from .ui_theme import theme_stylesheet, ui_icon
from .workspace_shell import MapWorkspace
from .gis_ribbon import GISRibbon
from .command_palette import CommandPalette
from .document_sessions import MapSession
from .wms_qt import WMSPreviewOverlay, WMSDialog
from .wms_auto import WMSAutoRefresh
from .google_preview import GoogleMapsPreviewDialog
from .raster_overlay import RasterOverlayStore
from .raster_ui import RasterCalibrationDialog, RasterLayerPanel
from .library_render import (parse_cdf, parse_sym_primitives, cdf_for_object,
    native_fill_color, simple_point_segments, simple_point_circles,
    parse_lay_pen_styles, lay_for_code,
    parse_sym_line_patterns, object_sym_line_pattern)

APP_QSS = theme_stylesheet('light')  # Keep the legacy constant for imports.


class _MapHistoryTarget:
    """Adapts the open GeoMap and the window's sidecar dicts to the history engine.

    The engine only needs the byte lines, the two style dictionaries and a way
    to rebuild the object model after the lines change.
    """

    def __init__(self, window):
        self._window = window

    @property
    def lines(self) -> list[bytes]:
        return self._window.doc.lines

    @property
    def visual_styles(self) -> dict:
        return self._window.visual_styles

    @property
    def label_positions(self) -> dict:
        return self._window.label_positions

    def reparse(self) -> None:
        self._window.doc._parse()


class GeoStudioWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._base_title = 'GeoStudio v0.14 — eksperymentalny edytor GEO-MAP'
        self.setWindowTitle(self._base_title)
        self.resize(1500, 900)
        self.settings = QSettings('GeoStudio', 'GeoStudio')
        self.theme_mode = str(self.settings.value('ui/theme', 'light')).lower()
        if self.theme_mode not in ('light', 'dark'):
            self.theme_mode = 'light'
        self._ui_icon_actions = []
        self._command_palette = None
        self._map_sessions = []
        self._active_map_tab = -1
        self._tab_change_guard = False
        self.workspace_mode = 'edit'
        self._last_workspace = 'edit'
        self.doc: GeoMap | None=None
        self.current_crs_epsg = None  # Never guess source CRS from raw coordinates.
        self.source_compilation_scale = DEFAULT_SCALE
        self.compilation_scale = DEFAULT_SCALE
        self.catalog: dict[str,str]={}
        self.symbols: dict[str,str]={}
        self.palette: dict[str,tuple[int,int,int]]={}
        self.cdf_styles = {}
        self.sym_primitives = {}
        self.lay_pen_styles = {}
        self.sym_line_patterns = {}
        self.fill_items_for_uid = {}
        self.library_paths = {}
        self.label_positions = {}
        self.label_items = {}
        self._active_label = None
        self.items_by_layer:dict[str,list]=defaultdict(list)
        self.graphics_for_uid={}
        self.visual_styles = {}
        self._last_fill_opacity = None
        self.selected_uids = []
        self.highlight_items = []
        self._selected_label_frames = []
        self.labels=[]
        self.label_world_span = {}
        self.labels_enabled = True
        self.hide_multipart_connectors = True
        self.orientation_is_geodetic = True
        self.view_rotation_degrees = 0
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
        self.edit_scope_code = ''
        self.edit_handles=[]
        self.draft_points=[]
        self.layers_tree=None
        self.current_polygon:list[tuple[float,float]]=[]
        self.polygon_code='5216'
        self.history = History(_MapHistoryTarget(self))
        self._raster_overlay = RasterOverlayStore()
        self._wms_preview = WMSPreviewOverlay()
        self._wms_dialog = None
        self._google_dialog = None
        self._raster_map_picker = None
        self._raster_calibration_dialog = None
        self._raster_opacity_pending = False
        self._label_history = None
        self.map_scene=QGraphicsScene(self)
        # Custom feature picking handles overlapping objects without Qt selection.
        self.view=MapView(self.map_scene)
        # Network work belongs to this window, independently from WMS dialog.
        # The active MapSession stores its own WMS source and imagery.
        self._wms_auto = WMSAutoRefresh(self)
        self.view.viewport_changed.connect(self._wms_auto.viewport_changed)
        self.view.setObjectName('GeoStudioCanvas')
        self.view.coordinate.connect(self.on_coordinate)
        self.view.canvas_click.connect(self.select_at)
        self.view.canvas_context.connect(self.show_objects_here)
        self.view.polygon_hover.connect(self.preview_polygon)
        self.view.vertex_hover.connect(self.preview_vertex)
        self.view.vertex_activate.connect(self.activate_vertex_at)
        self.view.vertex_commit.connect(self.commit_vertex)
        self.view.edge_insert.connect(self.insert_vertex_at)
        self.view.cancel_action.connect(self.cancel_edit)
        self.view.zoom_changed.connect(self.update_label_visibility)
        self.view.point_for_polygon.connect(self.add_polygon_point)
        self.view.finish_polygon.connect(self.finish_polygon)
        self.view.undo_polygon_point.connect(self.undo_last_polygon_point)
        self.view.label_press.connect(self.begin_label_drag)
        self.view.label_move.connect(self.move_label)
        self.view.label_drop.connect(self.end_label_drag)
        self._setup_menu()
        self._install_workspace_shell()
        self._setup_docks()
        self._install_arcgis_ribbon()
        self.set_workspace('edit', remember=False)
        # The original docks shrink to unreadable widths on Windows HiDPI.
        # Reserve usable space for layer names and attribute values.
        self.resizeDocks([self.layers_dock, self.properties_dock],
                         [275, 355], Qt.Horizontal)
        self._load_saved_libraries()
        self.status=QStatusBar();self.setStatusBar(self.status)
        self._setup_scale_widget()
        self.status.showMessage('Witaj w GeoStudio. Kliknij Otwórz MAP, aby rozpocząć; S/H/N/P/L zmienia narzędzie. E otwiera parametry obiektu.')
        self.setStyleSheet(theme_stylesheet(self.theme_mode))
        self._refresh_toolbar_icons()

    def _install_workspace_shell(self):
        """Move map tools into a dedicated rail instead of a second ribbon."""
        self.removeToolBarBreak(self.main_toolbar)
        self.removeToolBar(self.main_toolbar)
        self.main_toolbar.setOrientation(Qt.Vertical)
        self.main_toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.main_toolbar.setIconSize(QSize(25, 25))
        self.main_toolbar.setObjectName('GeoStudioToolPalette')
        self.main_toolbar.setFixedWidth(94)
        self.workspace = MapWorkspace(
            self.view, self.main_toolbar, self.selector,
            on_fit=self.fit_all, on_focus=self.toggle_focus_workspace)
        self.setCentralWidget(self.workspace)
        self.workspace.set_document(None)
        self.workspace.document_tabs.currentChanged.connect(self._activate_map_tab)
        self.workspace.document_tabs.tabCloseRequested.connect(self.close_map_tab)
        self.workspace.new_map_button.clicked.connect(self.open_map)


    def _install_arcgis_ribbon(self):
        """Replace two desktop toolbars with a task-based GIS ribbon.

        Every button delegates to the existing QAction or method. The map
        model, data format, selection and scene rendering do not change.
        """
        ribbon = GISRibbon(self.theme_mode, self)
        self.ribbon = ribbon
        ribbon.set_command_search(self.show_command_palette)
        self.ribbon_toolbar = QToolBar('Wstążka GIS', self)
        self.ribbon_toolbar.setObjectName('GeoStudioRibbonToolbar')
        self.ribbon_toolbar.setMovable(False)
        self.ribbon_toolbar.setFloatable(False)
        self.ribbon_toolbar.setAllowedAreas(Qt.TopToolBarArea)
        self.ribbon_toolbar.addWidget(ribbon)
        self.removeToolBar(self.file_toolbar)
        self.file_toolbar.hide()
        self.addToolBar(Qt.TopToolBarArea, self.ribbon_toolbar)

        # Map tab: the most frequent cartographic operations.
        project = ribbon.group('Mapa', 'Projekt')
        project.action(self.open_toolbar_action, 'folder', large=True, text='Otwórz MAP')
        project.action(self.save_toolbar_action, 'save', large=True, text='Zapisz kopię')

        navigation = ribbon.group('Mapa', 'Nawigacja')
        navigation.action(self.tool_actions['select'], 'select', large=True, text='Zaznacz')
        navigation.action(self.tool_actions['pan'], 'hand', large=True, text='Przesuń')
        navigation.action(self._action('Cała mapa', self.fit_all), 'fit', large=True)
        navigation.menu('Orientacja', self.orientation_button.menu(), 'compass')

        contents = ribbon.group('Mapa', 'Zawartość mapy')
        contents.stack(
            (self.layers_dock.toggleViewAction(), 'layers', 'Warstwy'),
            (self.labels_action, 'label', 'Podpisy A1/A2'),
            (self.snap_action, 'snap', 'Przyciąganie'),
        )

        search = ribbon.group('Mapa', 'Wybieranie')
        search.action(self._action('Znajdź obiekt', self.show_search),
                      'search', large=True, text='Znajdź')
        search.control(self.selector, minimum_width=178)

        # Edit tab. All tools remain backed by their original QActionGroup.
        edit = ribbon.group('Edycja', 'Narzędzia edycji')
        for key, icon, title in (
                ('select', 'select', 'Zaznacz'),
                ('draw', 'polygon', 'Poligon'),
                ('edit', 'vertices', 'Wierzchołki'),
                ('labels', 'label', 'Etykiety')):
            edit.action(self.tool_actions[key], icon, large=True, text=title)

        sketch = ribbon.group('Edycja', 'Szkic')
        sketch.stack(
            (self.finish_action, 'check', 'Zakończ poligon'),
            (self._action('Cofnij punkt szkicu', self.undo_last_polygon_point),
             'undo', 'Cofnij punkt'),
            (self._action('Przerwij narzędzie', self.cancel_edit),
             'select', 'Anuluj'),
        )

        objects = ribbon.group('Edycja', 'Obiekty')
        objects.stack(
            (self._action('Edytuj atrybut', self.edit_selected),
             'properties', 'Edytuj atrybut'),
            (self._action('Wybierz ten kod', self.select_all_same_code),
             'filter', 'Wybierz ten kod'),
            (self.delete_action, 'more', 'Usuń zaznaczone'),
        )
        history = ribbon.group('Edycja', 'Historia')
        self.ribbon_undo_action = self._action('Cofnij zmianę', self.undo_last_edit)
        self.ribbon_redo_action = self._action('Ponów zmianę', self.redo_last_edit)
        history.stack(
            (self.ribbon_undo_action, 'undo', 'Cofnij zmianę'),
            (self.ribbon_redo_action, 'redo', 'Ponów zmianę'),
        )

        # Data tab keeps import / coordinate tools discoverable.
        libraries = ribbon.group('Dane', 'Biblioteki GEO-MAP')
        libraries.action(
            self._action('Wczytaj SYM / LAY / CDF', self.open_catalogs),
            'layers', large=True, text='SYM / LAY / CDF')
        rasters = ribbon.group('Dane', 'Rastry')
        rasters.action(self._action('Dodaj raster', self.add_raster),
                       'image', large=True, text='Dodaj raster')
        rasters.stack(
            (self._action('Kalibruj raster…', self.calibrate_selected_raster),
             'snap', 'Kalibracja GCP'),
            (self._action('Panel podkładów', self.show_raster_panel),
             'layers', 'Podkłady'),
        )
        online = ribbon.group('Dane', 'Mapy online')
        online.stack(
            (self._action('Podgląd WMS…', self.show_wms_dialog),
             'layers', 'WMS — pod mapą'),
            (self._action('Google Earth w GeoStudio', self.open_google_maps),
             'compass', 'Google Earth'),
        )
        coordinates = ribbon.group('Dane', 'Współrzędne')
        coordinates.action(
            self._action('Transformuj układ', self.open_crs_converter),
            'snap', large=True, text='Transformuj')

        # View tab: scale, pane arrangement and display controls.
        workspace = ribbon.group('Widok', 'Układ stanowiska')
        workspace.stack(
            (self.workspace_actions['edit'], 'properties', 'Edycja'),
            (self.workspace_actions['search'], 'search', 'Wyszukiwanie'),
            (self.workspace_actions['map'], 'fit', 'Sama mapa'),
        )
        scales = ribbon.group('Widok', 'Skala i obrót')
        scales.stack(
            (self._action('Skala widoku', self.ask_view_scale),
             'fit', 'Skala widoku 1:N'),
            (self._action('Skala opracowania', self.ask_compilation_scale),
             'properties', 'Skala opracowania'),
        )
        scales.menu('Obróć mapę', self.orientation_button.menu(), 'compass')
        display = ribbon.group('Widok', 'Wyświetlanie')
        display.stack(
            (self.all_labels_action, 'label', 'Wszystkie podpisy'),
            (self.multipart_action, 'layers', 'Łączniki obiektów'),
        )
        theme = ribbon.group('Widok', 'Interfejs')
        theme.menu('Motyw', self.theme_menu, 'more')
        theme.menu('Panele', self.panels_menu, 'properties')

        # Export tab intentionally separates saving native MAP from DXF and images.
        saved = ribbon.group('Eksport', 'Plik GEO-MAP')
        saved.action(self.save_toolbar_action, 'save', large=True, text='Zapisz MAP')
        output = ribbon.group('Eksport', 'Udostępnianie')
        output.action(self._action('Eksportuj obraz', self.export_image),
                      'image', large=True, text='PNG / JPG / TIFF')
        output.action(self._action('Eksportuj DXF', self.export_dxf),
                      'export', large=True, text='DXF')

        # Compact Quick Access actions are available on every ribbon page.
        for action, icon in (
                (self.open_toolbar_action, 'folder'),
                (self.save_toolbar_action, 'save'),
                (self.ribbon_undo_action, 'undo'),
                (self.ribbon_redo_action, 'redo')):
            ribbon.add_quick_action(action, icon)
        ribbon.set_document(self.doc.filename if self.doc else None)
        self.ribbon_toggle_action = self._action(
            'Zwiń / rozwiń wstążkę', ribbon.toggle_collapsed, 'Ctrl+F1')
        self.addAction(self.ribbon_toggle_action)

        # ArcGIS Pro puts editing commands in the ribbon, not a vertical rail.
        self.workspace.tool_rail.hide()
        self.panel_toolbar.hide()

    def _update_dirty_title(self):
        mark = ' *' if self.history.is_dirty else ''
        self.setWindowTitle(getattr(self, '_base_title',
                                    'GeoStudio v0.14') + mark)
        if hasattr(self, 'workspace'):
            self.workspace.set_document(
                self.doc.filename if self.doc else None, dirty=self.history.is_dirty)
        if hasattr(self, 'ribbon'):
            self.ribbon.set_document(
                self.doc.filename if self.doc else None, dirty=self.history.is_dirty)
        if (0 <= self._active_map_tab < len(self._map_sessions) and
                hasattr(self, 'workspace')):
            self.workspace.document_tabs.setTabText(
                self._active_map_tab,
                Path(self.doc.filename).name + (' *' if self.history.is_dirty else ''))

    def _history_changed(self):
        self._update_dirty_title()

    def undo_last_edit(self):
        """Undo one entry. The UI shortcuts are attached in a later stage."""
        try:
            entry = self.history.undo()
        except HistoryConflict as exc:
            QMessageBox.warning(self, 'Nie można cofnąć', str(exc))
            return
        if entry is None:
            self.status.showMessage('Brak operacji do cofnięcia.')
            return
        self._after_history_apply(entry.selection_before,
                                  f'Cofnięto: {entry.label}')

    def redo_last_edit(self):
        try:
            entry = self.history.redo()
        except HistoryConflict as exc:
            QMessageBox.warning(self, 'Nie można ponowić', str(exc))
            return
        if entry is None:
            self.status.showMessage('Brak operacji do ponowienia.')
            return
        self._after_history_apply(entry.selection_after,
                                  f'Ponowiono: {entry.label}')

    def _after_history_apply(self, selection, message):
        """Rebuild the view after undo/redo and keep the work copy in step."""
        if not self.doc:
            return
        self.rebuild_scene(fit=False)
        self._set_selected_uids(list(selection or []))
        try:
            saved = self._autosave_work_copy()
        except Exception as exc:                      # autosave must not block undo
            saved = None
            QMessageBox.warning(self, 'Kopia robocza',
                'Zmiana została cofnięta w pamięci, ale kopii roboczej nie udało się '
                f'zaktualizować: {exc}')
        self._update_dirty_title()
        self.status.showMessage(message + (f' Kopia robocza: {saved}' if saved else ''))

    def _action(self,label,callback,shortcut=None):
        a=QAction(label,self)
        a.triggered.connect(callback)
        if shortcut:a.setShortcut(shortcut)
        return a

    def _decorate_action(self, action, glyph, tooltip=None):
        """Decorate existing actions without changing their callbacks."""
        self._ui_icon_actions.append((action, glyph))
        action.setIcon(ui_icon(glyph, self.theme_mode))
        if tooltip:
            action.setToolTip(tooltip)
            action.setStatusTip(tooltip)
        return action

    def _refresh_toolbar_icons(self):
        for action, glyph in self._ui_icon_actions:
            action.setIcon(ui_icon(glyph, self.theme_mode))
        if hasattr(self, 'ribbon'):
            self.ribbon.refresh_icons(self.theme_mode)
        for attr, icon_name in (
                ('orientation_button', 'compass'), ('data_button', 'layers'),
                ('export_button', 'export'), ('map_settings_button', 'more')):
            button = getattr(self, attr, None)
            if button is not None:
                button.setIcon(ui_icon(icon_name, self.theme_mode))

    def set_theme(self, theme):
        """Change UI chrome, never scene item colours or exported imagery."""
        if theme not in ('light', 'dark'):
            raise ValueError('Unknown interface theme')
        self.theme_mode = theme
        self.settings.setValue('ui/theme', theme)
        self.setStyleSheet(theme_stylesheet(theme))
        self._refresh_toolbar_icons()
        for key, action in getattr(self, 'theme_actions', {}).items():
            action.setChecked(key == theme)

    def _set_mode_badge(self, text):
        if hasattr(self, 'mode_badge'):
            self.mode_badge.setText(text)
        if hasattr(self, 'workspace'):
            self.workspace.set_tool(text)
        if hasattr(self, 'ribbon') and text in (
                'RYSOWANIE POLIGONU', 'RYSOWANIE LINII',
                'EDYCJA WIERZCHOŁKÓW', 'PRZESUWANIE ETYKIET'):
            self.ribbon.select_tab('Edycja')

    def _searchable_actions(self):
        """Collect existing QAction instances, including nested menus and ribbon."""
        result = []
        seen = set()

        def add(action):
            if action is None:
                return
            menu = action.menu()
            if menu is not None:
                for child in menu.actions():
                    add(child)
                return
            if action.isSeparator() or not action.text().strip():
                return
            if id(action) in seen:
                return
            seen.add(id(action))
            result.append((action.text().replace('&', ''), action))

        for top in self.menuBar().actions():
            add(top)
        for action in (self.open_toolbar_action, self.save_toolbar_action,
                       self.snap_action, self.labels_action, self.delete_action,
                       getattr(self, 'ribbon_undo_action', None),
                       getattr(self, 'ribbon_redo_action', None)):
            add(action)
        for action in self.tool_actions.values():
            add(action)
        if hasattr(self, 'ribbon'):
            for button in self.ribbon.findChildren(QToolButton):
                add(button.defaultAction())
        return result

    def show_command_palette(self):
        if self._command_palette is None:
            self._command_palette = CommandPalette(self)
        self._command_palette.set_commands(self._searchable_actions())
        self._command_palette.open_palette()

    def _setup_menu(self):
        fm=self.menuBar().addMenu('&Plik')
        actions=[('Otwórz MAP…',self.open_map,'Ctrl+O'),('Wczytaj biblioteki SYM/LAY/CDF…',self.open_catalogs,None),
                 ('Zapisz jako MAP…',self.save_map,'Ctrl+Shift+S'),
                 ('Dodaj raster / skan…',self.add_raster,None),
                 ('Kalibruj raster (GCP)…',self.calibrate_selected_raster,None),
                 ('Panel podkładów rastrowych',self.show_raster_panel,None),
                 ('Eksportuj obraz JPG/PNG/TIFF…',self.export_image,None),('Eksportuj DXF (uproszczony)…',self.export_dxf,None)]
        for label,fn,keys in actions: fm.addAction(self._action(label,fn,keys))
        fm.addSeparator();fm.addAction(self._action('Zakończ',self.close,'Ctrl+Q'))
        em=self.menuBar().addMenu('&Edycja')
        em.addAction(self._action('Zaznacz obiekt',self.cancel_edit,'S'))
        em.addAction(self._action('Przesuwanie mapy',self.start_pan,'H'))
        # One-letter keys work only while the map has focus: typing in
        # the inspector or a search field must not switch map tools.
        for title, callback, shortcut in (
                ('Rysuj poligon', self.start_polygon, 'N'),
                ('Edytuj węzły / wierzchołki', self.start_vertex_edit, 'P'),
                ('Parametry aktywnego obiektu…', self.show_active_object_parameters, 'E')):
            action = self._action(title, callback, shortcut)
            action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            self.view.addAction(action)
            em.addAction(action)
        em.addAction(self._action('Przesuń podpis A1 / A2',self.start_label_edit,'L'))
        self.finish_action = self._action('Zakończ i zapisz poligon',self.finish_polygon,'Return')
        em.addAction(self.finish_action)
        self.finish_action.setEnabled(False)
        em.addAction(self._action('Zakończ narzędzie (S)',self.cancel_edit))
        em.addAction(self._action('Edytuj pojedynczy atrybut…',self.edit_selected,'F2'))
        self.delete_action = self._action('Usuń zaznaczony obiekt', self.delete_selected, 'Delete')
        em.addAction(self.delete_action)
        em.addAction(self._action('Zaawansowane zaznaczanie (kod, A1, A2)…',
                                  self.open_selection_query, 'Ctrl+H'))
        em.addAction(self._action('Zamiana frazy w atrybutach…',
                                  self.open_phrase_replacement, 'Ctrl+F'))
        for label, callback, shortcut in (
            ('Utwórz obiekt według kodu…', self.start_code_creation, 'T'),
            ('Wyszukaj obiekty…', self.open_search_query, 'F'),
        ):
            action = self._action(label, callback, shortcut)
            action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            self.view.addAction(action)
            em.addAction(action)
        trans_menu = self.menuBar().addMenu('&Trans')
        trans_menu.addAction(self._action(
            'Przelicz współrzędne / eksportuj kopię MAP…',
            self.open_crs_converter, 'Ctrl+T'))
        vm=self.menuBar().addMenu('&Widok')
        self.view_menu = vm
        map_sources = vm.addMenu('Mapy online')
        map_sources.addAction(
            self._action('Podgląd warstw WMS…', self.show_wms_dialog))
        map_sources.addAction(
            self._action('Google Earth — w oknie programu (bez API)…', self.open_google_maps))
        self.command_palette_action = self._action(
            'Znajdź polecenie…', self.show_command_palette, 'Ctrl+K')
        vm.addAction(self.command_palette_action)
        vm.addSeparator()
        themes = vm.addMenu('Motyw interfejsu')
        self.theme_menu = themes
        self.theme_actions = {}
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        for mode, title in (('light', 'Jasny — przejrzysty'), ('dark', 'Ciemny — wieczorny')):
            action = themes.addAction(title)
            action.setCheckable(True)
            action.setChecked(self.theme_mode == mode)
            action.triggered.connect(lambda _checked=False, selected=mode: self.set_theme(selected))
            theme_group.addAction(action)
            self.theme_actions[mode] = action
        workspace_menu = vm.addMenu('Układ stanowiska')
        self.workspace_menu = workspace_menu
        self.workspace_actions = {}
        workspace_group = QActionGroup(self)
        workspace_group.setExclusive(True)
        for key, title, shortcut in (
                ('map', 'Sama mapa', 'Ctrl+1'),
                ('edit', 'Mapa + edycja', 'Ctrl+2'),
                ('search', 'Mapa + wyszukiwanie', 'Ctrl+3')):
            action = self._action(title, lambda _checked=False, mode=key:
                                  self.set_workspace(mode), shortcut)
            action.setCheckable(True)
            workspace_menu.addAction(action)
            workspace_group.addAction(action)
            self.workspace_actions[key] = action
        workspace_menu.addSeparator()
        workspace_menu.addAction(
            self._action('Przełącz skupienie na mapie', self.toggle_focus_workspace, 'F11'))
        self.workspace_actions['edit'].setChecked(True)
        vm.addSeparator()
        vm.addAction(self._action('Dopasuj widok do mapy',self.fit_all,'Ctrl+0'))
        vm.addAction(self._action('Ustaw skalę widoku 1:N…', self.ask_view_scale, 'Ctrl+M'))
        vm.addAction(self._action(
            'Skala opracowania 1:N…', self.ask_compilation_scale, 'Ctrl+F5'))
        orientation_menu = vm.addMenu('Orientacja i obrót mapy')
        orientation_menu.addAction(self._action(
            'Orientacja GEO-MAP (geodezyjna X/Y)',self.reset_orientation,'Ctrl+Alt+0'))
        orientation_menu.addAction(self._action(
            'Orientacja dawna GeoStudio (techniczna)',self.legacy_orientation))
        orientation_menu.addSeparator()
        orientation_menu.addAction(self._action(
            'Obróć w lewo 15°',lambda: self.rotate_view(-15),'Ctrl+Alt+Left'))
        orientation_menu.addAction(self._action(
            'Obróć w prawo 15°',lambda: self.rotate_view(15),'Ctrl+Alt+Right'))
        orientation_menu.addAction(self._action(
            'Obróć w lewo 90°',lambda: self.rotate_view(-90)))
        orientation_menu.addAction(self._action(
            'Obróć w prawo 90°',lambda: self.rotate_view(90)))
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
        self.all_labels_action.setChecked(True)
        self.all_labels_action.toggled.connect(lambda _checked: self.update_label_visibility())
        self.snap_action = em.addAction('Przyciąganie do punktów i odcinków')
        self.snap_action.setCheckable(True)
        self.snap_action.setChecked(True)
        # Primary, everyday commands stay visible; secondary file operations
        # are collected in predictable menus instead of crowded toolbars.
        file_toolbar = QToolBar('Plik i widok', self)
        file_toolbar.setObjectName('GeoStudioFileToolbar')
        file_toolbar.setMovable(False)
        file_toolbar.setIconSize(QSize(21, 21))
        file_toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.file_toolbar = file_toolbar
        self.addToolBar(Qt.TopToolBarArea, file_toolbar)
        brand = QLabel('GeoStudio')
        brand.setObjectName('GeoStudioBrand')
        file_toolbar.addWidget(brand)
        brand_accent = QLabel('MAPY I GEODEZJA')
        brand_accent.setObjectName('GeoStudioBrandAccent')
        file_toolbar.addWidget(brand_accent)
        file_toolbar.addSeparator()
        self.open_toolbar_action = self._decorate_action(
            self._action('Otwórz mapę', self.open_map), 'folder',
            'Otwórz mapę GEO-MAP • Ctrl+O')
        file_toolbar.addAction(self.open_toolbar_action)
        self.save_toolbar_action = self._decorate_action(
            self._action('Zapisz jako', self.save_map), 'save',
            'Zapisz nową kopię MAP • Ctrl+Shift+S')
        file_toolbar.addAction(self.save_toolbar_action)
        file_toolbar.addSeparator()
        file_toolbar.addAction(self._decorate_action(
            self._action('Cała mapa', self.fit_all), 'fit',
            'Dopasuj widok do wszystkich obiektów • Ctrl+0'))
        workspace_button = QToolButton(self)
        workspace_button.setText('Układ')
        workspace_button.setIcon(ui_icon('properties', self.theme_mode))
        workspace_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        workspace_button.setPopupMode(QToolButton.InstantPopup)
        workspace_button.setMenu(self.workspace_menu)
        workspace_button.setToolTip('Przełącz układ: sama mapa, edycja, wyszukiwanie. F11 — skupienie na mapie.')
        file_toolbar.addWidget(workspace_button)
        self.workspace_button = workspace_button

        data_menu = QMenu('Dane', self)
        data_menu.addAction(self._action('Wczytaj biblioteki SYM / LAY / CDF…', self.open_catalogs))
        data_menu.addAction(self._action('Dodaj raster z plikiem world…', self.add_raster))
        self.data_button = QToolButton(self)
        self.data_button.setText('Dane')
        self.data_button.setIcon(ui_icon('layers', self.theme_mode))
        self.data_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.data_button.setPopupMode(QToolButton.InstantPopup)
        self.data_button.setMenu(data_menu)
        self.data_button.setToolTip('Biblioteki GEO-MAP i podkłady rastrowe')
        file_toolbar.addWidget(self.data_button)

        export_menu = QMenu('Eksport', self)
        export_menu.addAction(self._action('Eksportuj obraz PNG / JPG / TIFF…', self.export_image))
        export_menu.addAction(self._action('Eksportuj uproszczony DXF…', self.export_dxf))
        self.export_button = QToolButton(self)
        self.export_button.setText('Eksport')
        self.export_button.setIcon(ui_icon('export', self.theme_mode))
        self.export_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.export_button.setPopupMode(QToolButton.InstantPopup)
        self.export_button.setMenu(export_menu)
        file_toolbar.addWidget(self.export_button)

        self.orientation_button = QToolButton(self)
        self.orientation_button.setText('Orientacja')
        self.orientation_button.setIcon(ui_icon('compass', self.theme_mode))
        self.orientation_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.orientation_button.setPopupMode(QToolButton.InstantPopup)
        self.orientation_button.setMenu(orientation_menu)
        self.orientation_button.setToolTip('Obrót i orientacja widoku bez zmiany współrzędnych')
        file_toolbar.addWidget(self.orientation_button)

        self.addToolBarBreak(Qt.TopToolBarArea)
        toolbar = QToolBar('Narzędzia mapy', self)
        toolbar.setObjectName('GeoStudioToolsToolbar')
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(21, 21))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.main_toolbar = toolbar
        self.addToolBar(Qt.TopToolBarArea, toolbar)
        caption = QLabel('NARZĘDZIA')
        caption.setObjectName('GeoStudioToolbarCaption')
        # The tool category is already presented by the new side rail.
        # Keep this label for compatibility, but do not spend map space on it.
        caption.hide()
        self.tool_actions = {}
        group = QActionGroup(self)
        group.setExclusive(True)
        for key, title, glyph, fn, hint in [
            ('select', 'Zaznacz', 'select', self.cancel_edit, 'Zaznacz obiekt (S); Ctrl+klik dodaje/usuwa'),
            ('pan', 'Przesuń', 'hand', self.start_pan, 'Przesuwaj mapę (H)'),
            ('draw', 'Poligon', 'polygon', self.start_polygon, 'Narysuj poligon (N)'),
            ('edit', 'Węzły', 'vertices', self.start_vertex_edit, 'Edytuj wierzchołki (P)'),
            ('labels', 'Etykiety', 'label', self.start_label_edit, 'Przesuwaj napisy A1/A2 (L)'),
        ]:
            action = self._decorate_action(self._action(title, fn), glyph, hint)
            action.setCheckable(True)
            group.addAction(action)
            toolbar.addAction(action)
            self.tool_actions[key] = action
        self.tool_actions['select'].setChecked(True)
        toolbar.addSeparator()
        self.finish_toolbar_action = self._decorate_action(
            self._action('Zakończ poligon', self.finish_polygon), 'check', 'Zamknij poligon (Enter)')
        toolbar.addAction(self.finish_toolbar_action)
        self.finish_toolbar_action.setVisible(False)
        self.undo_toolbar_action = self._decorate_action(
            self._action('Cofnij punkt', self.undo_last_polygon_point), 'undo', 'Cofnij punkt szkicu (Esc)')
        toolbar.addAction(self.undo_toolbar_action)
        self.undo_toolbar_action.setVisible(False)
        toolbar.addSeparator()
        self.snap_action.setText('Przyciągaj')
        toolbar.addAction(self._decorate_action(
            self.snap_action, 'snap', 'Przyciąganie do węzłów, linii i graniczników, także przy ukrytej warstwie Graniczniki'))

        map_settings_menu = QMenu('Opcje mapy', self)
        map_settings_menu.addAction(self.labels_action)
        map_settings_menu.addAction(self.all_labels_action)
        map_settings_menu.addAction(self.multipart_action)
        self.map_settings_button = QToolButton(self)
        self.map_settings_button.setText('Opcje mapy')
        self.map_settings_button.setIcon(ui_icon('more', self.theme_mode))
        self.map_settings_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.map_settings_button.setPopupMode(QToolButton.InstantPopup)
        self.map_settings_button.setMenu(map_settings_menu)
        self.map_settings_button.setToolTip('Widoczność napisów i łączników wieloczęściowych')
        toolbar.addWidget(self.map_settings_button)
        self.selector = QComboBox()
        self.selector.setToolTip('Filtr obiektów, które można zaznaczyć na mapie')
        self.selector.setMinimumWidth(175)
        self.selector.setMaximumWidth(220)
        self.selector.addItem('Wszystkie obiekty', None)
        self.selector.addItem('Działki 5216', '5216')
        self.selector.addItem('Użytki 5230', '5230')
        self.selector.currentIndexChanged.connect(self.change_select_filter)
        # The selection filter lives in the contextual map header,
        # so the vertical tool rail remains narrow and legible.

    def _setup_docks(self):
        self.selected_uid = ''
        self.layers_dock = QDockWidget('Warstwy GEO-MAP', self)
        self.layers_dock.setObjectName('GeoStudioLayersDock')
        self.layers_dock.setMinimumWidth(265)
        self.layers_tree = QTreeWidget()
        self.layers_tree.setHeaderLabels(['Warstwa', 'Obiekty'])
        self.layers_tree.setAlternatingRowColors(True)
        self.layers_tree.setUniformRowHeights(True)
        self.layers_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.layers_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.layers_tree.itemChanged.connect(self.on_layer_toggle)
        layer_root = QWidget(self.layers_dock)
        layer_layout = QVBoxLayout(layer_root)
        layer_layout.setContentsMargins(10, 12, 10, 10)
        layer_layout.setSpacing(9)
        layer_caption = QLabel('WIDOCZNOŚĆ WARSTW')
        layer_caption.setObjectName('GeoStudioSectionHeading')
        layer_layout.addWidget(layer_caption)
        self.layer_filter = QLineEdit()
        self.layer_filter.setObjectName('GeoStudioLayerFilter')
        self.layer_filter.setPlaceholderText('Znajdź warstwę…')
        self.layer_filter.setClearButtonEnabled(True)
        self.layer_filter.textChanged.connect(self._filter_layer_rows)
        layer_layout.addWidget(self.layer_filter)
        commands = QHBoxLayout()
        commands.setSpacing(6)
        for title, visible in (('Pokaż wszystkie', True), ('Ukryj wszystkie', False)):
            button = QPushButton(title)
            button.setObjectName('GeoStudioSubtleButton')
            button.clicked.connect(lambda _checked=False, show=visible: self._set_all_layers_visible(show))
            commands.addWidget(button)
        layer_layout.addLayout(commands)
        layer_layout.addWidget(self.layers_tree, 1)
        self.layers_summary = QLabel('Wczytaj mapę, aby zobaczyć warstwy')
        self.layers_summary.setObjectName('GeoStudioLayerSummary')
        layer_layout.addWidget(self.layers_summary)

        # ArcGIS-style symbology control for the selected feature code.
        # It is deliberately placed in the left Contents pane and operates
        # on all polygons sharing that code, without editing source .MAP.
        style_heading = QLabel('KRYCIE I KOLOR KODU')
        style_heading.setObjectName('GeoStudioSectionHeading')
        layer_layout.addWidget(style_heading)
        self.layer_code_choice = QComboBox()
        self.layer_code_choice.setObjectName('GeoStudioLayerCodeChoice')
        self.layer_code_choice.setToolTip(
            'Zmień wygląd wszystkich poligonów jednego kodu GEO-MAP')
        self.layer_code_choice.currentIndexChanged.connect(self._select_layer_code_style)
        layer_layout.addWidget(self.layer_code_choice)
        opacity_row = QHBoxLayout()
        self.layer_code_opacity = QSlider(Qt.Horizontal)
        self.layer_code_opacity.setObjectName('GeoStudioCodeOpacity')
        self.layer_code_opacity.setRange(0, 100)
        self.layer_code_opacity.setValue(60)
        self.layer_code_opacity.valueChanged.connect(self._code_opacity_moved)
        self.layer_code_opacity.sliderReleased.connect(self._commit_code_opacity)
        opacity_row.addWidget(self.layer_code_opacity, 1)
        self.layer_code_opacity_label = QLabel('60%')
        self.layer_code_opacity_label.setMinimumWidth(38)
        opacity_row.addWidget(self.layer_code_opacity_label)
        layer_layout.addLayout(opacity_row)
        code_buttons = QHBoxLayout()
        pick_color = QPushButton('Kolor…')
        pick_color.clicked.connect(self._choose_code_color)
        code_buttons.addWidget(pick_color)
        reset_code = QPushButton('Resetuj')
        reset_code.setToolTip('Usuń ręczne ustawienia kodu — wróć do kolorów GEO-MAP')
        reset_code.clicked.connect(self._reset_code_style)
        code_buttons.addWidget(reset_code)
        layer_layout.addLayout(code_buttons)
        self._pending_code_style = None
        self._code_opacity_timer = QTimer(self)
        self._code_opacity_timer.setSingleShot(True)
        self._code_opacity_timer.setInterval(300)
        self._code_opacity_timer.timeout.connect(self._commit_code_opacity)
        # One left dock, two real content tabs. A second QDockWidget would
        # unexpectedly rearrange the unrelated right-side inspector tabs in Qt.
        self.raster_tabs = QTabWidget(self.layers_dock)
        self.raster_tabs.setObjectName('GeoStudioContentsTabs')
        self.raster_tabs.addTab(layer_root, 'Warstwy')
        self.raster_panel = RasterLayerPanel(self)
        self.raster_tabs.addTab(self.raster_panel, 'Rastry')
        self.layers_dock.setWidget(self.raster_tabs)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.layers_dock)

        self.properties_dock = QDockWidget('Inspektor obiektu', self)
        self.properties_dock.setObjectName('GeoStudioPropertiesDock')
        self.properties_dock.setMinimumWidth(335)
        prop_root = QWidget(self.properties_dock)
        prop_root.setObjectName('GeoStudioPropertyPanel')
        prop_layout = QVBoxLayout(prop_root)
        prop_layout.setContentsMargins(11, 11, 11, 11)
        prop_layout.setSpacing(11)

        selected_card = QFrame(prop_root)
        selected_card.setObjectName('GeoStudioSelectionCard')
        card_layout = QVBoxLayout(selected_card)
        card_layout.setContentsMargins(13, 12, 13, 12)
        card_layout.setSpacing(4)
        self.selected_count_label = QLabel('Brak zaznaczenia')
        self.selected_count_label.setObjectName('GeoStudioSelectionBadge')
        card_layout.addWidget(self.selected_count_label)
        self.object_title = QLabel('Wybierz obiekt na mapie')
        self.object_title.setObjectName('GeoStudioObjectTitle')
        self.object_title.setWordWrap(True)
        card_layout.addWidget(self.object_title)
        self.object_details = QLabel('Kliknij działkę, budynek lub inny element.')
        self.object_details.setObjectName('GeoStudioObjectDetails')
        self.object_details.setWordWrap(True)
        card_layout.addWidget(self.object_details)
        self.object_metrics = QLabel('Wybierz obiekt, aby zobaczyć jego parametry')
        self.object_metrics.setObjectName('GeoStudioObjectMetrics')
        self.object_metrics.setWordWrap(True)
        card_layout.addWidget(self.object_metrics)
        quick_actions = QHBoxLayout()
        quick_actions.setSpacing(8)
        self.edit_object_button = QPushButton('Parametry [E]')
        self.edit_object_button.setObjectName('GeoStudioQuickEdit')
        self.edit_object_button.setToolTip('Otwórz parametry zaznaczonego obiektu (E)')
        self.edit_object_button.clicked.connect(self.show_active_object_parameters)
        self.edit_object_button.setEnabled(False)
        quick_actions.addWidget(self.edit_object_button, 1)
        self.copy_object_button = QPushButton('Kopiuj ID')
        self.copy_object_button.setObjectName('GeoStudioQuickCopy')
        self.copy_object_button.setToolTip('Skopiuj identyfikator zaznaczonego obiektu')
        self.copy_object_button.clicked.connect(self.copy_selected_uid)
        self.copy_object_button.setEnabled(False)
        quick_actions.addWidget(self.copy_object_button)
        card_layout.addLayout(quick_actions)
        prop_layout.addWidget(selected_card)

        # The inspector keeps its existing widget attributes and edit signals,
        # but separates dense source attributes from occasional styling.
        self.inspector_tabs = QTabWidget(prop_root)
        self.inspector_tabs.setObjectName('GeoStudioInspectorTabs')
        attrs_page = QWidget()
        attrs_layout = QVBoxLayout(attrs_page)
        attrs_layout.setContentsMargins(0, 11, 0, 0)
        attrs_layout.setSpacing(7)
        self.props = QTreeWidget()
        self.props.setHeaderLabels(['Pole', 'Wartość'])
        self.props.setAlternatingRowColors(True)
        self.props.setRootIsDecorated(False)
        self.props.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.props.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.props.itemDoubleClicked.connect(self.edit_property)
        attrs_layout.addWidget(self.props, 1)
        edit_hint = QLabel('Dwuklik w pole A1–A6 / TX, aby je edytować. Skrót F2.')
        edit_hint.setObjectName('GeoStudioInspectorHint')
        edit_hint.setWordWrap(True)
        attrs_layout.addWidget(edit_hint)
        self.inspector_tabs.addTab(attrs_page, 'Atrybuty')

        style_page = QWidget()
        style_layout = QVBoxLayout(style_page)
        style_layout.setContentsMargins(5, 16, 5, 8)
        style_layout.setSpacing(12)
        style_heading = QLabel('WYPEŁNIENIE POLIGONU')
        style_heading.setObjectName('GeoStudioSectionHeading')
        style_layout.addWidget(style_heading)
        self.fill_preview = QLabel('Podgląd wypełnienia')
        self.fill_preview.setObjectName('GeoStudioColorPreview')
        self.fill_preview.setAlignment(Qt.AlignCenter)
        self.fill_preview.setMinimumHeight(68)
        style_layout.addWidget(self.fill_preview)
        form = QFormLayout()
        form.setSpacing(9)
        self.fill_entry = QLineEdit('#7899B5@25')
        self.fill_entry.setToolTip('Kod #RRGGBB@krycie%, np. #D94848@40')
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(0, 100)
        self.opacity_spin.setSuffix(' % krycia')
        self.opacity_spin.setValue(25)
        self.opacity_spin.valueChanged.connect(self._sync_fill_opacity)
        self.opacity_spin.valueChanged.connect(self._update_fill_preview)
        self.fill_entry.textChanged.connect(self._update_fill_preview)
        form.addRow('Kolor', self.fill_entry)
        form.addRow('Krycie', self.opacity_spin)
        style_layout.addLayout(form)
        style_buttons = QHBoxLayout()
        for title, fn in [('Wybierz kolor…', self.choose_fill_color),
                          ('Kopiuj', self.copy_fill_code)]:
            button = QPushButton(title)
            button.clicked.connect(fn)
            style_buttons.addWidget(button)
        style_layout.addLayout(style_buttons)
        apply_button = QPushButton('Zastosuj do zaznaczonych poligonów')
        apply_button.setObjectName('GeoStudioPrimaryButton')
        apply_button.clicked.connect(self.apply_fill_style)
        style_layout.addWidget(apply_button)
        style_hint = QLabel('Zmiany wyglądu są zapisywane w pliku GeoStudio obok kopii. '
                            'Oryginalny MAP pozostaje nietknięty.')
        style_hint.setWordWrap(True)
        style_hint.setObjectName('GeoStudioPanelHint')
        style_layout.addWidget(style_hint)
        style_layout.addStretch(1)
        self.inspector_tabs.addTab(style_page, 'Wygląd')
        prop_layout.addWidget(self.inspector_tabs, 1)
        self.properties_dock.setWidget(prop_root)
        self.addDockWidget(Qt.RightDockWidgetArea, self.properties_dock)
        self._update_fill_preview()

        self.search_dock = QDockWidget('Wyszukaj obiekty', self)
        self.search_dock.setObjectName('GeoStudioSearchDock')
        search_root = QWidget(self.search_dock)
        search_layout = QVBoxLayout(search_root)
        search_layout.setContentsMargins(12, 12, 12, 12)
        search_layout.setSpacing(10)
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
        find_button = QPushButton('Znajdź na mapie')
        find_button.setObjectName('GeoStudioPrimaryButton')
        find_button.clicked.connect(self.run_search)
        search_layout.addWidget(find_button)
        self.search_value.returnPressed.connect(self.run_search)
        self.search_code.returnPressed.connect(self.run_search)
        self.search_summary = QLabel('Wpisz kod i wartość atrybutu')
        search_layout.addWidget(self.search_summary)
        self._search_uids = []
        self.search_results = QTreeWidget()
        self.search_results.setHeaderLabels(['Kod', 'A1', 'A2'])
        self.search_results.setAlternatingRowColors(True)
        self.search_results.itemClicked.connect(self.select_search_result)
        search_layout.addWidget(self.search_results, 1)
        select_results = QPushButton('Zaznacz wszystkie wyniki')
        select_results.clicked.connect(self.select_search_results)
        search_layout.addWidget(select_results)
        self.search_dock.setWidget(search_root)
        self.addDockWidget(Qt.RightDockWidgetArea, self.search_dock)
        # One right-side workspace: the search and inspector occupy tabs,
        # rather than permanently shrinking each other vertically.
        self.tabifyDockWidget(self.properties_dock, self.search_dock)
        self.properties_dock.raise_()
        self.search_dock.hide()

        self.info_dock = self._help_dock()
        self.info_dock.setObjectName('GeoStudioInfoDock')
        self.addDockWidget(Qt.BottomDockWidgetArea, self.info_dock)
        self.info_dock.hide()  # Save canvas space; help remains one click away.

        panels = self.view_menu.addMenu('Panele')
        self.panels_menu = panels
        self.panel_toolbar = QToolBar('Pokaż/ukryj panele', self)
        self.panel_toolbar.setObjectName('GeoStudioPanelToolbar')
        self.panel_toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.panel_toolbar.setIconSize(QSize(23, 23))
        self.panel_toolbar.setFixedWidth(47)
        self.panel_toolbar.setMovable(False)
        self.addToolBar(Qt.RightToolBarArea, self.panel_toolbar)
        for dock, title, glyph in ((self.layers_dock, 'Warstwy', 'layers'),
                                   (self.properties_dock, 'Atrybuty', 'properties'),
                                   (self.search_dock, 'Szukaj', 'search'),
                                   (self.info_dock, 'Pomoc', 'help')):
            action = dock.toggleViewAction()
            action.setText(title)
            self._decorate_action(action, glyph, 'Pokaż lub ukryj panel: ' + title)
            panels.addAction(action)
            self.panel_toolbar.addAction(action)
        self.view_menu.addAction(self._action('Przywróć wszystkie panele',
                                              self.restore_panels))

    def set_workspace(self, mode, *, remember=True):
        """Change only the workspace chrome, never geometry or current edits."""
        if mode not in {'map', 'edit', 'search'}:
            raise ValueError('Unknown GIS workspace')
        if mode != 'map':
            self._last_workspace = mode
        self.workspace_mode = mode
        if hasattr(self, 'workspace'):
            self.workspace.set_focus_mode(mode == 'map')
        if hasattr(self, 'ribbon_toolbar'):
            self.ribbon_toolbar.setVisible(mode != 'map')
        if mode == 'map':
            for dock in (self.layers_dock,
                         self.properties_dock, self.search_dock, self.info_dock):
                dock.hide()
            self.panel_toolbar.hide()
        else:
            self.panel_toolbar.hide()  # Pane commands live on the View ribbon.
            self.layers_dock.show()
            self.info_dock.hide()
            if mode == 'search':
                if self.search_dock not in self.tabifiedDockWidgets(self.properties_dock):
                    self.tabifyDockWidget(self.properties_dock, self.search_dock)
                self.properties_dock.show()
                self.search_dock.show()
                self.search_dock.raise_()
            else:
                self.search_dock.hide()
                self.properties_dock.show()
                self.properties_dock.raise_()
        for key, action in self.workspace_actions.items():
            action.setChecked(key == mode)
        self.workspace_button.setText({
            'map': 'Sama mapa', 'edit': 'Edycja', 'search': 'Wyszukiwanie'}[mode])
        if remember:
            self.settings.setValue('ui/workspace', mode)

    def toggle_focus_workspace(self):
        if self.workspace_mode == 'map':
            self.set_workspace(self._last_workspace)
        else:
            self.set_workspace('map')

    def restore_panels(self):
        self.set_workspace('edit')

    def start_code_creation(self):
        """T: GEO-MAP-style code/name picker before entering drawing mode."""
        if not self.doc:
            QMessageBox.information(self, 'Nowy obiekt', 'Najpierw otwórz mapę.')
            return
        dialog = CodePickerDialog(
            self.symbols, self.doc.objects, default=self.polygon_code, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self._start_polygon_with_code(dialog.code.text())

    def open_search_query(self):
        """F: find first matching code/attribute or select all results."""
        self._run_attribute_dialog(select_all=False)

    def open_selection_query(self):
        """Ctrl+H: precise selection by code and up to two attributes."""
        self._run_attribute_dialog(select_all=True)

    def _run_attribute_dialog(self, *, select_all):
        if not self.doc:
            QMessageBox.information(self, 'Wyszukiwanie', 'Najpierw otwórz mapę.')
            return
        prefilled = self.doc.by_id[self.selected_uid].code if self.selected_uid else ''
        dialog = AttributeQueryDialog(
            self.doc.objects, code=prefilled, select_all=select_all, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        uids = [obj.uid for obj in dialog.matches if
                self.layer_for_uid.get(obj.uid, '') not in self.hidden_layers]
        if not uids:
            QMessageBox.information(
                self, 'Wyszukiwanie', 'Nie znaleziono widocznych obiektów spełniających warunki.')
            return
        if dialog.select_all.isChecked():
            if len(uids) > 1000:
                answer = QMessageBox.question(
                    self, 'Duża grupa obiektów',
                    f'Zaznaczyć {len(uids)} obiektów? Może to chwilowo spowolnić mapę.',
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if answer != QMessageBox.Yes:
                    return
            self.cancel_edit()
            self._set_selected_uids(uids)
        else:
            self.select_search_uid(uids[0])
        self.status.showMessage(
            f'Znaleziono {len(uids)} obiektów. '
            f'Zaznaczono {len(self.selected_uids)}.')

    def open_phrase_replacement(self):
        """Ctrl+F: replace text in an explicit attribute and scope, one Undo."""
        if not self.doc:
            QMessageBox.information(self, 'Zamiana frazy', 'Najpierw otwórz mapę.')
            return
        dialog = ReplaceTextDialog(has_selection=bool(self.selected_uids), parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        spec = dialog.specification()
        objects = (self.doc.objects if spec.all_objects else
                   [self.doc.by_id[uid] for uid in self.selected_uids])
        try:
            updates = replacement_plan(objects, spec)
        except ValueError as exc:
            QMessageBox.warning(self, 'Zamiana frazy', str(exc))
            return
        if not updates:
            QMessageBox.information(self, 'Zamiana frazy', 'Nie znaleziono pasujących wartości.')
            return
        answer = QMessageBox.question(
            self, 'Potwierdź zamianę frazy',
            f'Zamienić „{spec.needle}” na „{spec.replacement}” '
            f'w polu {spec.field} dla {len(updates)} obiektów?\n'
            'Wszystkie zmiany będzie można cofnąć jednym Ctrl+Z. '
            'Oryginalny plik MAP nie zostanie nadpisany.',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        selection = list(self.selected_uids)
        try:
            with self.history.begin(
                    f'Zamiana frazy w {spec.field} ({len(updates)} obiektów)',
                    selection_before=selection):
                self.doc.bulk_update_fields(updates)
            self._history_changed()
            self.rebuild_scene(fit=False)
            self._set_selected_uids(selection)
            saved = self._autosave_work_copy()
            self.status.showMessage(
                f'Zamieniono {len(updates)} wartości pola {spec.field}.' +
                (f' Kopia: {saved}' if saved else ' Zapisz jako, aby zachować kopię.'))
        except Exception as exc:
            QMessageBox.warning(self, 'Nie zmieniono atrybutów', str(exc))

    def show_search(self):
        self.set_workspace('search')
        self.search_code.setFocus()
        self.search_code.selectAll()

    def _help_dock(self):
        dock=QDockWidget('Informacja',self)
        dock.setMaximumHeight(120)
        label=QLabel('S — zaznacz  •  H — przesuń  •  P — poligon  •  '
                     'E — wierzchołki  •  L — etykiety. '
                     'Ctrl+klik dodaje/usuwa zaznaczenie. Prawy przycisk pokazuje obiekty pod kursorem. '
                     'Enter kończy poligon; Esc anuluje akcję. '
                     'Symbolika GEO-MAP nadal jest częściowo przybliżona.')
        label.setWordWrap(True)
        dock.setWidget(label)
        return dock

    def open_crs_converter(self):
        """Interactive single-point converter and explicitly warned MAP export."""
        dialog = QDialog(self)
        dialog.setWindowTitle('Układy współrzędnych — PL-1992 / PL-2000 / 1965')
        dialog.resize(560,420)
        form = QFormLayout(dialog)
        source = QComboBox(dialog)
        destination = QComboBox(dialog)
        for title, epsg in CRS_CHOICES:
            source.addItem(title,epsg)
            destination.addItem(title,epsg)
        initial = self.current_crs_epsg or 2180
        idx = source.findData(initial)
        source.setCurrentIndex(idx if idx>=0 else 0)
        dst_idx = destination.findData(2178)
        destination.setCurrentIndex(dst_idx if dst_idx>=0 else 1)
        form.addRow('Układ źródłowy',source)
        form.addRow('Układ docelowy',destination)

        notice = QLabel(
            'Współrzędne GEO-MAP: X = północ (northing), Y = wschód (easting). '
            'Jeśli w folderze MAP brak pliku .prj, układ źródłowy NIE jest '
            'automatycznie rozpoznawany — zweryfikuj go w GEO-MAP przed przeliczeniem.')
        notice.setWordWrap(True)
        form.addRow(notice)
        input_x = QLineEdit(dialog)
        input_y = QLineEdit(dialog)
        input_x.setPlaceholderText('np. 513102,968')
        input_y.setPlaceholderText('np. 670076,708')
        form.addRow('X źródłowe [m]',input_x)
        form.addRow('Y źródłowe [m]',input_y)
        result = QLabel('Wynik: —')
        result.setWordWrap(True)
        form.addRow(result)

        def convert():
            try:
                x = float(input_x.text().strip().replace(',','.'))
                y = float(input_y.text().strip().replace(',','.'))
                sx,sy = transform_xy(x,y,source.currentData(),destination.currentData())
                result.setText(f'X = {sx:.3f} m     Y = {sy:.3f} m')
                return (sx,sy)
            except Exception as exc:
                result.setText('Błąd: ' + str(exc))
                return None

        row = QHBoxLayout()
        calculate = QPushButton('Przelicz punkt')
        calculate.clicked.connect(convert)
        row.addWidget(calculate)
        copy = QPushButton('Kopiuj X / Y')
        def copy_coords():
            transformed = convert()
            if transformed is not None:
                QApplication.clipboard().setText(
                    f'{transformed[0]:.3f}\t{transformed[1]:.3f}')
        copy.clicked.connect(copy_coords)
        row.addWidget(copy)
        form.addRow(row)

        map_button = QPushButton('Eksportuj przetransformowaną kopię MAP (eksperymentalnie)')
        map_button.setEnabled(bool(self.doc))
        map_button.setToolTip(
            'Konwertuje wszystkie rekordy P; nie jest to certyfikowana transformacja całego arkusza.')
        def export_copy():
            dialog_source=int(source.currentData())
            dialog_target=int(destination.currentData())
            if dialog_source not in MODERN_EPSG or dialog_target not in MODERN_EPSG:
                QMessageBox.warning(dialog,'Eksport MAP',
                    'Transformacja całej MAP obsługuje na razie wyłącznie PL-1992 '
                    'i PL-2000, strefy 5–8. Układy 1965: dostępny jest '
                    'kalkulator punktów, ale eksport mapy wymaga sprawdzenia '
                    'transformacji historycznych i dokładności.')
                return
            if dialog_source == dialog_target:
                QMessageBox.information(dialog,'Eksport MAP','Wybierz dwa różne układy.')
                return
            if not self.doc:
                return
            warn = (
                f'PRZELICZENIE CAŁEJ MAPY: EPSG:{dialog_source} → EPSG:{dialog_target}.\\n\\n'
                'GeoStudio zmieni wszystkie współrzędne rekordów P, '
                'włącznie z elementami arkusza, tabelami i opisami. '
                'Nie przeliczy automatycznie georeferencji rastrów ani '
                'powierzchni zapisanych jako atrybuty.\\n'
                'Powstaną wyłącznie nowe pliki MAP i PRJ. '
                'Koniecznie sprawdź pozycje i pola powierzchni w GEO-MAP.\\n\\n'
                'Kontynuować eksperymentalny eksport?')
            answer=QMessageBox.warning(dialog,'Uwaga — dane geodezyjne',
                warn,QMessageBox.Yes | QMessageBox.No,QMessageBox.No)
            if answer!=QMessageBox.Yes:
                return
            source_path=Path(self.doc.filename or 'mapa.MAP')
            default=source_path.with_name(
                source_path.stem+f'_EPSG{dialog_target}.MAP')
            filename,_=QFileDialog.getSaveFileName(
                dialog,'Wybierz nowy plik mapy (oryginał bez zmian)',
                str(default),'GEO-MAP (*.MAP)')
            if not filename:
                return
            target=Path(filename)
            prj=target.with_suffix('.prj')
            visual=sidecar_path(target)
            if target.exists() or prj.exists() or (
                    (self.visual_styles or self.label_positions) and visual.exists()):
                QMessageBox.warning(dialog,'Istniejący plik',
                    'Nie nadpisuję istniejących plików MAP, PRJ ani stylów. '
                    'Wybierz nową nazwę.')
                return
            try:
                source_doc=GeoMap(self.doc.to_bytes())
                projected=transform_map_copy(
                    source_doc,dialog_source,dialog_target)
                wkt=output_prj_text(dialog_target)
                adjusted_labels=transform_label_positions(
                    self.label_positions,dialog_source,dialog_target)
                projected.save_as(target)
                # PRJ is a standard metadata sidecar, may be ignored by GEO-MAP.
                prj.write_text(wkt,encoding='utf-8')
                if self.visual_styles or adjusted_labels:
                    write_styles(target,self.visual_styles,
                                 label_positions=adjusted_labels)
                QMessageBox.information(dialog,'Eksport zakończony',
                    f'Zapisano kopię:\\n{target}\\n{prj}\\n\\n'
                    'Oryginalna mapa nie została zmieniona. '
                    'Weryfikuj wynik w GEO-MAP, zwłaszcza atrybuty powierzchni '
                    'oraz elementy arkusza i rastry.')
            except Exception as exc:
                QMessageBox.critical(dialog,'Nie udało się przeliczyć mapy',str(exc))

        map_button.clicked.connect(export_copy)
        form.addRow(map_button)
        note = QLabel(
            'Uwaga: Warszawa 25/75, lokalny Poznań i niejednoznaczny układ '
            '1942 nie są jeszcze dostępne. Historyczne 1965 może wymagać '
            'parametrów lokalnych lub siatek transformacyjnych.')
        note.setWordWrap(True)
        form.addRow(note)
        close=QDialogButtonBox(QDialogButtonBox.Close,dialog)
        close.rejected.connect(dialog.reject)
        form.addRow(close)
        dialog.exec()

    def _recent_folder(self, key):
        saved = Path(str(self.settings.value(key, str(Path.home()))))
        return str(saved if saved.is_dir() else Path.home())

    def open_map(self):
        file,_=QFileDialog.getOpenFileName(
            self, 'Otwórz mapę GEO-MAP',
            self._recent_folder('last_map_dir'), 'GEO-MAP (*.MAP *.map)')
        if not file:return
        # A new map opens a NEW document tab. The previously active map,
        # including its dirty history, remains available and editable.
        for idx, session in enumerate(self._map_sessions):
            if Path(session.filename).resolve() == Path(file).resolve():
                self.workspace.document_tabs.setCurrentIndex(idx)
                return
        try:
            doc=GeoMap.open(file)
            if not doc.checksum_valid:
                answer=QMessageBox.warning(self,'Suma kontrolna','Suma MD5 pliku nie zgadza się z nagłówkiem. Otworzyć tylko do podglądu?',QMessageBox.Yes|QMessageBox.No)
                if answer!=QMessageBox.Yes:return
            self._capture_active_map_tab()
            if self.doc is not None:
                self.cancel_edit()
                self._close_document_dialogs()
            self.doc=doc
            self.history = History(_MapHistoryTarget(self))
            self._raster_overlay = RasterOverlayStore()
            self._wms_preview = WMSPreviewOverlay()
            self.hidden_layers = {'Graniczniki'}
            self.select_code_filter = None
            self._update_wms_attribution()
            self.current_crs_epsg = detected_crs_from_prj(file)
            self.selected_uid = ''
            self.settings.setValue('last_map_dir', str(Path(file).parent))
            self.visual_styles = load_styles(file)
            self.label_positions = load_label_positions(file)
            try:
                self._raster_overlay.load(file)
            except (OSError, ValueError, TypeError, KeyError) as raster_error:
                self._raster_overlay.clear()
                QMessageBox.warning(
                    self, 'Podkłady rastrowe',
                    'Mapa została otwarta, ale ustawienia podkładów są '
                    f'nieprawidłowe: {raster_error}')
            self._refresh_raster_panel()
            self.source_compilation_scale = detect_source_compilation_scale(doc.objects)
            saved = self.settings.value(self._compilation_scale_key(file), None)
            self.compilation_scale = validated_compilation_scale(
                saved, default=self.source_compilation_scale)
            self.selected_uids = []
            self._auto_copy_path = None
            self._auto_copy_digest = None
            self._auto_style_digest = None
            self._last_pick_pos = None
            self._last_pick_candidates = ()
            self._look_for_libraries(Path(file).parent)
            self.rebuild_scene()
            self._update_compilation_scale_indicator()
            # Entries refer to the lines of the previous document.
            self._label_history = None
            self.history.clear()
            self._base_title = 'GeoStudio v0.14 — '+Path(file).name
            self._append_current_map_tab()
            self.status.showMessage(
                f'Otwarto nową zakładkę: {Path(file).name} — '
                f'{len(doc.objects)} obiektów, {len(doc.lines)} wierszy.')
        except Exception as exc: QMessageBox.critical(self,'Błąd odczytu mapy',str(exc))

    def _capture_active_map_tab(self):
        # Commit an unfinished slider gesture to the *previous* document,
        # not to whichever tab happens to be selected 300 ms later.
        if getattr(self, '_pending_code_style', None) is not None:
            self._commit_code_opacity()
        if 0 <= self._active_map_tab < len(self._map_sessions) and self.doc:
            self._map_sessions[self._active_map_tab].capture(self)

    def _close_document_dialogs(self):
        """Prevent late network/GCP callbacks from writing into another MAP."""
        self._wms_auto.cancel()
        self._raster_map_picker = None
        if self._raster_calibration_dialog is not None:
            self._raster_calibration_dialog.close()
            self._raster_calibration_dialog = None
        if self._wms_dialog is not None:
            if self._wms_dialog.pending is not None:
                self._wms_dialog.pending.abort()
            self._wms_dialog.close()
            self._wms_dialog = None
        if self._google_dialog is not None:
            self._google_dialog.close()
            self._google_dialog = None

    def _append_current_map_tab(self):
        session = MapSession(self)
        self._map_sessions.append(session)
        self._tab_change_guard = True
        try:
            idx = self.workspace.document_tabs.addTab(Path(self.doc.filename).name)
            self.workspace.document_tabs.setTabToolTip(idx, str(self.doc.filename))
            self.workspace.document_tabs.setCurrentIndex(idx)
            self._active_map_tab = idx
            self.workspace.map_tabs_frame.show()
        finally:
            self._tab_change_guard = False
        self._update_dirty_title()

    def _activate_map_tab(self, index):
        if self._tab_change_guard or index < 0 or index == self._active_map_tab:
            return
        if index >= len(self._map_sessions):
            return
        self._capture_active_map_tab()
        self.cancel_edit()
        self._close_document_dialogs()
        self._active_map_tab = index
        self._map_sessions[index].restore(self)
        self._wms_auto.refresh(force=True)
        self.status.showMessage(
            f'Aktywna mapa: {Path(self.doc.filename).name}. '
            f'{len(self.doc.objects)} obiektów. Historia zmian jest niezależna.')

    def close_map_tab(self, index):
        if not 0 <= index < len(self._map_sessions):
            return
        session = self._map_sessions[index]
        if index == self._active_map_tab:
            self._capture_active_map_tab()
        if session.dirty:
            answer = QMessageBox.question(
                self, 'Zamknąć mapę z niezapisanymi zmianami?',
                f'{Path(session.filename).name} zawiera niezapisane zmiany. '
                'Zamknięcie jej zakładki odrzuci edycję w pamięci. '
                'Kopia robocza, jeśli istnieje, pozostanie na dysku. '
                'Zamknąć bez zapisywania jako nowy MAP?',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return

        closing_active = index == self._active_map_tab
        self._tab_change_guard = True
        try:
            self._map_sessions.pop(index)
            self.workspace.document_tabs.removeTab(index)
        finally:
            self._tab_change_guard = False
        if not closing_active:
            if index < self._active_map_tab:
                self._active_map_tab -= 1
            return

        self.cancel_edit()
        self._close_document_dialogs()
        self._active_map_tab = -1
        if self._map_sessions:
            replacement = min(index, len(self._map_sessions) - 1)
            self._tab_change_guard = True
            try:
                self.workspace.document_tabs.setCurrentIndex(replacement)
            finally:
                self._tab_change_guard = False
            self._activate_map_tab(replacement)
        else:
            self.doc = None
            self.history = History(_MapHistoryTarget(self))
            self._raster_overlay = RasterOverlayStore()
            self._wms_preview = WMSPreviewOverlay()
            self.map_scene.clear()
            self.selected_uids = []
            self.selected_uid = ''
            self.layers_tree.clear()
            self.props.clear()
            self.workspace.map_tabs_frame.hide()
            self._base_title = 'GeoStudio v0.14 — eksperymentalny edytor GEO-MAP'
            self._update_dirty_title()
            self._update_wms_attribution()
            self.status.showMessage('Wszystkie mapy zamknięte. Otwórz plik MAP (Ctrl+O).')

    def _load_saved_libraries(self):
        """Remember stable library locations across sessions, never bundle vendor files."""
        for kind in ('layers','symbols','palette'):
            path = self.settings.value('library_' + kind, '')
            if path and Path(str(path)).is_file():
                try:
                    self.load_library(path, kind, remember=False)
                except (OSError, ValueError):
                    pass

    def _look_for_libraries(self, folder):
        """Loaded user defaults win; beside-map discovery is a fallback only."""
        folder=Path(folder)
        for ext,kind in (('lay','layers'),('sym','symbols'),('cdf','palette')):
            if kind in self.library_paths and Path(self.library_paths[kind]).is_file():
                continue
            matches = sorted(p for p in folder.iterdir() if p.is_file() and
                             p.suffix.lower() == '.'+ext)
            if matches:
                self.load_library(matches[0], kind)

    def load_library(self, path, kind, *, remember=True):
        path = Path(path).resolve()
        if kind == 'layers':
            _, self.catalog = library_layers(path)
            self.lay_pen_styles = parse_lay_pen_styles(path)
        elif kind == 'symbols':
            self.symbols = library_symbols(path)
            self.sym_primitives = parse_sym_primitives(path)
            self.sym_line_patterns = parse_sym_line_patterns(path)
        elif kind == 'palette':
            self.palette = library_colors(path)
            self.cdf_styles = parse_cdf(path)
        else:
            raise ValueError('Nieznany typ biblioteki')
        self.library_paths[kind] = str(path)
        if remember:
            self.settings.setValue('library_' + kind, str(path))

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
        """Kept for callers in this module and for tests; see scene_builder.object_path."""
        return object_path(obj, points_override, hide_connectors=hide_connectors)

    @staticmethod
    def _label_anchor(obj):
        """Kept for callers in this module and for tests; see scene_builder.label_anchor."""
        return label_anchor(obj)

    def toggle_multipart_connectors(self, checked):
        self.hide_multipart_connectors = bool(checked)
        selected = list(self.selected_uids)
        if self.doc:
            self.rebuild_scene(fit=False)
            self._set_selected_uids(selected)
        self.status.showMessage('Łączniki między częściami mapy: ' +
                                ('ukryte' if checked else 'widoczne') +
                                '. Zmiana jest tylko wizualna; plik MAP pozostaje bez zmian.')

    def _render_context(self) -> RenderContext:
        """Snapshot of everything the renderer reads from the window."""
        return RenderContext(
            catalog=self.catalog,
            symbols=self.symbols,
            cdf_styles=self.cdf_styles,
            lay_pen_styles=self.lay_pen_styles,
            sym_primitives=self.sym_primitives,
            sym_line_patterns=self.sym_line_patterns,
            visual_styles=self.visual_styles,
            default_fill_opacity=self._default_fill_opacity(),
            label_positions=self.label_positions,
            compilation_scale=self.compilation_scale,
            source_compilation_scale=self.source_compilation_scale,
            hide_multipart_connectors=self.hide_multipart_connectors,
        )

    def rebuild_scene(self, *, fit=True, reselect=''):
        if not self.doc:
            return
        # The renderer clears QGraphicsScene: recreate each background
        # pixmap after every geometry / label rebuild, never above vectors.
        self._raster_overlay.clear_items()
        self._wms_preview.clear_items()
        result = build_scene(self.map_scene, self.doc, self._render_context())
        self._raster_overlay.attach(self.map_scene)
        self._wms_preview.attach(self.map_scene)
        self._wms_auto.viewport_changed()
        self.geometry_index = result.geometry_index
        self.layer_for_uid = result.layer_for_uid
        self.graphics_for_uid = result.graphics_for_uid
        self.fill_items_for_uid = result.fill_items_for_uid
        self._last_fill_opacity = self._default_fill_opacity()
        self.items_by_layer = result.items_by_layer
        self.labels = result.labels
        self.label_items = result.label_items
        self.label_world_span = result.label_world_span
        self.highlight_item = None
        self._selected_label_frames = []
        self.draft_item = None
        self.snap_marker = None
        self.edit_handles = []
        self.draft_points = []
        self.current_snap = None
        # Checkbox state and rendered visibility must always agree,
        # including on the initial open (Graniczniki are off by default).
        for name in self.hidden_layers:
            for item in self.items_by_layer.get(name, ()):
                item.setVisible(False)
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

    @staticmethod
    def _upright_map_text_transform(view_transform, bounds, ratio, offset=0.0):
        """Inverse the view's angle/mirror while retaining its zoom.

        When the view changes from A to k*A, QGraphicsItem's scene anchor must
        stay fixed.  Qt ItemIgnoresTransformations was insufficient: its
        pixel-space translation shifted labels as zoom changed.  Instead use a
        local, centred inverse orientation matrix B = |A|*ratio*inverse(A).
        Thus screen text has transform A*B = |A|*ratio*I; text stays upright,
        scales with parcel lines, and its geographic scene position never
        depends on zoom, rotation or the reflection in GEO-MAP orientation.
        """
        a=view_transform
        det=a.m11()*a.m22()-a.m12()*a.m21()
        zoom=math.hypot(a.m11(),a.m12())
        if abs(det)<1e-20 or not math.isfinite(zoom):
            return QTransform()
        factor=zoom*ratio/det
        b11=a.m22()*factor
        b12=-a.m12()*factor
        b21=-a.m21()*factor
        b22=a.m11()*factor
        cx=bounds.center().x()
        # Positive offset means the label is below the map anchor.
        cy=bounds.center().y()-offset
        dx=-(b11*cx+b21*cy)
        dy=-(b12*cx+b22*cy)
        return QTransform(b11,b12,b21,b22,dx,dy)

    def update_label_visibility(self):
        """Place all map labels at invariant map coordinates without culling."""
        if not self.doc or not hasattr(self,'labels_action'):
            return
        transform=self.view.transform()
        scale_factor=self.compilation_scale/self.source_compilation_scale
        for item in self.labels:
            base_ratio=float(item.data(4) or .55)
            ratio=base_ratio*scale_factor
            item.setData(3,ratio)
            offset=float(item.data(2) or 0)
            item.setTransform(self._upright_map_text_transform(
                transform,item.boundingRect(),ratio,offset))
            uid=item.data(0)
            item.setVisible(bool(self.labels_enabled and
                self.layer_for_uid.get(uid,'') not in self.hidden_layers))
        self.update_view_scale_indicator()

    def start_label_edit(self):
        if not self.doc:
            return
        self.cancel_edit()
        self.view.label_mode = True
        self.view.setCursor(Qt.CrossCursor)
        self.tool_actions['labels'].setChecked(True)
        self._set_mode_badge('PRZESUWANIE ETYKIET')
        # Moving descriptions must not mutate GEO-MAP geometry or attributes.
        self.status.showMessage(
            'Tryb L: przeciągnij widoczny napis A1 lub A2. '
            'Pozycje zapisywane są w pliku GeoStudio obok kopii MAP.')

    def begin_label_drag(self, x, y):
        self._active_label = None
        if not self.view.label_mode:
            return
        click = self.view.mapFromScene(QPointF(x,-y))
        found = []
        for item in self.labels:
            if not item.isVisible():
                continue
            uid, field = item.data(0), item.data(1)
            if field not in {'A1','A2'}:
                continue
            if self.layer_for_uid.get(uid,'') in self.hidden_layers:
                continue
            # Use the *actual* device transform so hitting text works
            # whether it scales with the map or uses a rotated viewport.
            rect = item.deviceTransform(
                self.view.viewportTransform()).mapRect(item.boundingRect())
            mouse = QPointF(click)
            if rect.adjusted(-8,-8,8,8).contains(mouse):
                center = rect.center()
                found.append((abs(mouse.x()-center.x())
                              + abs(mouse.y()-center.y()),item))
        if found:
            _, item = min(found, key=lambda choice: choice[0])
            self._active_label = item
            self._begin_label_history(item.data(0), item.data(1))
            self._set_selected_uids([item.data(0)])
            self.view.setCursor(Qt.ClosedHandCursor)
            self.status.showMessage(
                f'Przesuwasz {item.data(1)} obiektu {item.data(0)[:8]}. '
                'Puść mysz, aby zapisać pozycję w kopii roboczej.')

    def move_label(self, x, y):
        if self._active_label is not None and self.view.label_mode:
            self._active_label.setPos(x,-y)

    def end_label_drag(self, x, y):
        item = self._active_label
        self._active_label = None
        if not self.view.label_mode:
            return
        self.view.setCursor(Qt.CrossCursor)
        if item is None:
            return
        uid, field = item.data(0), item.data(1)
        if not uid or field not in {'A1','A2'}:
            return
        item.setPos(x,-y)
        item.setData(2,0.0)  # explicit dragged position is the new anchor
        self.label_positions.setdefault(uid,{})[field] = [round(x,3),round(y,3)]
        self._commit_label_history()
        saved = self._autosave_work_copy()
        self.update_label_visibility()
        self.status.showMessage(
            f'Przesunięto {field} i zapisano pozycję w stylu GeoStudio.' +
            (f' Kopia: {saved}' if saved else ' Użyj Zapisz jako, aby zachować pozycję.'))

    def _begin_label_history(self, uid, field):
        """One history entry per drag: opened on press, closed on drop."""
        self._abort_label_history()
        self._label_history = self.history.begin(
            f'Przesunięcie etykiety {field} obiektu {(uid or "")[:8]}',
            selection_before=[uid] if uid else [])
        self._label_history.__enter__()

    def _commit_label_history(self):
        tx, self._label_history = self._label_history, None
        if tx is not None:
            tx.__exit__(None, None, None)
            self._history_changed()

    def _abort_label_history(self):
        tx, self._label_history = self._label_history, None
        if tx is not None:
            tx.__exit__(RuntimeError, RuntimeError('label drag cancelled'), None)

    def start_pan(self):
        self.cancel_edit()
        self.view.pan_mode = True
        self.view.setDragMode(QGraphicsView.NoDrag)
        self.view.setCursor(Qt.OpenHandCursor)
        self.tool_actions['pan'].setChecked(True)
        self._set_mode_badge('PRZESUWANIE')
        self.status.showMessage('Tryb przesuwania mapy (H). S lub Esc: powrót do zaznaczania.')

    def _map_radius(self, pixels: float) -> float:
        """Length of ``pixels`` in map units at the current view transform.

        A tolerance given in pixels is a screen distance, not a distance in
        metres. Taking the length of the transformed vector keeps the value
        correct under any zoom, and it does not depend on the view rotation
        because a rotation preserves length.
        """
        origin = self.view.mapToScene(QPoint(0, 0))
        other = self.view.mapToScene(QPoint(pixels, 0))
        return math.hypot(other.x() - origin.x(), other.y() - origin.y())

    def _selection_context(self, radius: float) -> SelectionContext:
        return SelectionContext(
            doc=self.doc, geometry_index=self.geometry_index,
            layer_for_uid=self.layer_for_uid,
            hidden_layers=frozenset(self.hidden_layers),
            code_filter=self.select_code_filter,
            hide_connectors=self.hide_multipart_connectors,
            radius=radius)

    def _visible_uids(self):
        return visible_uids(self._selection_context(0.0))

    def _pick_candidates(self, x, y):
        return pick_candidates(self._selection_context(self._map_radius(8)), x, y)

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

    def copy_selected_uid(self):
        if self.selected_uid:
            QApplication.clipboard().setText(self.selected_uid)
            self.status.showMessage('Skopiowano identyfikator obiektu.')

    def _set_selected_uids(self, uids):
        """One highlight path can outline thousands of selected objects efficiently."""
        if not self.doc:
            return
        self.selected_uids = list(dict.fromkeys(uid for uid in uids if uid in self.doc.by_id))
        self.selected_uid = self.selected_uids[-1] if self.selected_uids else ''
        for frame in self._selected_label_frames:
            try:
                if frame.scene() is self.map_scene:
                    self.map_scene.removeItem(frame)
            except RuntimeError:
                pass
        self._selected_label_frames = []
        self.props.clear()
        if self.highlight_item is not None:
            self.map_scene.removeItem(self.highlight_item)
            self.highlight_item = None
        self.selected_count_label.setText(
            f'Zaznaczono: {len(self.selected_uids)} obiektów' if self.selected_uids
            else 'Brak zaznaczenia')
        if hasattr(self, 'edit_object_button'):
            self.edit_object_button.setEnabled(bool(self.selected_uids))
            self.copy_object_button.setEnabled(bool(self.selected_uid))
        if not self.selected_uids:
            self.object_title.setText('Wybierz obiekt na mapie')
            self.object_details.setText('Kliknij działkę, budynek lub inny element.')
            self.object_metrics.setText('Wybierz obiekt, aby zobaczyć jego parametry')
            self.update_label_visibility()
            return
        combined = highlight_path(self.doc, self.selected_uids,
                                  hide_connectors=self.hide_multipart_connectors)
        self.highlight_item = QGraphicsPathItem(combined)
        outline = QPen(QColor('#ffb000'), 3)
        outline.setCosmetic(True)
        self.highlight_item.setPen(outline)
        self.highlight_item.setBrush(QBrush(Qt.NoBrush))
        self.highlight_item.setZValue(1000)
        self.highlight_item.setAcceptedMouseButtons(Qt.NoButton)
        self.map_scene.addItem(self.highlight_item)
        # The A1 and A2 descriptions belong to the selected GEO-MAP object,
        # not independent objects. Emphasize both together with its contour.
        if len(self.selected_uids) == 1:
            for field in ('A1', 'A2'):
                label = self.label_items.get((self.selected_uid, field))
                if label is None:
                    continue
                frame = QGraphicsRectItem(
                    label.boundingRect().adjusted(-3, -2, 3, 2), label)
                frame.setBrush(QBrush(QColor(255, 190, 25, 72)))
                border = QPen(QColor(239, 165, 19, 220), 1)
                border.setCosmetic(True)
                frame.setPen(border)
                frame.setZValue(-1)
                frame.setAcceptedMouseButtons(Qt.NoButton)
                self._selected_label_frames.append(frame)
        self._show_selection_properties()
        self.update_label_visibility()

    def _show_selection_properties(self):
        """Fill the properties dock and the fill widgets for the selection.

        Split out of _set_selected_uids so selection logic and the properties
        panel can be changed independently. Behaviour is unchanged: same rows,
        same order, same labels.
        """
        obj = self.doc.by_id[self.selected_uid]
        if hasattr(self, 'layer_code_choice'):
            index = self.layer_code_choice.findData(obj.code)
            if index >= 0 and self.layer_code_choice.currentIndex() != index:
                self.layer_code_choice.setCurrentIndex(index)
        if len(self.selected_uids) > 1:
            self.object_title.setText(f'{len(self.selected_uids)} zaznaczonych obiektów')
            self.object_details.setText('Możesz usunąć grupę lub zmienić jej wypełnienie.')
            self.object_metrics.setText(
                f'{len(self.selected_uids)} obiektów  •  '
                f'{sum(len(self.doc.by_id[uid].points) for uid in self.selected_uids):,} wierzchołków')
        else:
            title = (obj.fields.get('A2') or obj.fields.get('A1') or
                     self.symbols.get(obj.code) or f'Obiekt {obj.code}')
            self.object_title.setText(title)
            self.object_title.setToolTip(title)
            self.object_details.setText(
                f'Kod {obj.code}  ·  {resolve_layer(self.catalog, obj.code)}')
            area = (f'  •  {obj.area_m2 / 10000:,.4f} ha'
                    if obj.area_m2 is not None else '')
            self.object_metrics.setText(
                f'{len(obj.points)} wierzchołków' + area)
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
            row = QTreeWidgetItem([key, str(value)])
            row.setToolTip(0, str(key))
            row.setToolTip(1, str(value))
            self.props.addTopLevelItem(row)
        current = self.visual_styles.get(self.selected_uid)
        if current:
            color_code = fill_code(current['fill'], current['opacity'])
            opacity = current['opacity']
        else:
            code_style = self.visual_styles.get('code:' + obj.code, {})
            native = native_fill_color(obj.style)
            base = QColor(code_style.get('fill', QColor(
                *(native if native else obj.colorref)).name()))
            opacity = code_style.get('opacity', self._default_fill_opacity())
            color_code = fill_code(base.name().upper(), opacity)
        self.fill_entry.setText(color_code)
        self.opacity_spin.setValue(opacity)

    def _select_uid(self, uid):
        self._set_selected_uids([uid] if uid else [])

    def select_at(self, x, y, cycle=False, additive=False):
        if not self.doc:
            return
        if self._raster_map_picker is not None:
            callback = self._raster_map_picker
            self._raster_map_picker = None
            callback(x, y)
            return
        candidates = self._pick_candidates(x, y)
        uids = [obj.uid for obj in candidates]
        # A click on an A1/A2 text must select its owner directly. This
        # eliminates repeated cycling through background parcels/land-use.
        screen_point = self.view.mapFromScene(QPointF(x, -y))
        same_spot = (self._last_pick_pos is not None and
                     (screen_point - self._last_pick_pos).manhattanLength() <= 12 and
                     tuple(uids) == self._last_pick_candidates)
        if not additive and not cycle and not same_spot:
            for item in self.view.items(screen_point):
                uid, field = item.data(0), item.data(1)
                if (field in {'A1', 'A2'} and uid in self.doc.by_id and
                        self.doc.by_id[uid].code == '5310' and
                        self.layer_for_uid.get(uid, '') not in self.hidden_layers and
                        self.doc.by_id[uid].is_closed and
                        point_in_ring(x, y, [(p.x, p.y)
                                            for p in self.doc.by_id[uid].points[:-1]])):
                    self._last_pick_pos = screen_point
                    self._last_pick_candidates = tuple(uids)
                    self._select_uid(uid)
                    self.status.showMessage(
                        f'Wybrano kod {self.doc.by_id[uid].code} poprzez etykietę {field}. '
                        'Kliknij ponownie, aby przejść do kolejnego obiektu.')
                    return
        if not uids:
            self._last_pick_pos = None
            self._last_pick_candidates = ()
            if not additive:
                self._set_selected_uids([])
            return
        # Prefer a small building 5310 over large overlapping land-use and
        # parcel backgrounds on the first click. Repeated clicks still
        # cycle the *entire* candidate list, one object per click.
        if not cycle and not additive and self.selected_uid not in uids:
            inside_buildings = [
                uid for uid in uids
                if (self.doc.by_id[uid].code == '5310' and
                    self.doc.by_id[uid].is_closed and
                    point_in_ring(x, y, [(p.x, p.y)
                                        for p in self.doc.by_id[uid].points[:-1]]))
            ]
            if inside_buildings:
                uids = inside_buildings + [
                    uid for uid in uids if uid not in inside_buildings]
        screen = self.view.mapFromScene(QPointF(x, -y))
        repeat = (self._last_pick_pos is not None and
                  (screen - self._last_pick_pos).manhattanLength() <= 12 and
                  tuple(uids) == self._last_pick_candidates)
        self._last_pick_pos = screen
        self._last_pick_candidates = tuple(uids)
        uid = resolve_click(uids, self.selected_uid, cycle=cycle, repeat=repeat)
        if additive:
            self._set_selected_uids(toggle_selection(self.selected_uids, uid))
        else:
            self._select_uid(uid)
        self.status.showMessage(
            f'Wybrano kod {self.doc.by_id[uid].code}. '
            f'Łącznie zaznaczono: {len(self.selected_uids)}. '
            'Ctrl+klik dodaje/usuwa, Ctrl+H otwiera wybór po kodzie i atrybutach.')

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
        return snap_at(self._selection_context(self._map_radius(12)), x, y,
                       exclude_uid=exclude_uid,
                       enabled=self.snap_action.isChecked(),
                       include_hidden_markers=True)

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
        if hasattr(self, 'layer_filter'):
            self._filter_layer_rows(self.layer_filter.text())
        self._populate_layer_code_styles()

    def _default_fill_opacity(self):
        """Let WMS/rasters show through without washing out a plain MAP."""
        wms_visible = (self._wms_preview.image is not None and
                       self._wms_preview.visible)
        raster_visible = any(layer.calibrated and layer.visible
                             for layer in self._raster_overlay.layers)
        return 60 if (wms_visible or raster_visible) else 100

    def _populate_layer_code_styles(self):
        if not hasattr(self, 'layer_code_choice') or not self.doc:
            return
        previous = self.layer_code_choice.currentData()
        counts = defaultdict(int)
        for obj in self.doc.objects:
            if obj.is_closed:
                counts[obj.code] += 1
        self.layer_code_choice.blockSignals(True)
        self.layer_code_choice.clear()
        for code in sorted(counts):
            self.layer_code_choice.addItem(
                f'{code} · {self.symbols.get(code, resolve_layer(self.catalog, code))} ({counts[code]})',
                code)
        index = self.layer_code_choice.findData(previous)
        self.layer_code_choice.setCurrentIndex(index if index >= 0 else 0)
        self.layer_code_choice.blockSignals(False)
        self._select_layer_code_style()

    def _select_layer_code_style(self, *_args):
        code = self.layer_code_choice.currentData()
        if code is None:
            return
        current = self.visual_styles.get('code:' + code, {})
        value = current.get('opacity', self._default_fill_opacity())
        self.layer_code_opacity.blockSignals(True)
        self.layer_code_opacity.setValue(value)
        self.layer_code_opacity.blockSignals(False)
        self.layer_code_opacity_label.setText(f'{value}%')

    def _code_opacity_moved(self, value):
        self.layer_code_opacity_label.setText(f'{value}%')
        code = self.layer_code_choice.currentData()
        if code is not None and self.doc:
            self._pending_code_style = (code, value)
            self._code_opacity_timer.start()

    def _commit_code_opacity(self):
        self._code_opacity_timer.stop()
        pending, self._pending_code_style = self._pending_code_style, None
        if pending is None or not self.doc:
            return
        code, opacity = pending
        key = 'code:' + code
        before = self.visual_styles.get(key, {})
        if before.get('opacity', self._default_fill_opacity()) == opacity:
            return
        with self.history.begin(f'Krycie poligonów kodu {code}'):
            self.visual_styles[key] = {**before, 'opacity': opacity}
        self._history_changed()
        self._refresh_fill_brushes(code=code, force=True)
        self._autosave_work_copy()
        self.status.showMessage(
            f'Kod {code}: krycie {opacity}%. Styl zapisany w kopii GeoStudio.')

    def _choose_code_color(self):
        code = self.layer_code_choice.currentData()
        if not code or not self.doc:
            return
        key = 'code:' + code
        old = self.visual_styles.get(key, {})
        initial = old.get('fill', '#8AAFC6')
        color = QColorDialog.getColor(QColor(initial), self, f'Kolor kodu {code}')
        if not color.isValid():
            return
        with self.history.begin(f'Kolor poligonów kodu {code}'):
            self.visual_styles[key] = {
                **old, 'opacity': old.get('opacity', self._default_fill_opacity()),
                'fill': color.name().upper()}
        self._history_changed()
        self._refresh_fill_brushes(code=code, force=True)
        self._autosave_work_copy()

    def _reset_code_style(self):
        code = self.layer_code_choice.currentData()
        key = 'code:' + str(code)
        if not code or key not in self.visual_styles or not self.doc:
            return
        with self.history.begin(f'Przywrócenie wyglądu kodu {code}'):
            self.visual_styles.pop(key, None)
        self._history_changed()
        self._select_layer_code_style()
        self._refresh_fill_brushes(code=code, force=True)
        self._autosave_work_copy()

    def _refresh_fill_brushes(self, *, code=None, force=False):
        """Update native/CDF brushes in place; never rebuild the whole map."""
        if not self.doc or not hasattr(self, 'fill_items_for_uid'):
            return
        default = self._default_fill_opacity()
        if code is None and not force and self._last_fill_opacity == default:
            return
        ctx = self._render_context()
        for obj in self.doc.objects:
            if code is not None and obj.code != code:
                continue
            item = self.fill_items_for_uid.get(obj.uid)
            if item is None:
                continue
            if obj.code == '5200' and len(obj.points) == 4 and obj.fields.get('FA') == '0':
                continue  # Opaque black parts of the compass rose.
            item.setBrush(object_fill_brush(obj, ctx))
        self._last_fill_opacity = default
        if code is None:
            self._select_layer_code_style()

    def _filter_layer_rows(self, query):
        """Filter the layer list only; never hide geometry on the map."""
        needle = query.strip().casefold()
        matches = 0
        total = self.layers_tree.topLevelItemCount()
        for i in range(total):
            node = self.layers_tree.topLevelItem(i)
            visible = needle in node.text(0).casefold()
            node.setHidden(not visible)
            matches += visible
        self.layers_summary.setText(
            f'{matches} z {total} warstw' if needle else f'{total} warstw')

    def _set_all_layers_visible(self, visible):
        """One bulk visibility change, without repeated signal/scene rebuilds."""
        tree = self.layers_tree
        tree.blockSignals(True)
        try:
            for i in range(tree.topLevelItemCount()):
                node = tree.topLevelItem(i)
                node.setCheckState(0, Qt.Checked if visible else Qt.Unchecked)
                for graphic in self.items_by_layer.get(node.text(0), []):
                    graphic.setVisible(visible)
                if visible:
                    self.hidden_layers.discard(node.text(0))
                else:
                    self.hidden_layers.add(node.text(0))
        finally:
            tree.blockSignals(False)
        if self.doc:
            selected = [uid for uid in self.selected_uids
                        if self.layer_for_uid.get(uid) not in self.hidden_layers]
            if selected != self.selected_uids:
                self._set_selected_uids(selected)
            else:
                self.update_label_visibility()

    def on_layer_toggle(self,item,column):
        state=item.checkState(0)==Qt.Checked
        for graphic in self.items_by_layer.get(item.text(0),[]):graphic.setVisible(state)
        if state:
            self.hidden_layers.discard(item.text(0))
        else:
            self.hidden_layers.add(item.text(0))
        # A hidden layer must not keep a ghost selection overlay; labels
        # belonging to other visible layers retain their previous positions.
        selected = [uid for uid in self.selected_uids
                    if self.layer_for_uid.get(uid) not in self.hidden_layers]
        if selected != self.selected_uids:
            self._set_selected_uids(selected)
        else:
            self.update_label_visibility()

    def _update_fill_preview(self, *_args):
        """Show the actual selected fill with the requested opacity."""
        if not hasattr(self, 'fill_preview'):
            return
        try:
            color, opacity = parse_fill_code(
                self.fill_entry.text(), self.opacity_spin.value())
            rgb = QColor(color)
            preview = rgb if opacity >= 100 else QColor(
                round(rgb.red() * opacity / 100 + 240 * (100 - opacity) / 100),
                round(rgb.green() * opacity / 100 + 244 * (100 - opacity) / 100),
                round(rgb.blue() * opacity / 100 + 248 * (100 - opacity) / 100))
            ink = '#17273B' if preview.lightness() > 145 else '#FFFFFF'
            self.fill_preview.setText(f'{color}  ·  krycie {opacity}%')
            self.fill_preview.setStyleSheet(
                'background-color: ' + preview.name() + '; color: ' + ink +
                '; border: 1px solid #8397A9; border-radius: 9px;')
        except (ValueError, TypeError):
            self.fill_preview.setText('Wpisz prawidłowy kolor #RRGGBB')
            self.fill_preview.setStyleSheet('')

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
        with self.history.begin(f'Wypełnienie {len(self.selected_uids)} obiektów',
                                selection_before=self.selected_uids):
            for uid in self.selected_uids:
                obj = self.doc.by_id.get(uid)
                if obj and (obj.is_closed or all(
                    len(p) >= 4 and (p[0].x, p[0].y) == (p[-1].x, p[-1].y)
                    for p in obj.display_parts)):
                    self.visual_styles[uid] = {'fill': color, 'opacity': opacity}
                    modified.append(uid)
        self._history_changed()
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

    def show_active_object_parameters(self):
        """Open E: full attributes and source coordinates for the active object."""
        if not self.doc or not self.selected_uid:
            QMessageBox.information(
                self, 'Parametry aktywnego obiektu',
                'Zaznacz najpierw obiekt na mapie (S).')
            return
        uid = self.selected_uid
        obj = self.doc.by_id[uid]
        dialog = ObjectParametersDialog(
            obj, symbols=self.symbols,
            layer_name=resolve_layer(self.catalog, obj.code), parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        changes = dialog.changed_fields()
        if not changes:
            return
        try:
            with self.history.begin('Parametry obiektu ' + obj.code,
                                    selection_before=self.selected_uids) as tx:
                for key, value in changes.items():
                    self.doc.update_field(uid, key, value)
                tx.set_selection_after(self.selected_uids)
            self._history_changed()
            self.cancel_edit()
            self.rebuild_scene(fit=False, reselect=uid)
            self.status.showMessage(
                f'Zapisano {len(changes)} atrybutów obiektu {obj.code}. '
                'Ctrl+Z cofa zmianę. Zapisz kopię MAP, aby zachować dane.')
        except Exception as exc:
            QMessageBox.warning(self, 'Nie udało się zapisać parametrów', str(exc))

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
            with self.history.begin(f'Zmiana {key} obiektu {uid[:8]}',
                                    selection_before=self.selected_uids) as tx:
                self.doc.update_field(uid,key,text)
                tx.set_selection_after([uid])
            self._history_changed()
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
                  'Ta operacja usuwa CAŁE rekordy; można ją cofnąć (Ctrl+Z).\\n'
                  'Oryginalny MAP pozostaje nietknięty.')
        answer = QMessageBox.question(self, 'Potwierdź usunięcie', prompt,
                                      QMessageBox.Yes | QMessageBox.No,
                                      QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.cancel_edit()
        with self.history.begin(f'Usunięcie {count} obiektów',
                                selection_before=selected):
            self.doc.delete_objects(selected)
            for uid in selected:
                self.visual_styles.pop(uid, None)
                self.label_positions.pop(uid, None)
        self._history_changed()
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
            if (self.visual_styles or self.label_positions) and sidecar_path(file).exists():
                raise FileExistsError('Plik stylów o tej nazwie już istnieje.')
            self.doc.save_as(file)
        except Exception as exc:
            QMessageBox.warning(self, 'Zapis przerwany', str(exc))
            return
        if self.visual_styles or self.label_positions:
            try:
                write_styles(file, self.visual_styles,
                             label_positions=self.label_positions)
            except Exception as exc:
                # The map is on disk, the sidecar is not: not a complete save,
                # so the save point must not move.
                QMessageBox.warning(self, 'Zapis częściowy',
                    'Plik MAP został zapisany, ale stylów GeoStudio nie udało się '
                    f'zapisać: {exc}\nPunkt zapisu nie został przesunięty.')
                return
        self.history.mark_saved()
        self._update_dirty_title()
        QMessageBox.information(self, 'Zapisano eksperymentalną MAP',
            'Utworzono nowy plik MAP. Osobne wypełnienia (jeśli używane) '
            'są zapisane w towarzyszącym pliku *.geostudio.json i nie '
            'są interpretowane przez GEO-MAP. Sprawdź kopię w GEO-MAP. '
            'Oryginał nie został nadpisany.')

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

    @staticmethod
    def _geodetic_transform():
        """View-space correction: scene (X,-Y) -> screen (Y,-X)."""
        return QTransform(0, -1, -1, 0, 0, 0)

    def _apply_orientation(self, transform, *, geodetic, rotation):
        if self.view.draw_mode or self.view.edit_mode:
            # Changing view orientation mid-edit is safe geometrically,
            # but disorienting; first exit the active interaction mode.
            self.cancel_edit()
        center = self.view.mapToScene(self.view.viewport().rect().center())
        existing = self.view.transform()
        zoom = math.hypot(existing.m11(), existing.m12())
        # Resetting orientation should not throw the user back to another zoom.
        self.view.setTransform(transform.scale(zoom, zoom))
        self.view.centerOn(center)
        self.orientation_is_geodetic = geodetic
        self.view_rotation_degrees = rotation % 360
        self.update_label_visibility()
        self.status.showMessage(
            f'Orientacja: {"GEO-MAP" if geodetic else "techniczna"}'
            f' • obrót {self.view_rotation_degrees}°. Współrzędne MAP nie są zmieniane.')

    def reset_orientation(self):
        self._apply_orientation(self._geodetic_transform(), geodetic=True,
                                rotation=0)

    def legacy_orientation(self):
        self._apply_orientation(QTransform(), geodetic=False, rotation=0)

    def rotate_view(self, degrees):
        """Rotate the viewport about its center, not the stored world coords."""
        center = self.view.mapToScene(self.view.viewport().rect().center())
        self.view.rotate(degrees)
        self.view.centerOn(center)
        self.view_rotation_degrees = (self.view_rotation_degrees + degrees) % 360
        self.update_label_visibility()
        self.status.showMessage(
            f'Obrót widoku: {self.view_rotation_degrees}°. '
            'Obiekty i zapisane współrzędne pozostają bez zmian.')

    def _setup_scale_widget(self):
        """Visible map scale, estimated from Qt's logical screen DPI."""
        self.coordinate_readout = QLabel('X —   Y —')
        self.coordinate_readout.setObjectName('GeoStudioCoordinateReadout')
        self.coordinate_readout.setToolTip('Pozycja kursora w źródłowym układzie współrzędnych GEO-MAP')
        self.status.addPermanentWidget(self.coordinate_readout)
        self.mode_badge = QLabel('ZAZNACZANIE')
        self.mode_badge.setObjectName('GeoStudioModeBadge')
        self.mode_badge.setToolTip('Aktywny tryb pracy, zmienisz go na górnym pasku')
        self.status.addPermanentWidget(self.mode_badge)
        self.status.addPermanentWidget(QLabel('Skala widoku:'))
        self.scale_combo = QComboBox(self)
        self.scale_combo.setObjectName('GeoStudioScale')
        self.scale_combo.setEditable(True)
        self.scale_combo.setMinimumWidth(115)
        self.scale_combo.addItems(['1:500', '1:1000', '1:2000', '1:5000',
                                   '1:10000', '1:25000'])
        self.scale_combo.setCurrentText('1:1000')
        self.scale_combo.activated.connect(lambda _idx: self.apply_view_scale())
        self.scale_combo.lineEdit().returnPressed.connect(self.apply_view_scale)
        self.status.addPermanentWidget(self.scale_combo)
        self.compilation_label=QLabel(self)
        self.compilation_label.setObjectName('GeoStudioCompilationScale')
        self.status.addPermanentWidget(self.compilation_label)
        self.wms_source_label = QLabel(self)
        self.wms_source_label.setObjectName('GeoStudioWMSSource')
        self.wms_source_label.setVisible(False)
        self.status.addPermanentWidget(self.wms_source_label)
        self._update_compilation_scale_indicator()

    @staticmethod
    def _compilation_scale_key(path):
        """Per-file local setting: does not modify source MAP or GEO-MAP data."""
        return 'compilation_scale/' + hashlib.sha256(
            str(Path(path).resolve()).encode('utf-8')).hexdigest()

    def _update_compilation_scale_indicator(self):
        if not hasattr(self,'compilation_label'):
            return
        self.compilation_label.setText(f'Opracowanie 1:{self.compilation_scale}')
        self.compilation_label.setToolTip(
            f'Skala prezentacji napisów, niezależna od skali '
            f'widoku. Skala odczytana z legendy: 1:{self.source_compilation_scale}. '
            'Ctrl+F5 zmienia ustawienie w GeoStudio (nie oryginalny MAP).')

    def set_compilation_scale(self, denominator: int):
        """Update the cartographic presentation scale without map geometry edits."""
        denominator = validated_compilation_scale(denominator)
        if denominator is None:
            raise ValueError('Skala opracowania 1:N musi być od 1:100 do 1:1000000.')
        self.compilation_scale=denominator
        if self.doc and self.doc.filename:
            self.settings.setValue(
                self._compilation_scale_key(self.doc.filename),denominator)
        self._update_compilation_scale_indicator()
        self.update_label_visibility()
        self.status.showMessage(
            f'Skala opracowania GeoStudio ustawiona na 1:{denominator}. '
            'Zmienia prezentację napisów, nie skalę widoku ani danych GEO-MAP.')

    def ask_compilation_scale(self):
        if not self.doc:
            QMessageBox.information(self,'Skala opracowania',
                                   'Najpierw otwórz mapę MAP.')
            return
        value, accepted = QInputDialog.getInt(
            self,'Skala opracowania (Ctrl+F5)',
            'Skala opracowania 1:N — rozmiar napisów i opisu arkusza.\n'
            'Skala widoku w dolnym pasku jest niezależna.\n'
            'To ustawienie GeoStudio, nie modyfikuje oryginalnej MAP:',
            self.compilation_scale,100,1_000_000,100)
        if accepted:
            self.set_compilation_scale(value)

    def _view_pixel_scale(self):
        t = self.view.transform()
        return math.hypot(t.m11(), t.m12())

    def _display_denominator(self):
        px_per_m = self._view_pixel_scale()
        if px_per_m < 1e-8:
            return 0
        # 1 m in projected coordinates is 1000 mm on the ground.
        # pixel units are Qt logical screen pixels, not printer resolution.
        return self.view.logicalDpiX() / 0.0254 / px_per_m

    def update_view_scale_indicator(self):
        if not hasattr(self, 'scale_combo') or not self.doc:
            return
        den = self._display_denominator()
        if not (math.isfinite(den) and 1 <= den <= 1e9):
            return
        self.scale_combo.blockSignals(True)
        self.scale_combo.setCurrentText(f'1:{round(den):d}')
        self.scale_combo.blockSignals(False)

    def apply_view_scale(self):
        if not self.doc:
            return
        raw = self.scale_combo.currentText().strip().replace(' ', '').replace(',', '.')
        try:
            denominator = float(raw.split(':')[-1])
            if len(raw.split(':')) > 2 or not (10 <= denominator <= 10000000):
                raise ValueError('Skala 1:N musi być między 1:10 a 1:10000000')
            if not math.isfinite(denominator):
                raise ValueError('Wybierz poprawny mianownik skali')
            current = self._view_pixel_scale()
            target = self.view.logicalDpiX() / .0254 / denominator
            factor = target / current
            if not (1e-5 <= current * factor <= 4000):
                raise ValueError('Ta skala wykracza poza zakres wyświetlania')
            center = self.view.mapToScene(self.view.viewport().rect().center())
            self.view.scale(factor, factor)
            self.view.centerOn(center)
            self._wms_auto.viewport_changed()
            self.update_label_visibility()
            self.status.showMessage(
                f'Ustawiono przybliżoną skalę ekranu 1:{denominator:g}. '
                'Nie zmieniono współrzędnych ani skali wydruku GEO-MAP.')
        except (ValueError,ZeroDivisionError) as exc:
            QMessageBox.warning(self,'Nieprawidłowa skala',str(exc))
            self.update_view_scale_indicator()

    def ask_view_scale(self):
        if not self.doc:
            return
        value, ok = QInputDialog.getText(
            self,'Skala widoku', 'Podaj skalę 1:N, np. 1:2000',
            text=self.scale_combo.currentText())
        if ok:
            self.scale_combo.setCurrentText(value)
            self.apply_view_scale()

    def fit_all(self):
        if not self.doc:
            return
        rect = self._world_scene_rect()
        if rect.isEmpty():
            return
        self.map_scene.setSceneRect(self._navigation_scene_rect())
        self.view.fitInView(rect, Qt.KeepAspectRatio)
        self._wms_auto.viewport_changed()
        self.update_label_visibility()

    def on_coordinate(self,x,y):
        # Persistent readout: moving the cursor should not erase status tips,
        # undo feedback or save warnings from the message area.
        if hasattr(self, 'coordinate_readout'):
            self.coordinate_readout.setText(f'X {x:.3f}    Y {y:.3f}')
        else:
            self.status.showMessage(f'Współrzędne: X={x:.3f} | Y={y:.3f}')

    def cancel_edit(self):
        self.view.draw_mode = False
        self.view.edit_mode = False
        self.view.pan_mode = False
        self.view.label_mode = False
        self.view._label_down = False
        self._active_label = None
        self.view.setCursor(Qt.ArrowCursor)
        if hasattr(self, "tool_actions"):
            self.tool_actions["select"].setChecked(True)
        self.view.dragged_vertex = None
        self.view.edit_points = []
        self.view.setDragMode(QGraphicsView.NoDrag)
        self._set_mode_badge('ZAZNACZANIE')
        self.view._pan_button = None
        self.view._pan_last = None
        if hasattr(self, 'finish_toolbar_action'):
            self.finish_toolbar_action.setVisible(False)
            self.finish_action.setEnabled(False)
        self.current_polygon = []
        self.edit_uid = ''
        self.edit_scope_code = ''
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
        """N shortcut / ribbon entry for creating a new polygon."""
        if not self.doc:
            return
        code, ok = QInputDialog.getText(
            self, 'Nowy poligon', 'Kod GEO-MAP:', text=self.polygon_code)
        if ok:
            self._start_polygon_with_code(code)

    def _start_polygon_with_code(self, code):
        if not self.doc:
            return
        code = str(code).strip()
        if not code.isdigit() or len(code) != 4:
            QMessageBox.warning(self, 'Kod', 'Kod musi składać się z czterech cyfr.')
            return
        self.cancel_edit()
        self.polygon_code = code
        self.current_polygon = []
        self.view.draw_mode = True
        self.view.setCursor(Qt.CrossCursor)
        self.tool_actions['draw'].setChecked(True)
        self._set_mode_badge('RYSOWANIE POLIGONU')
        self.view.setDragMode(QGraphicsView.NoDrag)
        self._ensure_feedback_items()
        self.finish_toolbar_action.setVisible(True)
        self.undo_toolbar_action.setVisible(True)
        self.finish_action.setEnabled(True)
        self.status.showMessage(
            f'Rysowanie kodu {code}: klikaj wierzchołki. Enter lub PPM kończy '
            'poligon; Esc cofa ostatni punkt.')

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
            self.status.showMessage('Brak punktów do cofnięcia. Narzędzie N nadal aktywne.')
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
            with self.history.begin(f'Nowy poligon {self.polygon_code}'):
                uid = self.doc.append_polygon(points, self.polygon_code, fields=attrs)
            self._history_changed()
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
        if (not self.visual_styles and not self.label_positions and
                self._auto_style_digest is None):
            return
        if self._auto_style_digest is None:
            write_styles(self._auto_copy_path, self.visual_styles, overwrite=False,
                         label_positions=self.label_positions)
        else:
            if not target.is_file() or hashlib.sha256(
                    target.read_bytes()).digest() != self._auto_style_digest:
                raise RuntimeError('Plik stylów zmieniono poza GeoStudio; nie nadpisuję go.')
            write_styles(self._auto_copy_path, self.visual_styles, overwrite=True,
                         label_positions=self.label_positions)
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
        tolerance = math.hypot(edge.x() - origin.x(), edge.y() - origin.y())
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
            with self.history.begin('Wstawienie wierzchołka',
                                    selection_before=[uid]):
                self.doc.insert_polygon_vertex(uid, index, px, py)
            self._history_changed()
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
            QMessageBox.information(
                self, 'Edycja wierzchołków', 'Zaznacz najpierw poligon.')
            return
        obj = self.doc.by_id[self.selected_uid]
        if not obj.is_closed:
            QMessageBox.warning(
                self, 'Edycja', 'Wybrany obiekt nie jest zamkniętym poligonem.')
            return
        uid, code = self.selected_uid, obj.code
        self.cancel_edit()
        self.edit_scope_code = code
        self._activate_vertex_object(uid)
        self.status.showMessage(
            f'Węzły kodu {code}: przeciągnij dowolny węzeł poligonu o tym kodzie. '
            'Wspólne węzły sąsiadów tego samego kodu zmienią się razem. '
            'Przyciąganie działa do linii i graniczników innych kodów. Esc kończy.')

    def _activate_vertex_object(self, uid):
        """Switch active vertex handles without leaving the edit tool."""
        obj = self.doc.by_id.get(uid) if self.doc else None
        if not obj or not obj.is_closed or obj.code != self.edit_scope_code:
            return
        if uid != self.selected_uid:
            self._set_selected_uids([uid])
        self.edit_uid = uid
        self.view.edit_mode = True
        self.view.setCursor(Qt.CrossCursor)
        self.tool_actions['edit'].setChecked(True)
        self._set_mode_badge('EDYCJA WIERZCHOŁKÓW')
        self.view.edit_points = [(p.x, p.y) for p in obj.points[:-1]]
        self.view.setDragMode(QGraphicsView.NoDrag)
        for handle in self.edit_handles:
            if handle.scene() is self.map_scene:
                self.map_scene.removeItem(handle)
        self.edit_handles = []
        self._ensure_feedback_items()
        self.draft_item.setPath(self._path_for(obj))
        for px, py in self.view.edit_points:
            handle = QGraphicsEllipseItem(-4, -4, 8, 8)
            handle.setPos(px, -py)
            handle.setPen(QPen(QColor('#ffffff'), 1))
            handle.setBrush(QBrush(QColor('#0d9a90')))
            handle.setFlag(
                QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            handle.setAcceptedMouseButtons(Qt.NoButton)
            handle.setZValue(1200)
            self.map_scene.addItem(handle)
            self.edit_handles.append(handle)

    def activate_vertex_at(self, x, y):
        """Find the closest editable vertex across ALL visible objects of code."""
        if not self.doc or not self.view.edit_mode or not self.edit_scope_code:
            return
        radius = self._map_radius(20)
        pos = self.view.mapFromScene(QPointF(x, -y))
        best = None
        for obj in self.geometry_index.nearby(x, y, radius):
            if (obj.code != self.edit_scope_code or not obj.is_closed or
                    self.layer_for_uid.get(obj.uid, '') in self.hidden_layers):
                continue
            for p in obj.points[:-1]:
                pixel = self.view.mapFromScene(QPointF(p.x, -p.y))
                distance = (pixel - pos).manhattanLength()
                if distance <= 18 and (best is None or distance < best[0]):
                    best = (distance, obj.uid)
        if best is not None and best[1] != self.edit_uid:
            self._activate_vertex_object(best[1])

    def _refresh_changed_geometry(self, uids):
        """Refresh only changed polygon graphics, not thousands of scene items."""
        for uid in uids:
            obj = self.doc.by_id.get(uid)
            if obj is None:
                continue
            path = self._path_for(obj)
            item = self.graphics_for_uid.get(uid)
            if isinstance(item, QGraphicsPathItem):
                item.setPath(path)
            fill = self.fill_items_for_uid.get(uid)
            if fill is not None:
                fill.setPath(path)
            anchor = self._label_anchor(obj)
            if anchor:
                for field in ('A1', 'A2', 'A3'):
                    label = self.label_items.get((uid, field))
                    if label is not None and not self.label_positions.get(uid, {}).get(field):
                        label.setPos(anchor[0], -anchor[1])
        # GeometryIndex stores a spatial hash of bounding boxes; refreshed
        # coordinate objects require fresh tile occupancy after vertex movement.
        self.geometry_index = GeometryIndex(
            self.doc.objects, hide_connectors=self.hide_multipart_connectors)
        if self.highlight_item is not None:
            self.highlight_item.setPath(
                highlight_path(self.doc, self.selected_uids,
                               hide_connectors=self.hide_multipart_connectors))
        if self.selected_uid in uids:
            self._show_selection_properties()

    def preview_vertex(self, x, y, index):
        if (not self.view.edit_mode or not self.edit_uid or
                not 0 <= index < len(self.view.edit_points)):
            return
        snap = self._snap(x, y, exclude_uid=self.edit_uid)
        # Snapping may target ANY code, including survey markers. This
        # determines only the new coordinate; linked_vertex_moves below is
        # responsible for updating same-code neighbours exclusively.
        # Ignore an unchanged shared point so the drag does not stick there.
        if snap and math.hypot(
                snap.x - self.view.edit_points[index][0],
                snap.y - self.view.edit_points[index][1]) <= self._map_radius(6):
            snap = None
        px, py = (snap.x,snap.y) if snap else (x,y)
        pts = self.view.edit_points[:]
        pts[index] = (px,py)
        if index < len(self.edit_handles):
            self.edit_handles[index].setPos(px,-py)
        self._ensure_feedback_items()
        self.draft_item.setPath(self._path_for(self.doc.by_id[self.edit_uid], pts + [pts[0]]))
        self.snap_marker.setVisible(True)
        self.snap_marker.setPos(px, -py)

    def commit_vertex(self, x, y, index):
        if not self.view.edit_mode or not self.edit_uid or not self.doc:
            return
        obj = self.doc.by_id.get(self.edit_uid)
        if obj is None or not 0 <= index < len(obj.points) - 1:
            return
        snap = self._snap(x, y, exclude_uid=self.edit_uid)
        # Read the original coordinate from the document, not temporary
        # handles: mouse-driven edits and undo tests both use this path.
        old_point = obj.points[index]
        if snap and math.hypot(
                snap.x - old_point.x, snap.y - old_point.y) <= self._map_radius(6):
            snap = None
        px, py = (snap.x,snap.y) if snap else (x,y)
        try:
            uid = self.edit_uid
            changes = linked_vertex_moves(self.doc, uid, index, px, py)
            with self.history.begin('Przesunięcie wspólnego węzła',
                                    selection_before=[uid]):
                self.doc.move_polygon_vertices(changes, reparse=False)
            self._history_changed()
            # A vertex edit must not call rebuild_scene() for the entire map:
            # preserve the canvas and update just affected polygons.
            self._refresh_changed_geometry(changes)
            self._activate_vertex_object(uid)
            saved = self._autosave_work_copy()
            count = len(changes) - 1
            message = (f'Przesunięto węzeł i zsynchronizowano {count} poligonów '
                       f'tego samego kodu.' if count else 'Przesunięto węzeł.')
            self.status.showMessage(message +
                                    (f' Kopia: {saved}' if saved else ' Zapisz jako nowy MAP.'))
        except Exception as exc:
            QMessageBox.warning(self,'Nie zmieniono geometrii',str(exc))
            self.cancel_edit()
            self.rebuild_scene(fit=False,reselect=self.selected_uid)

    def _refresh_raster_panel(self):
        if hasattr(self, 'raster_panel'):
            self.raster_panel.refresh()
        self._refresh_fill_brushes()

    def _save_raster_settings(self):
        if self.doc and self.doc.filename:
            return self._raster_overlay.save(self.doc.filename)
        return None

    def show_raster_panel(self):
        """Select raster tab inside the existing left contents dock."""
        self.layers_dock.show()
        self.raster_tabs.setCurrentWidget(self.raster_panel)
        self._refresh_raster_panel()

    def _update_wms_attribution(self):
        label = getattr(self, 'wms_source_label', None)
        if label is None:
            return
        overlay = self._wms_preview
        if overlay.image is None:
            label.hide()
            self._refresh_fill_brushes()
            return
        name = overlay.title or 'usługa WMS'
        label.setText('WMS: ' + name[:36] + ('…' if len(name) > 36 else ''))
        label.setToolTip('Źródło WMS: ' + name)
        label.show()
        self._refresh_fill_brushes()

    def show_wms_dialog(self):
        if not self.doc:
            QMessageBox.information(self, 'WMS', 'Najpierw otwórz mapę GEO-MAP.')
            return
        if self._wms_dialog is None:
            self._wms_dialog = WMSDialog(self)
        self._wms_dialog.show()
        self._wms_dialog.raise_()

    def open_google_maps(self):
        """Open the complete Google Earth Web site inside Qt WebEngine."""
        if not self.doc:
            QMessageBox.information(self, 'Google Earth', 'Najpierw otwórz mapę.')
            return
        if self._google_dialog is None:
            self._google_dialog = GoogleMapsPreviewDialog(self)
        self._google_dialog.show()
        self._google_dialog.raise_()

    def add_raster(self):
        """Import an image; use world file or launch interactive GCP calibration."""
        if not self.doc:
            QMessageBox.information(self, 'Raster', 'Najpierw otwórz mapę GEO-MAP.')
            return
        file, _ = QFileDialog.getOpenFileName(
            self, 'Dodaj podkład rastrowy',
            self._recent_folder('last_raster_dir'),
            'Obrazy (*.png *.jpg *.jpeg *.tif *.tiff *.bmp)')
        if not file:
            return
        try:
            layer = self._raster_overlay.add(file)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, 'Nie można dodać rastra', str(exc))
            return
        self.settings.setValue('last_raster_dir', str(Path(file).parent))
        self.show_raster_panel()
        if layer.calibrated:
            self._raster_overlay.attach(self.map_scene)
            try:
                self._save_raster_settings()
            except OSError as exc:
                QMessageBox.warning(self, 'Nie zapisano ustawień podkładu', str(exc))
            self.status.showMessage(
                f'Pod mapą: {Path(file).name}. Raster ma georeferencję z pliku world.')
        else:
            self.status.showMessage(
                'Raster nie ma pliku world. Wskaż 3 lub więcej par punktów, aby go skalibrować.')
            self._open_raster_calibration(layer)

    def calibrate_selected_raster(self):
        if not self.doc:
            QMessageBox.information(self, 'Kalibracja', 'Najpierw otwórz mapę.')
            return
        layer = self.raster_panel.selected_layer()
        if layer is None and self._raster_overlay.layers:
            layer = self._raster_overlay.layers[-1]
        if layer is None:
            self.add_raster()
            return
        self._open_raster_calibration(layer)

    def _open_raster_calibration(self, layer):
        if self._raster_calibration_dialog is not None:
            self._raster_calibration_dialog.close()
        # This window is intentionally non-modal: the live GEO-MAP canvas
        # must stay clickable when capturing a corresponding world point.
        dialog = RasterCalibrationDialog(self, layer)
        self._raster_calibration_dialog = dialog
        dialog.show()
        dialog.raise_()

    def export_image(self):
        if not self.doc:return
        file,_=QFileDialog.getSaveFileName(self,'Eksport widoku mapy',str(Path.home()/'mapa.png'),
            'PNG (*.png);;JPEG (*.jpg);;TIFF (*.tif)')
        if not file:return
        try:
            img=render_scene_image(self.map_scene)
            if img is None:return
            if not save_image(img,file):
                # TIFF writer availability is platform-dependent.
                raise RuntimeError('Format niedostępny w tej instalacji Qt; wybierz PNG/JPG.')
            self.status.showMessage('Zapisano obraz: '+file)
        except Exception as exc:QMessageBox.warning(self,'Błąd eksportu',str(exc))

    def export_dxf(self):
        if not self.doc:return
        file,_=QFileDialog.getSaveFileName(self,'Eksport uproszczonego DXF',str(Path.home()/'mapa.dxf'),'AutoCAD DXF (*.dxf)')
        if not file:return
        try:
            write_dxf(self.doc,self.catalog,file)
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
