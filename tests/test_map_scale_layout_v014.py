"""v0.14 tests: map-unit lettering, decluttered GEO-MAP sheet, Ctrl+F5."""
from __future__ import annotations
import os
os.environ.setdefault("QT_QPA_PLATFORM","offscreen")
import pytest
from geostudio.map_layout import (detect_source_compilation_scale,
    validated_compilation_scale, source_text_height, label_ratio,
    text_line_offset)
from geostudio.geomap import GeoMap, GeoObject
from test_geomap import fixture_map

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt


def make_layout_object(code, a1, tx, x, y, uid):
    from geostudio.geomap import GeoPoint
    return GeoObject(code=code,style="0 51 0",start=0,end=0,uid=uid,
        fields={"A1":str(a1),"TX":tx},
        points=[GeoPoint(x,y-200),GeoPoint(x,y+200)])


def test_compilation_scale_recognizes_real_legend_text_without_coordinate_guessing():
    objs=[make_layout_object("7900",15,"SKALA 1:5000||WYKAZ ZNAKÓW I KOLORÓW",
                             100,500,"LEG")]
    assert detect_source_compilation_scale(objs)==5000
    objs[0].fields["TX"]="SKALA 1:1000"
    assert detect_source_compilation_scale(objs)==1000
    objs[0].fields["TX"]="MAPA GOSPODARCZA LASU"
    assert detect_source_compilation_scale(objs)==5000
    assert validated_compilation_scale("2500")==2500
    assert validated_compilation_scale("-50") is None
    assert validated_compilation_scale("50000000") is None


def test_A1_is_nominal_world_height_not_2_1x_multiplied():
    assert source_text_height({"A1":"30.0"})==30
    assert source_text_height({"A1":"15"})==15
    assert source_text_height({"A1":"0"})==12
    assert label_ratio("7900",{"A1":"30"},32,5000,5000)*32==pytest.approx(30)
    assert label_ratio("6301",{"A1":"8"},30,5000,5000)*30==pytest.approx(8)
    assert label_ratio("7900",{"A1":"30"},32,10000,5000)*32==pytest.approx(60)
    assert text_line_offset(0,2,30)==-text_line_offset(1,2,30)


@pytest.fixture
def layout_window():
    from geostudio.app import GeoStudioWindow
    app=QApplication.instance() or QApplication([])
    w=GeoStudioWindow()
    w.show()
    w.doc=GeoMap(fixture_map())
    yield w
    w.close()


def append_object(doc,code,uid,a1,tx,x,y):
    rows=[f"*{code} 0 51 0",f":ID[{uid}]",f":A1[{a1}]",
          f":TX[{tx}]",f"P 1   {x:.3f}   {y-200:.3f}",
          f"P 1   {x:.3f}   {y+200:.3f}"]
    doc.lines.extend([(row+"\r\n").encode("cp1250") for row in rows])
    doc._parse()


def bounding_on_screen(view,item):
    return item.deviceTransform(view.viewportTransform()).mapRect(
        item.boundingRect())


def test_title_and_agency_rows_respect_source_geographic_spacing(layout_window):
    """Earlier v0.13 used 2.1*A1 and overprinted independently anchored rows."""
    w=layout_window
    append_object(w.doc,"7900","TITLE",30,
                  "MAPA GOSPODARCZA LASU||wsi MOKRA WIES",515300.,668430.)
    append_object(w.doc,"7900","ADMIN",24,
                  "gm. TŁUSZCZ pow. WOŁOMIŃSKI||woj. MAZOWIECKIE",
                  515220.,668430.)
    append_object(w.doc,"7900","PERIOD",24,
                  "NA OKRES 2027 - 2036",515180.,668430.)
    append_object(w.doc,"7900","DATE",18,"STAN NA: 30.06.2026 r.",
                  515140.,668430.)
    append_object(w.doc,"7900","AGENCY",15,"AGENCJA CEZAR",
                  514700.,668930.)
    append_object(w.doc,"7900","WORKSHOP",15,
                  "PRACOWNIA URZĄDZANIA LASU||05-300 MIŃSK",
                  514650.,668930.)
    w.source_compilation_scale=5000
    w.compilation_scale=5000
    w.rebuild_scene()
    labels=w.label_items
    for uid,height in (("TITLE",30),("ADMIN",24),("PERIOD",24),("DATE",18),
                        ("AGENCY",15),("WORKSHOP",15)):
        item=labels[(uid,"TX0")]
        assert item.boundingRect().height()*item.data(3)==pytest.approx(height)
    title_rects=[bounding_on_screen(w.view,labels[("TITLE","TX"+str(i))])
                 for i in range(2)]
    admin_rects=[bounding_on_screen(w.view,labels[("ADMIN","TX"+str(i))])
                 for i in range(2)]
    # Words on separate source rows must not collide.
    for a in title_rects:
        for b in admin_rects:
            assert not a.intersects(b)
    assert not bounding_on_screen(w.view,labels[("DATE","TX0")]).intersects(
        bounding_on_screen(w.view,labels[("PERIOD","TX0")]))
    assert not bounding_on_screen(w.view,labels[("AGENCY","TX0")]).intersects(
        bounding_on_screen(w.view,labels[("WORKSHOP","TX0")]))


def test_ctrl_f5_scale_changes_labels_not_zoom_or_geomap_data(layout_window,tmp_path):
    from PySide6.QtGui import QAction
    w=layout_window
    append_object(w.doc,"7900","TITLE",30,"MAPA GOSPODARCZA LASU",
                  515300.,668430.)
    w.doc.filename=str(tmp_path/"test.MAP")
    before=w.doc.to_bytes()
    w.source_compilation_scale=5000
    w.compilation_scale=5000
    w.rebuild_scene()
    item=w.label_items[("TITLE","TX0")]
    original_height=item.boundingRect().height()*item.data(3)
    zoom_before=w._view_pixel_scale()
    w.set_compilation_scale(10000)
    assert w._view_pixel_scale()==pytest.approx(zoom_before)
    assert item.boundingRect().height()*item.data(3)==pytest.approx(original_height*2)
    assert "Opracowanie 1:10000" in w.compilation_label.text()
    assert w.doc.to_bytes()==before
    key=w._compilation_scale_key(w.doc.filename)
    assert int(w.settings.value(key))==10000
    assert any(a.shortcut().toString().lower().replace(" ","")=="ctrl+f5"
               for a in w.findChildren(QAction))
    w.settings.remove(key)


def test_scale_display_and_compilation_scale_are_independent(layout_window):
    w=layout_window
    append_object(w.doc,"7900","TITLE",30,"SKALA 1:5000",515300.,668430.)
    w.source_compilation_scale=detect_source_compilation_scale(w.doc.objects)
    w.compilation_scale=w.source_compilation_scale
    w.rebuild_scene()
    item=w.label_items[("TITLE","TX0")]
    ratio=item.data(3)
    w.scale_combo.setCurrentText("1:2000")
    w.apply_view_scale()
    assert item.data(3)==pytest.approx(ratio)
    w.set_compilation_scale(2500)
    assert item.data(3)==pytest.approx(ratio*.5)
    assert w._display_denominator()==pytest.approx(2000,abs=2)
