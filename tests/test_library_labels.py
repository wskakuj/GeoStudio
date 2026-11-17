"""v0.8 regressions: library parsers, remembered files, labels, Qt fills."""
from __future__ import annotations

import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

import pytest

from geostudio.library_render import (
    parse_cdf, parse_sym_primitives, native_fill_color, cdf_for_object,
    simple_point_segments,
)
from geostudio.visual_styles import load_label_positions, load_styles, write_styles


def test_cdf_rgb_hatch_border_and_exact_variant(tmp_path):
    f=tmp_path/'custom.CDF'
    f.write_bytes(
        b'; ID RGB S RGB W\r\n'
        b'5310.bx 220 33 44 0 120 20 20 1.8 test\r\n'
        b'5216.?.RV 10 255 10 4 0 20 0 0.25 test\r\n'
        b'BROKEN 12 99\r\n')
    styles=parse_cdf(f)
    s=cdf_for_object(styles,'5310','bx','')
    assert s.fill==(220,33,44) and s.border==(120,20,20)
    assert s.hatch==0 and s.width==pytest.approx(1.8)
    assert cdf_for_object(styles,'5216','1','RV').fill==(10,255,10)
    assert cdf_for_object(styles,'5230','', 'RV') is None


def test_sym_simple_segments_and_native_map_fill(tmp_path):
    f=tmp_path/'vendor.SYM'
    f.write_bytes(
        b'*1246 punkt\r\n L 0.00 0.00 1.00 0.00 0.00 0.00\r\n'
        b' V 0.00 0.00 0.00 1.00 1.00 0.00\r\n'
        b'*5310 budynek\r\n O 4001.00 0 0 0 0 0\r\n'
        b' T 0 0 10 6301.01 0 1.10\r\n')
    sym=parse_sym_primitives(f)
    assert len(sym['1246'])==2
    assert simple_point_segments(sym['1246']) == [(0,0,1,0)]
    assert [primitive.kind for primitive in sym['5310']] == ['O','T']
    assert native_fill_color('255 24 8499682')==(226,177,129)
    assert native_fill_color('8553090 15 0') is None


def test_label_positions_are_saved_separately_from_map(tmp_path):
    f=tmp_path/'real.MAP'
    f.write_bytes(b'original-do-not-edit')
    write_styles(f, {'A':{'fill':'#AA0000','opacity':30}},
                 label_positions={'A':{'A1':[512333.123,671233.456],
                                       'A2':[512335.555,671235.789]}})
    assert load_label_positions(f)['A']['A1']==[512333.123,671233.456]
    assert load_styles(f)['A']['fill']=='#AA0000'
    assert f.read_bytes()==b'original-do-not-edit'


@pytest.fixture
def gui():
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    from geostudio.app import GeoStudioWindow
    app=QApplication.instance() or QApplication([])
    w=GeoStudioWindow()
    w.show()
    app.processEvents()
    yield w
    w.close()


def test_labels_A1_A2_independent_and_preserved_on_layer_toggle(gui, tmp_path):
    from geostudio.geomap import GeoMap
    from test_geomap import fixture_map
    f=tmp_path/'test.MAP'
    f.write_bytes(fixture_map())
    gui.doc=GeoMap.open(f)
    uid=gui.doc.append_polygon([(5,5),(10,5),(5,10)],'5310',
        fields={'A1':'bx','A2':'test'})
    gui.rebuild_scene()
    gui._select_uid(uid)
    assert (uid,'A1') in gui.label_items
    assert (uid,'A2') in gui.label_items
    assert gui.label_items[(uid,'A1')].isVisible()
    assert gui.label_items[(uid,'A2')].isVisible()
    gui.start_label_edit()
    item=gui.label_items[(uid,'A1')]
    pos=item.pos()
    # Hit the rendered A1 glyph, not the shared A1/A2 geographic anchor.
    centre=item.deviceTransform(gui.view.viewportTransform()).mapRect(
        item.boundingRect()).center().toPoint()
    scene=gui.view.mapToScene(centre)
    gui.begin_label_drag(scene.x(),-scene.y())
    assert gui._active_label is item
    gui.move_label(pos.x()+2,-pos.y()+1)
    gui.end_label_drag(pos.x()+2,-pos.y()+1)
    assert gui.label_positions[uid]['A1']==[round(pos.x()+2,3),round(-pos.y()+1,3)]
    assert 'A2' not in gui.label_positions[uid]
    assert gui._auto_copy_path is not None
    assert load_label_positions(gui._auto_copy_path)[uid]['A1']==gui.label_positions[uid]['A1']
    assert f.read_bytes()==fixture_map()
    gui.rebuild_scene(fit=False,reselect=uid)
    assert gui.label_items[(uid,'A1')].pos().x()==pytest.approx(pos.x()+2, abs=.001)
    assert gui.label_items[(uid,'A2')].pos().x()!=pytest.approx(pos.x()+2)


