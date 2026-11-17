"""Regression tests for GEO-MAP X/Y axis order, EPSG transformations, scale."""
from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

from geostudio.coordinates import (
    CRS_CHOICES, MODERN_EPSG, transform_xy, transform_map_copy,
    output_prj_text, transform_label_positions, detected_crs_from_prj,
)
from geostudio.geomap import GeoMap
from test_geomap import fixture_map


def test_epsg_codes_cover_pl1992_pl2000_and_historical_1965():
    codes = {code for _,code in CRS_CHOICES}
    assert set((2180,2176,2177,2178,2179,2171,2172,2173,2174,2175)) <= codes
    assert MODERN_EPSG == frozenset((2180,2176,2177,2178,2179))


def test_modern_transform_uses_geomap_x_north_y_east_order():
    # A point on the real map in PL-1992; pyproj expects the reverse order
    # easting,northing, while GEO-MAP expects X=northing,Y=easting.
    x,y=513102.968, 670076.708
    x2,y2=transform_xy(x,y,2180,2178)
    assert math.isfinite(x2) and math.isfinite(y2)
    assert 5_000_000 < x2 < 7_000_000  # northing PL-2000
    assert 7_000_000 < y2 < 8_000_000  # 2000/7 easting zone prefix
    back_x,back_y=transform_xy(x2,y2,2178,2180)
    assert back_x == pytest.approx(x,abs=.005)
    assert back_y == pytest.approx(y,abs=.005)


def test_converted_map_roundtrip_no_original_mutation():
    source=GeoMap(fixture_map())
    raw=source.to_bytes()
    output=transform_map_copy(source,2180,2178)
    assert source.to_bytes() == raw
    assert output.checksum_valid and output.declared_lines == len(output.lines)
    assert len(output.objects) == len(source.objects)
    assert output.objects[0].uid == source.objects[0].uid
    assert output.objects[0].fields == source.objects[0].fields
    assert len(output.objects[0].points)==len(source.objects[0].points)
    assert output.objects[0].points[0].x != source.objects[0].points[0].x
    assert output.declared_extent != source.declared_extent


def test_coordinate_converter_rejects_bad_source_or_unsupported_whole_map():
    doc=GeoMap(fixture_map())
    with pytest.raises(ValueError):
        transform_xy(5,6,99999,2178)
    with pytest.raises(ValueError):
        transform_xy(math.nan,0,2180,2178)
    with pytest.raises(ValueError):
        transform_map_copy(doc,2171,2178)
    with pytest.raises(ValueError):
        transform_map_copy(doc,2180,2180)
    broken=GeoMap(fixture_map())
    broken.lines[-1] = broken.lines[-1].replace(b'0',b'1',1)
    with pytest.raises(ValueError):
        transform_map_copy(broken,2180,2178)


def test_proj_sidecar_and_label_coordinates(tmp_path):
    from pyproj import CRS
    map_file=tmp_path/'test.MAP'
    map_file.write_bytes(fixture_map())
    prj=map_file.with_suffix('.prj')
    prj.write_text(output_prj_text(2178),encoding='utf-8')
    assert detected_crs_from_prj(map_file)==2178
    assert CRS.from_wkt(prj.read_text(encoding='utf-8')).to_epsg()==2178
    labels={'DEMO-01':{'A1':[513102.968,670076.708]}}
    converted=transform_label_positions(labels,2180,2178)
    assert converted['DEMO-01']['A1'] != labels['DEMO-01']['A1']
    assert labels['DEMO-01']['A1'] == [513102.968,670076.708]


@pytest.fixture
def gui_scale():
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    from geostudio.app import GeoStudioWindow
    app=QApplication.instance() or QApplication([])
    w=GeoStudioWindow()
    w.show()
    w.doc=GeoMap(fixture_map())
    w.rebuild_scene()
    app.processEvents()
    yield w
    w.close()


def test_exact_screen_scale_input_is_reversible(gui_scale):
    from math import hypot
    w=gui_scale
    w.scale_combo.setCurrentText('1:2500')
    w.apply_view_scale()
    assert w._display_denominator()==pytest.approx(2500,abs=2)
    assert w.scale_combo.currentText()=='1:2500'
    first=w._view_pixel_scale()
    w.scale_combo.setCurrentText('1:1000')
    w.apply_view_scale()
    second=w._view_pixel_scale()
    assert second/first==pytest.approx(2.5,rel=.005)
    assert w.doc.checksum_valid


def test_legacy_1965_point_transform_is_optional_and_warned():
    # Historical CRS may require local grids; no unvalidated whole-map
    # reprojection is permitted, even if pyproj knows a point operation.
    with pytest.raises(ValueError):
        transform_map_copy(GeoMap(fixture_map()),2174,2180)
