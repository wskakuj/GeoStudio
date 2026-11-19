"""Stage 8: GEO-MAP GMW 10.52 multipart closure, performance and safety."""
from __future__ import annotations

from hashlib import md5
from time import perf_counter
from pathlib import Path
import os
import pytest

from geostudio.geomap import GeoMap
from geostudio.web_app.geometry_6a import geometry_of, rings_from_shape
from geostudio.web_app.data import PreviewWorkspace


def _map_bytes(lines):
    body=b"\r\n".join(lines)+b"\r\n"
    header=(
        b";# Plik danych systemu GEO-MAP ver=[ 8.00]  N=["+
        f"{len(lines)+1:12d}".encode()+
        b"] CHK=["+md5(body).hexdigest().encode()+b"]\r\n"
    )
    return header+body


def _multipart_with_or_without_gmw_closure(global_closure):
    """Small actual GMW-style 5310 record with two disjoint islands."""
    lines=[
        b"*5310 255  24    5871579",
        b":ID[B705AB37-F1B5-4350-A2C5-A225BA840C21]",
        b":A1[l]",
        b":A2[So120|II-0.3]",
        b":MP[0]",
        b":FA[5871579]",
        b"L 2 5.647 -1.042 0.0000000 1.0000000 21",
        b"L 3 -15.107 -1.042 0.0015708 1.0000000 21",
        b"L 1 0.000 0.000 0.0015708 1.0000000 21",
        b"P 1   512885.290   669202.050",
        b"P 1   512883.590   669223.700",
        b"P 1   512873.880   669200.590",
        b"P 0   512885.290   669202.050",
        b"P 1   512897.853   669176.864",
        b"P 1   512899.233   669152.574",
        b"P 1   512908.453   669178.224",
        b"P 1   512897.853   669176.864",
    ]
    if global_closure:
        lines.append(b"P 1   512885.290   669202.050")
    return _map_bytes(lines)


def test_gmw_multipart_global_closure_is_not_an_extra_polygon_edge():
    original=GeoMap(_multipart_with_or_without_gmw_closure(False))
    corrected=GeoMap(_multipart_with_or_without_gmw_closure(True))
    uid="B705AB37-F1B5-4350-A2C5-A225BA840C21"
    assert corrected.checksum_valid
    assert corrected.declared_lines==len(corrected.lines)
    assert original.by_id[uid].is_closed and corrected.by_id[uid].is_closed
    assert len(original.by_id[uid].display_parts)==2
    assert len(corrected.by_id[uid].display_parts)==2
    shape_a=geometry_of(original.by_id[uid])
    shape_b=geometry_of(corrected.by_id[uid])
    assert shape_a.equals(shape_b)
    assert corrected.by_id[uid].area_m2==pytest.approx(original.by_id[uid].area_m2)


def test_every_native_multipart_export_ends_with_first_global_vertex():
    uid="B705AB37-F1B5-4350-A2C5-A225BA840C21"
    doc=GeoMap(_multipart_with_or_without_gmw_closure(False))
    geom=geometry_of(doc.by_id[uid])
    rings=rings_from_shape(geom,
        prefer_anchor=(512885.290,669202.050))
    doc.replace_polygon_components(uid,rings)
    out=GeoMap(doc.to_bytes())
    assert out.checksum_valid and out.declared_lines==len(out.lines)
    o=out.by_id[uid]
    assert o.points[-1].point_type==1
    assert (o.points[0].x,o.points[0].y)==(o.points[-1].x,o.points[-1].y)
    assert (o.points[-2].x,o.points[-2].y)!=(
        o.points[-1].x,o.points[-1].y)
    assert len(o.display_parts)==2
    assert geometry_of(o).equals_exact(geom,0.001)==False or (
        geom.symmetric_difference(geometry_of(o)).area<.002)
    assert geom.symmetric_difference(geometry_of(o)).area<.002
    assert b"L 2 5.647 -1.042" in out.to_bytes()
    assert b":A2[So120|II-0.3]" in out.to_bytes()


def test_true_hole_has_gmw_global_closure_and_preserves_area():
    uid="B705AB37-F1B5-4350-A2C5-A225BA840C21"
    doc=GeoMap(_multipart_with_or_without_gmw_closure(False))
    shell=[(0,0),(0,40),(40,40),(40,0),(0,0)]
    hole=[(10,10),(10,20),(20,20),(20,10),(10,10)]
    doc.replace_polygon_components(uid,[shell,hole])
    result=GeoMap(doc.to_bytes())
    obj=result.by_id[uid]
    assert obj.is_closed and len(obj.display_parts)==2
    assert (obj.points[0].x,obj.points[0].y)==(
        obj.points[-1].x,obj.points[-1].y)
    assert geometry_of(obj).area==pytest.approx(1500.)
    assert result.checksum_valid


def test_unmodified_map_is_byte_exact_after_parsing_gmw_closure():
    original=_multipart_with_or_without_gmw_closure(True)
    doc=GeoMap(original)
    assert doc.to_bytes()==original
    assert doc.checksum_valid


def test_100k_line_map_roundtrip_with_valid_checksum_is_bounded():
    # Regression on large maps without committing user source files.
    # The benchmark cap is intentionally generous for slow CI hardware.
    lines=[]
    for i in range(16000):
        x=510000+i*.001
        y=670000+i*.001
        lines.extend([
            b"*5216 8553090  15          0",
            (":ID[PERF-%05d]"%i).encode(),
            ("P 1   %.3f   %.3f"%(x,y)).encode(),
            ("P 1   %.3f   %.3f"%(x,y+1)).encode(),
            ("P 1   %.3f   %.3f"%(x+1,y+1)).encode(),
            ("P 1   %.3f   %.3f"%(x+1,y)).encode(),
            ("P 1   %.3f   %.3f"%(x,y)).encode(),
        ])
    source=_map_bytes(lines)
    start=perf_counter()
    doc=GeoMap(source)
    assert len(doc.objects)==16000
    assert doc.checksum_valid
    assert doc.to_bytes()==source
    assert perf_counter()-start<45
