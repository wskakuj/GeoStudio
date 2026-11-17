import pytest

from geostudio.geomap import GeoMap, GeoObject, GeoPoint
from geostudio.interactions import closest_point_on_edge, find_snap, polygon_is_valid


def obj(code, uid, coords):
    return GeoObject(code=code, style='0', start=0, end=0, uid=uid,
                     points=[GeoPoint(x, y) for x, y in coords])


def test_nearest_vertex_over_segment_and_survey_point():
    boundary = obj('5216','parcel',[(0,0),(10,0),(10,10),(0,0)])
    marker = obj('1246','marker',[(5,1)])
    hit = find_snap(5.1, 0.8, [boundary,marker], radius=1.5)
    assert hit.kind == 'vertex'
    assert (hit.x, hit.y) == (5,1)
    assert hit.code == '1246'
    assert hit.uid == 'marker'


def test_snap_to_nearest_edge_projection():
    boundary = obj('5216','parcel',[(0,0),(10,0),(10,10),(0,0)])
    hit = find_snap(5,0.7,[boundary],radius=2)
    assert hit.kind == 'edge'
    assert (hit.x,hit.y)==pytest.approx((5,0))
    assert closest_point_on_edge(20,2,0,0,10,0)==(10,0)


def test_snap_outside_radius_and_exclude_current_polygon():
    boundary = obj('5216','parcel',[(0,0),(10,0),(10,10),(0,0)])
    assert find_snap(5,3,[boundary],radius=0.1) is None
    assert find_snap(5,0,[boundary],radius=2,exclude_uid='parcel') is None


def test_validate_polygon():
    assert polygon_is_valid([(0,0),(10,0),(0,10)])
    assert not polygon_is_valid([(0,0),(1,1),(2,2)])
    assert not polygon_is_valid([(0,0),(0,0),(1,1)])
    assert not polygon_is_valid([(0,0),(10,0),(float('nan'),2)])


def test_move_vertex_preserves_fields_labels_and_checksum():
    from test_geomap import fixture_map
    doc = GeoMap(fixture_map())
    # The first/last ring coordinate must be replaced together.
    doc.move_polygon_vertex('DEMO-01',0,0.2,0.2)
    encoded = doc.to_bytes()
    assert b':UNKNOWN[retain this]' in encoded
    again = GeoMap(encoded)
    assert again.checksum_valid
    assert again.objects[0].is_closed
    assert again.objects[0].points[0].x == 0.2
    assert again.objects[0].points[-1].x == 0.2
    assert again.objects[0].fields['A2']=='TEST'
    with pytest.raises(ValueError):
        again.move_polygon_vertex('DEMO-01',1,0.2,0.2)


def test_move_middle_vertex_preserves_label_and_line_count():
    from test_geomap import fixture_map
    raw = fixture_map().replace(b'1.000   1.000\r\n',b'1.000   1.000 ,P-123\r\n')
    # In actual samples a point can carry an identifier after the comma.
    doc = GeoMap(raw)
    n = len(doc.lines)
    doc.move_polygon_vertex('DEMO-01',2,1.5,1.5)
    assert len(doc.lines) == n
    assert doc.by_id['DEMO-01'].points[2].label=='P-123'
    assert b'1.500   1.500 ,P-123' in doc.to_bytes()