def test_library_files_auto_load_from_settings(gui, tmp_path):
    from geostudio.app import GeoStudioWindow
    sym=tmp_path/'GEO-MAP.sym'
    lay=tmp_path/'GEO-MAP.lay'
    cdf=tmp_path/'GEO-MAP.CDF'
    sym.write_bytes(b'*5310 test\r\n L 0 0 1 1 0 0\r\n')
    lay.write_bytes(b'* 255 2.002 "Budynki"\r\n 5310 255 2.002 1 standard 2.5 15 0.0\r\n')
    cdf.write_bytes(b'5310 200 120 40 0 0 0 0 1.0\r\n')
    gui.load_library(sym,'symbols')
    gui.load_library(lay,'layers')
    gui.load_library(cdf,'palette')
    window=GeoStudioWindow()
    try:
        assert window.symbols['5310']=='test'
        assert window.catalog['5310']=='Budynki'
        assert window.cdf_styles['5310'].fill==(200,120,40)
    finally:
        window.close()
        for kind in ('symbols','layers','palette'):
            gui.settings.remove('library_'+kind)



def test_native_polygon_fill_and_cdf_palette(gui, tmp_path):
    from geostudio.geomap import GeoMap
    from test_geomap import fixture_map
    gui.doc = GeoMap(fixture_map())
    parcel = gui.doc.by_id['DEMO-01']
    parcel.style = '255 24 8499682'
    gui.rebuild_scene()
    item = gui.fill_items_for_uid['DEMO-01']
    assert item.brush().color().getRgb()[:3] == (226,177,129)
    assert item.brush().color().alpha() == 255

    # A CDF rule is used if no explicit source fill is recorded.
    parcel.style = '8553090 15 0'
    cdf=tmp_path/'map.CDF'
    cdf.write_bytes(b'5216 10 200 100 0 10 20 30 1.0 test\r\n')
    gui.load_library(cdf,'palette')
    gui.rebuild_scene()
    item = gui.fill_items_for_uid['DEMO-01']
    assert item.brush().color().getRgb()[:3] == (10,200,100)
    assert gui.graphics_for_uid['DEMO-01'].pen().color().getRgb()[:3] == (10,20,30)


def test_label_layer_toggle_visibility_is_reversible(gui):
    from geostudio.geomap import GeoMap
    from test_geomap import fixture_map
    from PySide6.QtCore import Qt
    gui.doc=GeoMap(fixture_map())
    uid=gui.doc.append_polygon([(5,5),(10,5),(5,10)],'5310',
                               fields={'A1':'bx','A2':'test'})
    gui.rebuild_scene()
    gui._select_uid(uid)
    layer=gui.layer_for_uid[uid]
    nodes=[gui.layers_tree.topLevelItem(i)
           for i in range(gui.layers_tree.topLevelItemCount())]
    node=next(n for n in nodes if n.text(0)==layer)
    node.setCheckState(0,Qt.Unchecked)
    assert not gui.label_items[(uid,'A1')].isVisible()
    assert not gui.label_items[(uid,'A2')].isVisible()
    node.setCheckState(0,Qt.Checked)
    gui._select_uid(uid)
    assert gui.label_items[(uid,'A1')].isVisible()
    assert gui.label_items[(uid,'A2')].isVisible()


