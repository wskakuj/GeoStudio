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
    from PySide6.QtCore import Qt, QPointF, QRectF, QSettings, Signal
    from PySide6.QtGui import QAction, QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QImage, QTransform
    from PySide6.QtWidgets import (QApplication, QMainWindow, QFileDialog, QGraphicsView, QGraphicsScene,
        QGraphicsPathItem, QGraphicsEllipseItem, QGraphicsPixmapItem, QGraphicsSimpleTextItem, QGraphicsItem, QDockWidget,
        QTreeWidget, QTreeWidgetItem, QToolBar, QMessageBox, QStatusBar, QInputDialog,
        QLabel, QWidget, QVBoxLayout, QHeaderView, QSplitter)
except ImportError as exc:
    raise SystemExit('Zainstaluj GUI: python -m pip install -e .\nBrakuje PySide6') from exc

from .geomap import GeoMap, GeoObject, library_layers, library_symbols, library_colors, resolve_layer

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
    coordinate = Signal(float, float)
    point_for_polygon = Signal(float, float)
    finish_polygon = Signal()

    def __init__(self, scene):
        super().__init__(scene)
        self.draw_mode=False
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setViewportUpdateMode(QGraphicsView.MinimalViewportUpdate)
        self.setBackgroundBrush(QBrush(QColor('#f7f9fb')))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def wheelEvent(self, event):
        factor=1.2 if event.angleDelta().y()>0 else 1/1.2
        self.scale(factor,factor)

    def mouseMoveEvent(self,event):
        pt=self.mapToScene(event.position().toPoint())
        self.coordinate.emit(pt.x(), -pt.y())
        super().mouseMoveEvent(event)

    def mousePressEvent(self,event):
        if self.draw_mode:
            if event.button()==Qt.RightButton:
                self.finish_polygon.emit();return
            if event.button()==Qt.LeftButton:
                pt=self.mapToScene(event.position().toPoint())
                self.point_for_polygon.emit(pt.x(),-pt.y());return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self,event):
        if self.draw_mode:
            self.finish_polygon.emit();return
        super().mouseDoubleClickEvent(event)


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
        self.layers_tree=None
        self.current_polygon:list[tuple[float,float]]=[]
        self.polygon_code='5216'
        self.map_scene=QGraphicsScene(self)
        self.map_scene.selectionChanged.connect(self.on_selection)
        self.view=MapView(self.map_scene)
        self.view.coordinate.connect(self.on_coordinate)
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
        em.addAction(self._action('Rysuj poligon',self.start_polygon,'P'))
        em.addAction(self._action('Edytuj atrybut zaznaczonego obiektu…',self.edit_selected,'F2'))
        vm=self.menuBar().addMenu('&Widok')
        vm.addAction(self._action('Dopasuj widok do mapy',self.fit_all,'Ctrl+0'))
        toolbar=QToolBar('Narzędzia',self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        for label,fn in [('📂 Otwórz',self.open_map),('💾 Zapisz jako',self.save_map),
                         ('◎ Cała mapa',self.fit_all),('⬡ Poligon',self.start_polygon),
                         ('▧ Raster',self.add_raster),('↗ DXF',self.export_dxf),('⬇ Obraz',self.export_image)]:
            toolbar.addAction(self._action(label,fn))

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
        label=QLabel('Wersja eksperymentalna. Kody, geometria i atrybuty są odczytywane z pliku. '
                     'Symbole i style GEO-MAP nie są jeszcze odwzorowane w 100%. '
                     'Rysowanie: klikaj wierzchołki, zakończ prawym przyciskiem myszy.')
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

    def rebuild_scene(self):
        if not self.doc:return
        self.map_scene.clear(); self.graphics_for_uid={}; self.items_by_layer=defaultdict(list)
        for obj in self.doc.objects:
            if not obj.points:continue
            layer=resolve_layer(self.catalog,obj.code)
            color=QColor(*obj.colorref)
            pen=QPen(color if obj.colorref!=(0,0,0) else QColor('#31455d'))
            pen.setCosmetic(True);pen.setWidth(1)
            if len(obj.points)==1:
                item=QGraphicsEllipseItem(-2.5,-2.5,5,5)
                item.setPos(obj.points[0].x,-obj.points[0].y)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations,True)
                item.setBrush(QBrush(color))
            else:
                path=QPainterPath(QPointF(obj.points[0].x,-obj.points[0].y))
                for p in obj.points[1:]:path.lineTo(p.x,-p.y)
                item=QGraphicsPathItem(path)
                if obj.is_closed:item.setBrush(QBrush(QColor(color.red(),color.green(),color.blue(),18)))
            item.setPen(pen)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable,True)
            item.setData(0,obj.uid or f'index:{obj.start}')
            item.setToolTip(f'Kod {obj.code} • {self.symbols.get(obj.code,layer)}\n{obj.fields.get("A2","")}')
            self.map_scene.addItem(item)
            self.items_by_layer[layer].append(item)
            if obj.uid:self.graphics_for_uid[obj.uid]=item
            # Approximate placement of explicit text objects. Full cartographic
            # rendering of font, size, angle and anchors still needs work.
            if obj.code.startswith('7') and obj.fields.get('TX'):
                text=obj.fields['TX'].replace('||','\n').replace('|',' ')
                text_item=QGraphicsSimpleTextItem(text)
                text_item.setBrush(QBrush(color))
                text_item.setPos(obj.points[0].x,-obj.points[0].y)
                text_item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations,True)
                text_item.setZValue(10)
                self.map_scene.addItem(text_item)
                self.items_by_layer[layer].append(text_item)
        self._populate_layers();self.fit_all()

    def _populate_layers(self):
        self.layers_tree.blockSignals(True)
        self.layers_tree.clear()
        for name,items in sorted(self.items_by_layer.items()):
            node=QTreeWidgetItem([name,str(len(items))]);node.setCheckState(0,Qt.Checked)
            self.layers_tree.addTopLevelItem(node)
        self.layers_tree.blockSignals(False)

    def on_layer_toggle(self,item,column):
        state=item.checkState(0)==Qt.Checked
        for graphic in self.items_by_layer.get(item.text(0),[]):graphic.setVisible(state)

    def on_selection(self):
        selected=self.map_scene.selectedItems();self.props.clear();self.selected_uid=''
        if not selected or not self.doc:return
        uid=selected[0].data(0)
        if uid not in self.doc.by_id:return
        obj=self.doc.by_id[uid];self.selected_uid=uid
        entries=[('Kod',obj.code),('Nazwa symbolu',self.symbols.get(obj.code,'—')),
                 ('Warstwa',resolve_layer(self.catalog,obj.code)),('ID',obj.uid),
                 ('Wierzchołki',str(len(obj.points)))]
        if obj.area_m2 is not None:
            entries.append(('Pole geometryczne',f'{obj.area_m2:,.3f} m² / {obj.area_m2/10000:,.4f} ha'))
        entries.extend((k,v) for k,v in obj.fields.items() if k!='ID')
        for k,v in entries:self.props.addTopLevelItem(QTreeWidgetItem([k,v]))

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
            self.map_scene.clearSelection()
            if uid in self.graphics_for_uid:
                self.graphics_for_uid[uid].setSelected(True)
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

    def fit_all(self):
        if not self.doc:return
        rect=self.map_scene.itemsBoundingRect()
        if rect.isEmpty():return
        self.map_scene.setSceneRect(rect.adjusted(-15,-15,15,15))
        self.view.fitInView(self.map_scene.sceneRect(),Qt.KeepAspectRatio)

    def on_coordinate(self,x,y):
        self.status.showMessage(f'Współrzędne źródłowe: X={x:.3f} | Y={y:.3f} | {"tryb rysowania" if self.view.draw_mode else "tryb zaznaczania"}')

    def start_polygon(self):
        if not self.doc:return
        code,ok=QInputDialog.getText(self,'Nowy poligon','Kod GEO-MAP:',text='5216')
        if not ok:return
        if not code.isdigit() or len(code)!=4:
            QMessageBox.warning(self,'Kod','Kod musi składać się z czterech cyfr');return
        self.polygon_code=code
        self.current_polygon=[]
        self.view.draw_mode=True
        self.view.setDragMode(QGraphicsView.NoDrag)
        self.status.showMessage('Kliknij co najmniej 3 wierzchołki. Prawy przycisk kończy poligon.')

    def add_polygon_point(self,x,y):
        self.current_polygon.append((x,y))
        self.status.showMessage(f'Nowy poligon: {len(self.current_polygon)} wierzchołków; prawy przycisk kończy.')

    def finish_polygon(self):
        self.view.draw_mode=False
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        if not self.doc or len(self.current_polygon)<3:
            self.current_polygon=[];return
        label,ok=QInputDialog.getText(self,'Nowy poligon','Numer / opis (A2):')
        if not ok:self.current_polygon=[];return
        try:
            uid=self.doc.append_polygon(self.current_polygon,self.polygon_code,label)
            self.rebuild_scene()
            if uid in self.graphics_for_uid:self.graphics_for_uid[uid].setSelected(True)
            self.status.showMessage('Dodano poligon (tryb eksperymentalny). Zapisz jako nowy plik.')
        except Exception as exc:QMessageBox.warning(self,'Błąd rysowania',str(exc))
        self.current_polygon=[]

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
