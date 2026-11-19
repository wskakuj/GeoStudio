"""Stage 6A: reversible cutouts, GEO-MAP winding, split/merge and line tools."""
from __future__ import annotations

import json
import pytest
from shapely.geometry import Polygon

from conftest import MapBuilder
from geostudio.geomap import GeoMap
from geostudio.web_app.data import PreviewWorkspace


def source():
    return (MapBuilder(ext=(5000,0,0,100,100))
      .object("5310","A",{"A1":"b","A2":"Dom"},
              [(0,0),(0,10),(10,10),(10,0)])
      .object("5310","B",{"A1":"b","A2":"Dom"},
              [(20,0),(20,10),(30,10),(30,0)])
      .object("5220","C",{"A1":"LsV","A2":"Las"},
              [(0,0),(0,10),(10,10),(10,0)])
      .build())


@pytest.fixture
def ws():
    w=PreviewWorkspace()
    w.load_map(source(),"MOKRA WIEŚ.MAP")
    return w


def auth(w):
    s=w.editing_status()
    return {"document_token":s["documentToken"],"revision":s["revision"]}


def act(w,operation):
    plan=w.preview_geometry_operation(operation,**auth(w))
    assert plan["canApply"],plan
    return w.apply_geometry_operation(
        operation,preview_key=plan["previewKey"],**auth(w))


def move(w,ids,dx,dy):
    plan=w.preview_move_polygons(ids,dx,dy,allow_detach=False,
                                 snap_distance=0,**auth(w))
    assert plan["canApply"],plan
    return w.apply_move_polygons(ids,dx,dy,allow_detach=False,
                                  snap_distance=0,preview_key=plan["previewKey"],
                                  **auth(w))


def feature(w,fid):
    data=w.viewport((-1e3,-1e3,1e3,1e3))
    return next(f for f in data["features"] if f["id"]==fid)


def test_overlay_eats_area_then_restores_when_moved_away(ws):
    baseline=ws.export_copy(auth(ws)["document_token"])[1]
    assert feature(ws,"f0")["visibleAreaM2"]==100
    move(ws,["f1"],-15,0)
    a=feature(ws,"f0")
    b=feature(ws,"f1")
    forest=feature(ws,"f2")
    assert a["reversibleCutout"] and a["visibleAreaM2"]==50
    assert b["visibleAreaM2"]==100
    assert forest["visibleAreaM2"]==100
    after=GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    before=GeoMap(baseline)
    # The underlying A and a DIFFERENT code C keep every source byte.
    for uid in ("A","C"):
        original=before.by_id[uid]
        current=after.by_id[uid]
        assert before.lines[original.start:original.end]==after.lines[
            current.start:current.end]
    move(ws,["f1"],35,0)
    assert feature(ws,"f0")["visibleAreaM2"]==100
    ws.step_history("undo",**auth(ws))
    assert feature(ws,"f0")["visibleAreaM2"]==50
    ws.step_history("redo",**auth(ws))
    assert feature(ws,"f0")["visibleAreaM2"]==100


def test_cutout_order_survives_companion_and_is_bound_to_map(ws):
    move(ws,["f1"],-15,0)
    saved=ws.export_copy(auth(ws)["document_token"])[1]
    companion=ws.export_topology_metadata(saved)
    assert json.loads(companion)["format"]=="geostudio-topology-v1"
    restored=PreviewWorkspace()
    restored.load_map(saved,"restored.MAP")
    assert feature(restored,"f0")["visibleAreaM2"]==100
    restored.import_topology_metadata(companion,saved)
    assert feature(restored,"f0")["visibleAreaM2"]==50
    with pytest.raises(ValueError,match="nie pasuje"):
        restored.import_topology_metadata(companion,saved+b"x")


def test_positive_winding_repair_is_one_undoable_transaction(ws):
    doc=GeoMap(source())
    assert GeoMap.signed_area([(p.x,p.y) for p in doc.by_id["A"].points[:-1]])<0
    result=act(ws,{"action":"repair","ids":["f0"]})
    assert result["changed"]
    repaired=GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    coords=[(p.x,p.y) for p in repaired.by_id["A"].points[:-1]]
    assert GeoMap.signed_area(coords)>0
    assert repaired.checksum_valid
    ws.step_history("undo",**auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1]==source()


def test_new_polygon_is_positive_both_draw_directions(ws):
    operation={"action":"create","code":"5310",
               "fields":{"A1":"xd","A2":"So03"},
               "points":[[50,0],[50,10],[60,10],[60,0]]}
    plan=ws.preview_object_operation(operation,**auth(ws))
    outcome=ws.apply_object_operation(operation,preview_key=plan["previewKey"],
                                      **auth(ws))
    obj=GeoMap(ws.export_copy(auth(ws)["document_token"])[1]).by_id[
        outcome["createdUids"][0]]
    pts=[(p.x,p.y) for p in obj.points[:-1]]
    assert GeoMap.signed_area(pts)>0


def test_merge_polygons_and_undo(ws):
    move(ws,["f1"],-10,0)  # B becomes adjacent to A
    before=ws.export_copy(auth(ws)["document_token"])[1]
    result=act(ws,{"action":"merge","ids":["f0","f1"]})
    assert result["changed"]
    merged=GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    assert "A" in merged.by_id and "B" not in merged.by_id
    assert round(merged.by_id["A"].area_m2,3)==200
    assert merged.checksum_valid
    ws.step_history("undo",**auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1]==before


def test_split_polygon_by_polyline_preserves_total_area(ws):
    operation={"action":"split","ids":["f0"],
               "points":[[5,-2],[5,12]]}
    result=act(ws,operation)
    assert len(result["createdUids"])==1
    after=GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    areas=[after.by_id["A"].area_m2]+[
        after.by_id[uid].area_m2 for uid in result["createdUids"]]
    assert sum(areas)==pytest.approx(100,abs=.001)
    assert after.checksum_valid
    ws.step_history("undo",**auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1]==source()


def test_create_line_and_edit_line_and_undo(ws):
    made=act(ws,{"action":"create_line","code":"6900",
                 "points":[[40,0],[41,2],[42,3]],
                 "fields":{"A1":"linia"}})
    uid=made["createdUids"][0]
    assert not GeoMap(ws.export_copy(auth(ws)["document_token"])[1]).by_id[uid].is_closed
    original=ws.export_copy(auth(ws)["document_token"])[1]
    fid=made["createdIds"][0]
    act(ws,{"action":"edit_line","ids":[fid],
            "points":[[40,0],[44,2],[46,5]]})
    obj=GeoMap(ws.export_copy(auth(ws)["document_token"])[1]).by_id[uid]
    assert obj.points[-1].x==46 and obj.points[-1].y==5
    ws.step_history("undo",**auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1]==original


def test_ui_stage6_controls_and_magnet():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]/"geostudio/web_app/static"
    h=(root/"index.html").read_text(encoding="utf-8")
    j=(root/"map.js").read_text(encoding="utf-8")
    for item in ("tool-merge","tool-split","tool-winding","tool-line",
                 "split-dialog","line-dialog"):
        assert 'id="'+item+'"' in h
    assert "function magneticMove(" in j
    assert "function quickDuplicate(" in j
    assert "/api/geometry/preview" in j and "/api/geometry/apply" in j