def test_real_mouse_drag_moves_A2_not_A1(gui, tmp_path):
    from geostudio.geomap import GeoMap
    from test_geomap import fixture_map
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt, QPoint
    f=tmp_path/'mapa.MAP'
    f.write_bytes(fixture_map())
    gui.doc=GeoMap.open(f)
    uid=gui.doc.append_polygon([(5,5),(10,5),(5,10)],'5310',
        fields={'A1':'a', 'A2':'b'})
    gui.rebuild_scene()
    gui._select_uid(uid)
    gui.start_label_edit()
    item=gui.label_items[(uid,'A2')]
    click=item.deviceTransform(gui.view.viewportTransform()).mapRect(
        item.boundingRect()).center().toPoint()
    QTest.mousePress(gui.view.viewport(),Qt.LeftButton,pos=click)
    assert gui._active_label is item
    new=click+QPoint(22,12)
    QTest.mouseMove(gui.view.viewport(),pos=new)
    QTest.mouseRelease(gui.view.viewport(),Qt.LeftButton,pos=new)
    assert 'A2' in gui.label_positions[uid]
    assert 'A1' not in gui.label_positions[uid]
    assert gui._auto_copy_path is not None
    assert load_label_positions(gui._auto_copy_path)[uid]['A2']==gui.label_positions[uid]['A2']


