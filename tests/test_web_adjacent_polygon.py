"""Adjacent new polygons must survive native 1 mm coordinate rounding."""
from __future__ import annotations

import pytest
from shapely.geometry import Polygon
from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.geometry_6a import creation_overlap


@pytest.mark.parametrize("points",[
    [(10,0),(10,10),(20,10),(20,0)],  # shared edge
    [(10,10),(10,20),(20,20),(20,10)],  # shared point
    [(2,10),(8,10),(8,20),(2,20)],  # partial edge/T-junctions
])
def test_adjacent_creation_and_undo(points):
    source=MapBuilder().object(
        "5310","original",{"A1":"o"},[(0,0),(0,10),(10,10),(10,0)]).build()
    ws=PreviewWorkspace()
    ws.load_map(source,"adjacent.MAP")
    state=ws.editing_status()
    args={"document_token":state["documentToken"],"revision":state["revision"]}
    payload={"action":"create","code":"5310","points":[list(p) for p in points],
             "fields":{"A1":"new"}}
    preview=ws.preview_object_operation(payload,**args)
    result=ws.apply_object_operation(payload,preview_key=preview["previewKey"],**args)
    assert result["changed"]
    assert len(result["createdUids"])==1
    assert ws.export_copy(args["document_token"])[1].startswith(source)
    ws.step_history("undo",document_token=args["document_token"],
                    revision=result["revision"])
    assert ws.export_copy(args["document_token"])[1]==source


def test_diagonal_edge_projection_rounding():
    # Existing edge y=x/3; rounded projected point (2, .667) is
    # just inside the original triangle. Native coordinates are millimetres.
    existing=[(0,0),(30,10),(0,20)]
    new=[(2,.667),(20,6.667),(20,-5),(2,-5)]
    a,b=Polygon(existing),Polygon(new)
    assert a.intersection(b).area>0
    assert not creation_overlap(b,a)
    raw=MapBuilder().object("5310","original",{},existing).build()
    ws=PreviewWorkspace()
    ws.load_map(raw,"diagonal.MAP")
    state=ws.editing_status()
    args={"document_token":state["documentToken"],"revision":state["revision"]}
    payload={"action":"create","code":"5310","points":[list(p) for p in new],
             "fields":{}}
    preview=ws.preview_object_operation(payload,**args)
    assert ws.apply_object_operation(payload,preview_key=preview["previewKey"],**args)["changed"]


@pytest.mark.parametrize("points",[
    [(9,0),(9,10),(20,10),(20,0)],  # clear overlap
    [(9.997,0),(9.997,10),(20,10),(20,0)],  # 3 mm intrusion
    [(1,1),(1,2),(2,2),(2,1)],  # containment
    [(0,0),(0,10),(10,10),(10,0)],  # duplicate
])
def test_real_same_code_overlap_rejected(points):
    raw=MapBuilder().object("5310","original",{},
                            [(0,0),(0,10),(10,10),(10,0)]).build()
    ws=PreviewWorkspace()
    ws.load_map(raw,"overlap.MAP")
    state=ws.editing_status()
    args={"document_token":state["documentToken"],"revision":state["revision"]}
    payload={"action":"create","code":"5310","points":[list(p) for p in points],
             "fields":{}}
    with pytest.raises(ValueError,match="nakłada"):
        ws.preview_object_operation(payload,**args)
    assert ws.export_copy(args["document_token"])[1]==raw


def test_existing_hole_is_not_an_overlap():
    existing=Polygon([(0,0),(0,10),(10,10),(10,0)],
                     holes=[[(2,2),(2,8),(8,8),(8,2)]])
    assert not creation_overlap(Polygon([(2,2),(2,8),(8,8),(8,2)]),existing)
