"""Independent of PySide6: selected features follow map geometry, not Qt shapes."""
from geostudio.geomap import GeoObject, GeoPoint
from geostudio.geometry_index import GeometryIndex, boundary_distance, point_in_ring


def obj(code, uid, coords, fields=None):
    return GeoObject(code=code, style='0', start=0, end=0, uid=uid,
                     fields=fields or {},
                     points=[GeoPoint(x,y) for x,y in coords])


def test_select_parcel_when_landuse_polygon_covers_it():
    parcel = obj('5216','parcel',[(0,0),(20,0),(20,10),(0,10),(0,0)],{'A2':'123/4'})
    landuse = obj('5230','landuse',[(0,0),(20,0),(20,10),(0,10),(0,0)],{'A2':'R'})
    idx = GeometryIndex([landuse, parcel])
    hits = idx.pick(10, 5, 0.1)
    assert [h.obj.uid for h in hits] == ['parcel', 'landuse']
    assert all(h.hit_kind == 'inside' for h in hits)
    assert [h.obj.uid for h in idx.pick(10, 5, 0.1, code_filter='5230')] == ['landuse']


def test_select_boundary_when_polygon_is_open():
    outline = obj('5216','parcel',[(0,0),(10,0),(10,10)])
    idx = GeometryIndex([outline])
    assert idx.pick(5, 0.3, 0.4)[0].obj.uid=='parcel'
    assert not idx.pick(5, 2, 0.4)


def test_select_polygon_interior_far_from_edges():
    polygon = obj('5216','parcel',[(0,0),(80,0),(80,80),(0,80),(0,0)])
    idx = GeometryIndex([polygon])
    assert idx.pick(40,40,0.0001)[0].obj.uid=='parcel'
    assert not idx.pick(120,120,0.5)


def test_visibility_and_code_filter():
    a=obj('5216','parcel',[(0,0),(10,0),(10,10),(0,10),(0,0)])
    b=obj('5230','landuse',[(0,0),(10,0),(10,10),(0,10),(0,0)])
    idx=GeometryIndex([a,b])
    assert [h.obj.uid for h in idx.pick(3,3,1,visible={'landuse'})] == ['landuse']
    assert idx.pick(3,3,1,visible=set())==[]
    assert idx.pick(3,3,1,code_filter='5310')==[]


def test_point_inside_concave_polygon():
    p=[(0,0),(10,0),(10,10),(5,5),(0,10)]
    assert point_in_ring(7,2,p)
    assert not point_in_ring(5,8,p)
    assert boundary_distance(5,0,p)==0


def test_large_polygon_still_indexed():
    large=obj('5216','big',[(0,0),(10000,0),(10000,10000),(0,10000),(0,0)])
    tiny=obj('5230','tiny',[(9,9),(11,9),(11,11),(9,11),(9,9)])
    idx=GeometryIndex([tiny,large])
    assert [h.obj.uid for h in idx.pick(10,10,.1)] == ['big','tiny']
