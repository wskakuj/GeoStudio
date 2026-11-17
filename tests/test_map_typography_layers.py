"""Regression checks for GEO-MAP-like fixed text and separate polygon rendering."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

import pytest
pytest.importorskip('PySide6')

from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsPathItem

from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from geostudio.label_render import map_label_style, display_label_text
from geostudio.library_render import SymbolPrimitive, simple_point_commands
from test_geomap import fixture_map


@pytest.fixture
def window():
    app=QApplication.instance() or QApplication([])
    w=GeoStudioWindow()
    w.show()
    w.doc=GeoMap(fixture_map())
    uid=w.doc.append_polygon([(5,5),(11,5),(11,11)],
        '5310', fields={'A1':'b','A2':'8So10|I-0.9'})
    w.rebuild_scene()
    app.processEvents()
    yield w,uid
    w.close()


def test_typography_is_fixed_screen_pixels_at_any_zoom(window):
    w,uid=window
    a1=w.label_items[(uid,'A1')]
    a2=w.label_items[(uid,'A2')]
    assert a1.font().pixelSize()==14
    assert a2.font().pixelSize()==13
    assert a1.flags() & QGraphicsItem.ItemIgnoresTransformations
    assert a2.flags() & QGraphicsItem.ItemIgnoresTransformations
    assert a1.font().bold() and a2.font().bold()
    assert a1.brush().color().name().upper()=='#E41F29'
    assert '\n' in a2.text()
    for delta in (120,120,-120,-120,-120):
        event=QWheelEvent(QPointF(250,210),QPointF(250,210),
            QPoint(),QPoint(0,delta),Qt.NoButton,Qt.NoModifier,
            Qt.NoScrollPhase,False)
        w.view.wheelEvent(event)
        assert a1.font().pixelSize()==14
        assert a2.font().pixelSize()==13


def test_overview_does_not_change_font_or_arbitrarily_hide_only_label(window):
    w,uid=window
    w._select_uid(uid)
    a1=w.label_items[(uid,'A1')]
    a2=w.label_items[(uid,'A2')]
    w.view.scale(.02,.02)
    w.update_label_visibility()
    assert a1.isVisible() and a2.isVisible()
    assert (a1.font().pixelSize(),a2.font().pixelSize())==(14,13)


def test_label_colors_follow_geomap_object_roles():
    assert map_label_style('5310','A1').bold
    assert map_label_style('5216','A2').color=='#626B70'
    assert map_label_style('5220','A2').color=='#378349'
    assert map_label_style('5230','A2').pixel_size==10
    assert display_label_text('5310','A2','8So10|I-0.9')=='8So10\nI-0.9'
    assert display_label_text('5216','A2','29/16')=='29/16'


def test_colored_fills_do_not_cover_boundary_strokes(window):
    w,uid=window
    main=w.graphics_for_uid[uid]
    assert isinstance(main,QGraphicsPathItem)
    assert main.zValue() < 0
    assert main.brush().style()!=Qt.NoBrush
    # Foreground stroke is a distinct path item in the same user layer.
    layer=w.layer_for_uid[uid]
    over=[it for it in w.items_by_layer[layer] if (
        isinstance(it,QGraphicsPathItem) and it is not main
        and it.zValue()>=50 and it.path()==main.path())]
    assert over
    assert over[0].pen().color().name().upper()=='#FF0000'


def test_hiding_layer_hides_fills_and_foreground_strokes(window):
    w,uid=window
    layer=w.layer_for_uid[uid]
    nodes=[w.layers_tree.topLevelItem(i)
           for i in range(w.layers_tree.topLevelItemCount())]
    node=next(n for n in nodes if n.text(0)==layer)
    members=list(w.items_by_layer[layer])
    node.setCheckState(0,Qt.Unchecked)
    assert not any(it.isVisible() for it in members)
    node.setCheckState(0,Qt.Checked)
    assert all(it.isVisible() or it in w.labels for it in members)


def test_safe_simple_sym_vectors_and_complete_circles():
    primitive=[
        SymbolPrimitive('L',(0,0,1,0,0,0)),
        SymbolPrimitive('V',(1,1,0,0,1,0)),
        SymbolPrimitive('A',(0,0,.25,0,0,360)),
        SymbolPrimitive('A',(0,0,3,0,0,110)),   # partial arc: unsupported
        SymbolPrimitive('O',(1001,0,0,0,0,0)),  # nested: unsupported
    ]
    commands=simple_point_commands(primitive)
    assert [cmd.kind for cmd in commands]==['line','line','ellipse']
    assert commands[-1].values==(0,0,.25,.25)


def test_renderer_does_not_mutate_source_map_bytes(window):
    w,_=window
    current=w.doc.to_bytes()
    w.rebuild_scene()
    assert w.doc.to_bytes()==current
