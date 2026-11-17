"""Focused GEO-MAP v8 layout tests, no private map or vendor library bytes."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from geostudio.library_render import (parse_sym_primitives,
    parse_sym_line_patterns, object_sym_line_pattern)
from test_geomap import fixture_map


def add_record(doc, code, uid, fields, points, style="0  51 0.00000000"):
    rows=[f"*{code} {style}",f":ID[{uid}]"]
    rows.extend(f":{k}[{v}]" for k,v in fields.items())
    rows.extend(f"P 1   {x:.3f}   {y:.3f}" for x,y in points)
    doc.lines.extend([(row+"\r\n").encode("cp1250") for row in rows])
    doc._parse()


@pytest.fixture
def window():
    app=QApplication.instance() or QApplication([])
    w=GeoStudioWindow()
    w.show()
    w.doc=GeoMap(fixture_map())
    yield w
    w.close()


def test_map_sheet_text_from_source_is_not_drawn_as_long_line(window):
    # Two P coordinates describe a text baseline, not a map feature.
    add_record(window.doc,"7900","TITLE",
        {"A1":"30.0","TX":"MAPA GOSPODARCZA LASU||wsi MOKRA WIES"},
        [(515302.645,668203.682),(515302.645,668654.556)])
    add_record(window.doc,"7900","AGENCY",
        {"A1":"15.0","TX":"AGENCJA CEZAR"},
        [(514705.0,669018.0),(514705.0,669086.0)])
    add_record(window.doc,"6000","LEGEND",
        {"A1":"15.0","TX":"Sosna i Modrzew"},
        [(514882.9,668405.7),(514882.9,668459.8)])
    add_record(window.doc,"6301","ROW",
        {"A1":"8.0","TX":"HALIZNY"},
        [(514906.5,668100.0),(514906.5,668128.0)])
    window.rebuild_scene()
    assert window.label_items[("TITLE","TX0")].text()=="MAPA GOSPODARCZA LASU"
    assert window.label_items[("TITLE","TX1")].text()=="wsi MOKRA WIES"
    assert window.label_items[("AGENCY","TX0")].text()=="AGENCJA CEZAR"
    assert window.label_items[("LEGEND","TX0")].text()=="Sosna i Modrzew"
    assert window.label_items[("ROW","TX0")].text()=="HALIZNY"
    assert window.label_items[("TITLE","TX0")].font().bold()
    assert window.graphics_for_uid["TITLE"].pen().style()==Qt.NoPen
    assert window.graphics_for_uid["AGENCY"].pen().style()==Qt.NoPen
    title=window.label_items[("TITLE","TX0")]
    assert title.data(3) > window.label_items[("ROW","TX0")].data(3)


def test_code_6900_compass_labels_and_numbers_render_at_map_anchor(window):
    for name,tx in (("NORTH","N"),("EAST","E"),("BLOCK3","3")):
        add_record(window.doc,"6900",name,{"A1":"70","TX":tx},
            [(514070.0,669090.0),(514070.0,669100.0)])
    window.rebuild_scene()
    for name,txt in (("NORTH","N"),("EAST","E"),("BLOCK3","3")):
        item=window.label_items[(name,"TX0")]
        assert item.text()==txt
        assert item.isVisible()
        assert item.font().bold()
        assert window.graphics_for_uid[name].pen().style()==Qt.NoPen
        assert item.data(3)>1


def test_precinct_boundary_5214_uses_4010_sym_dash_and_is_visible(window,tmp_path):
    sym=tmp_path/"test.sym"
    sym.write_bytes(
        b"*4010 dash three\r\n 2 3.00 -2.00 0.00 0.00 0.00 0.00\r\n"
        b"*5214 precinct\r\n O 4010.00 0 0 0 0 0\r\n")
    assert parse_sym_line_patterns(sym)["4010"]==(3,2)
    assert object_sym_line_pattern(parse_sym_primitives(sym),
        parse_sym_line_patterns(sym),"5214")==(3,2)
    window.load_library(sym,"symbols")
    add_record(window.doc,"5214","PRECINCT",{"A2":"143411_5.0014","A3":"Mokra Wies"},
        [(513001.,670001.),(513100.,670100.),(513200.,670150.)],
        style="16711680 22 0")
    window.rebuild_scene()
    outline=window.graphics_for_uid["PRECINCT"]
    assert outline.pen().style()==Qt.CustomDashLine
    assert outline.zValue() >= 220
    assert window.label_items[("PRECINCT","A3")].text()=="Mokra Wies"


def test_compass_rose_quadrants_fill_black_from_existing_fa_flag(window):
    add_record(window.doc,"5200","COMPASS_DARK",{"FA":"0","TX":"SIEDLISKO LAS"},
               [(514100.,669100.),(514200.,669100.),
                (514150.,669150.),(514100.,669100.)],
               style="15 0 0")
    add_record(window.doc,"5200","COMPASS_LIGHT",{"FA":"-1","TX":"SIEDLISKO LAS"},
               [(514200.,669100.),(514300.,669100.),
                (514250.,669150.),(514200.,669100.)],
               style="15 0 0")
    window.rebuild_scene()
    dark=window.fill_items_for_uid["COMPASS_DARK"]
    light=window.fill_items_for_uid["COMPASS_LIGHT"]
    assert dark.brush().color().name()=="#111111"
    assert light.brush().style()==Qt.NoBrush