def test_map_label_font_scales_with_geometry_but_is_never_culled(gui):
    """GEO-MAP-like annotation is proportional to map zoom, not fixed pixels."""
    from geostudio.geomap import GeoMap
    from test_geomap import fixture_map
    from PySide6.QtWidgets import QGraphicsItem
    gui.doc=GeoMap(fixture_map())
    uid=gui.doc.append_polygon([(5,5),(10,5),(5,10)],'5310',
                               fields={'A1':'bx','A2':'a'})
    gui.rebuild_scene()
    item=gui.label_items[(uid,'A1')]
    assert item.font().pixelSize()==16
    assert not (item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
    width=lambda: item.deviceTransform(gui.view.viewportTransform()).mapRect(
        item.boundingRect()).width()
    w0=width()
    gui.view.scale(3.0,3.0)
    gui.update_label_visibility()
    w1=width()
    gui.view.scale(.11,.11)
    gui.update_label_visibility()
    w2=width()
    assert w1 == pytest.approx(w0*3, abs=0.15)
    assert w2 == pytest.approx(w0*.33, abs=0.15)
    gui.update_label_visibility()
    assert item.isVisible()
    assert gui.label_items[(uid,'A2')].font().pixelSize()==16


def test_geo_map_text_palette_and_pen_width(gui, tmp_path):
    from geostudio.geomap import GeoMap
    from test_geomap import fixture_map
    gui.doc=GeoMap(fixture_map())
    uid1=gui.doc.append_polygon([(5,5),(10,5),(5,10)],'5310',
                                fields={'A1':'bx','A2':'bud'})
    uid2=gui.doc.append_polygon([(15,15),(18,15),(15,18)],'5230',
                                fields={'A2':'RV'})
    f=tmp_path/'col.CDF'
    f.write_bytes(b'5230.RV 20 150 90 3 0 130 0 2.25\r\n')
    gui.load_library(f,'palette')
    gui.rebuild_scene()
    assert gui.label_items[(uid1,'A1')].brush().color().red() > 170
    assert gui.label_items[(uid2,'A2')].brush().color().green() > (
        gui.label_items[(uid2,'A2')].brush().color().red())
    poly=gui.graphics_for_uid[uid2]
    assert poly.pen().widthF() == pytest.approx(2.25)
    assert gui.fill_items_for_uid[uid2].brush().color().getRgb()[:3] == (20,150,90)


def test_parcel_lines_are_above_filled_forest_polygons(gui):
    """Regression from MOKRA WIEŚ screenshots: fills obscured subdivisions."""
    from geostudio.geomap import GeoMap
    from test_geomap import fixture_map
    from PySide6.QtCore import Qt
    gui.doc=GeoMap(fixture_map())
    uid=gui.doc.append_polygon(
        [(0,0),(2,0),(2,2),(0,2)],'5310',
        fields={'A1':'a','A2':'So80'})
    gui.doc.by_id[uid].style = '255 24 15461219'  # opaque cyan test colour
    gui.rebuild_scene()
    parcel=gui.graphics_for_uid['DEMO-01']
    forest=gui.graphics_for_uid[uid]
    fill=gui.fill_items_for_uid[uid]
    assert fill.brush().color().alpha() == 255
    assert fill.zValue() < parcel.zValue()
    assert fill.zValue() < forest.zValue()
    assert parcel.zValue() > forest.zValue()
    assert forest.brush().style() == Qt.NoBrush
    assert parcel.brush().style() == Qt.NoBrush
    assert fill in gui.items_by_layer[gui.layer_for_uid[uid]]
    gui.layers_tree.blockSignals(True)
    gui.layers_tree.clear()
    gui.layers_tree.blockSignals(False)


def test_lay_pen_and_sym_granicznik_arcs(tmp_path):
    from geostudio.library_render import (
        parse_lay_pen_styles, lay_for_code, parse_sym_primitives,
        simple_point_circles)
    lay=tmp_path/'x.lay'
    lay.write_bytes(
        b'* 0 2.002 "Dzialki"\r\n'
        b' 5216 8553090 23.023 1 standard 2.0 15 0\r\n'
        b' 5220 32768 2.008 1 standard 2.5 15 0\r\n')
    styles=parse_lay_pen_styles(lay)
    assert lay_for_code(styles,'5216').line_id=='23.023'
    assert lay_for_code(styles,'5220').line_id=='2.008'
    sym=tmp_path/'x.sym'
    sym.write_bytes(
        b'*1246 granicznik\r\n'
        b' A 0 0 0.50 0 0 360\r\n'
        b' A 0 0 0.05 0 0 360\r\n'
        b' T 2 3 1 6246.01 0 0\r\n')
    assert simple_point_circles(parse_sym_primitives(sym)['1246']) == [
        (0.0,0.0,0.5),(0.0,0.0,0.05)]


def test_sym_400x_line_styles_follow_object_macro_references(tmp_path):
    from geostudio.library_render import (
        parse_sym_primitives, parse_sym_line_patterns, object_sym_line_pattern)
    f=tmp_path/'symbols.sym'
    f.write_bytes(
        b'*4001 solid\r\n 1 1.00 0.00 0 0 0 0\r\n'
        b'*4002 1,-1\r\n 2 1.00 -1.00 0 0 0 0\r\n'
        b'*4003 2,-1\r\n 2 2.00 -1.00 0 0 0 0\r\n'
        b'*4216 granica dzialki\r\n L 4001.00 0 0 0.5 0 0\r\n'
        b'*5216 dzialka\r\n O 4216.00 0 0 0 0 0\r\n'
        b'*5220 kontur\r\n O 4003.00 0 0 0 0 0\r\n'
        b'*5230 uzytek\r\n O 4002.00 0 0 0 0 0\r\n')
    primitives=parse_sym_primitives(f)
    patterns=parse_sym_line_patterns(f)
    assert patterns['4003']==(2,1)
    assert object_sym_line_pattern(primitives,patterns,'5216')==()
    assert object_sym_line_pattern(primitives,patterns,'5220')==(2,1)
    assert object_sym_line_pattern(primitives,patterns,'5230')==(1,1)


def test_contour_pen_dashes_come_from_sym(gui, tmp_path):
    from geostudio.geomap import GeoMap
    from test_geomap import fixture_map
    from PySide6.QtCore import Qt
    gui.doc=GeoMap(fixture_map())
    uid=gui.doc.append_polygon([(4,4),(6,4),(5,7)],'5220',
                                fields={'A2':'RV'})
    lib=tmp_path/'sample.sym'
    lib.write_bytes(
        b'*4003 dashed\r\n 2 2.00 -1.00 0 0 0 0\r\n'
        b'*5220 kontur klasyfikacyjny\r\n O 4003 0 0 0 0 0\r\n')
    gui.load_library(lib,'symbols')
    gui.rebuild_scene()
    item=gui.graphics_for_uid[uid]
    assert item.pen().style()==Qt.CustomDashLine
    assert item.pen().dashPattern()==pytest.approx([6.0,3.0])
