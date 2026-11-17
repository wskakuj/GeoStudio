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
    assert cdf_for_object(styles,'5216','12','RV').fill==(10,255,10)
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
    gui.begin_label_drag(pos.x(),-pos.y())
    assert gui._active_label is item
    gui.move_label(pos.x()+2,-pos.y()+1)
    gui.end_label_drag(pos.x()+2,-pos.y()+1)
    assert gui.label_positions[uid]['A1']==[round(pos.x()+2,3),round(-pos.y()+1,3)]
    assert 'A2' not in gui.label_positions[uid]
    assert gui._auto_copy_path is not None
    assert load_label_positions(gui._auto_copy_path)[uid]['A1']==gui.label_positions[uid]['A1']
    assert f.read_bytes()==fixture_map()
    gui.rebuild_scene(fit=False,reselect=uid)
    assert gui.label_items[(uid,'A1')].pos().x()==pytest.approx(pos.x()+2)
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
