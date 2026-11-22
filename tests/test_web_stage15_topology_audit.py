"""Stage 15: read-only topology diagnostics and GEO-MAP Ls forest grouping."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app


def _square(x0,y0,x1,y1):
    return [(x0,y0),(x0,y1),(x1,y1),(x1,y0)]


def test_forest_grades_from_both_5220_and_5230_and_both_label_fields():
    original=(MapBuilder()
        .object("5220","FOREST-A",{"A1":"Ls","A2":"LsVI"},_square(0,0,8,8))
        .object("5230","FOREST-B",{"A1":"LsV","A2":"LsV"},_square(10,0,18,8))
        .object("5220","FOREST-C",{"A1":"Ls","A2":""},_square(20,0,28,8))
        .object("5230","FOREST-D",{"A1":"R","A2":"LsIV"},_square(30,0,38,8))
        .object("5230","SOIL",{"A1":"R","A2":"RV"},_square(40,0,48,8))
        .build())
    ws=PreviewWorkspace()
    meta=ws.load_map(original,"forest.MAP")
    forest=meta["forestClasses"]
    assert forest=={"Ls":1,"LsIV":1,"LsV":1,"LsVI":1}
    uses={x["key"] for x in meta["landUseClasses"]}
    assert uses=={"rv"}
    assert {f["layer"] for f in ws.viewport(tuple(meta["bounds"]))["features"]}=={
        "Użytki Leśne","Użytki"}
    assert ws.export_copy(ws.editing_status()["documentToken"])[1]==original


def test_topology_finds_real_errors_and_avoids_foreign_code_false_positives():
    source=(MapBuilder(ext=(5000,0,0,200,200))
        # Exact duplicate same code and A1/A2, plus an overlapping
        # neighboring parcel with a different shape.
        .object("5216","P-1",{"A1":"d"},_square(0,0,10,10))
        .object("5216","P-2",{"A1":"d"},_square(0,0,10,10))
        .object("5216","P-3",{"A1":"d"},_square(5,5,15,15))
        # 12 mm slit between parallel 10-m boundaries, same code.
        .object("5220","U-1",{"A1":"R","A2":"RV"},
                _square(30,0,40,10))
        .object("5220","U-2",{"A1":"R","A2":"RVI"},
                _square(30,10.012,40,20.012))
        # Touching buildings: point (60,5) is on B-1 edge but
        # absent from its explicit P vertices (T-junction).
        .object("5310","B-1",{"A1":"m"},_square(50,0,60,10))
        .object("5310","B-2",{"A1":"m"},
                [(60,0),(60,5),(70,5),(70,0)])
        .object("5310","OPEN",{"A1":"m"},
                [(80,0),(80,10),(90,10)],closed=False)
        .object("5310","INVALID",{"A1":"m"},
                [(100,0),(110,10),(100,10),(110,0)])
        # Different code overlapping first parcel is legitimate and
        # MUST NOT create extra same-code overlap flags.
        .object("5230","FOREIGN",{"A1":"dr"},
                _square(0,0,10,10))
        .build())
    ws=PreviewWorkspace()
    meta=ws.load_map(source,"geometry.MAP")
    result=ws.topology_audit(ws.editing_status()["documentToken"],
                             ws.editing_status()["revision"])
    kinds={issue["kind"] for issue in result["issues"]}
    assert {"duplicate","overlap","gap","node","open","invalid"}<=kinds
    assert result["checked"]==10
    assert not result["skippedObjects"]
    assert result["documentToken"]==ws.editing_status()["documentToken"]
    assert result["revision"]==0
    dup=[i for i in result["issues"] if i["kind"]=="duplicate"]
    assert len(dup)>=1
    assert dup[0]["canDeleteDuplicate"] is True
    assert len(dup[0]["ids"])==2
    assert not any("FOREIGN" in issue["ids"] for issue in result["issues"])
    for issue in result["issues"]:
        assert issue["bounds"][2]>=issue["bounds"][0]
        assert issue["bounds"][3]>=issue["bounds"][1]
        assert isinstance(issue["location"]["x"],(float,int))
        assert isinstance(issue["location"]["y"],(float,int))
    assert ws.export_copy(ws.editing_status()["documentToken"])[1]==source


def test_equal_shapes_with_different_attributes_are_not_safe_to_delete():
    source=(MapBuilder()
        .object("5310","B-1",{"A1":"100","A2":"Budynek A"},
                _square(0,0,10,10))
        .object("5310","B-2",{"A1":"101","A2":"Budynek B"},
                _square(0,0,10,10))
        .build())
    ws=PreviewWorkspace()
    ws.load_map(source,"different-attributes.MAP")
    state=ws.editing_status()
    result=ws.topology_audit(state["documentToken"],state["revision"])
    identical=[x for x in result["issues"] if x["kind"]=="duplicate"]
    assert identical and all(
        x["canDeleteDuplicate"] is False for x in identical)
    assert ws.export_copy(state["documentToken"])[1]==source


def test_topology_does_not_flag_cross_code_shared_vertices():
    source=(MapBuilder()
        .object("5216","P-1",{},_square(0,0,10,10))
        .object("5310","B-1",{},_square(0,0,10,10))
        .build())
    ws=PreviewWorkspace()
    ws.load_map(source,"good.MAP")
    state=ws.editing_status()
    result=ws.topology_audit(state["documentToken"],state["revision"])
    assert result["issues"]==[]
    assert ws.export_copy(state["documentToken"])[1]==source


def test_topology_revision_token_validation_and_limit():
    ws=PreviewWorkspace()
    ws.load_map(MapBuilder().object("5310","A",{},
        _square(0,0,10,10)).build(),"test.MAP")
    state=ws.editing_status()
    with pytest.raises(RuntimeError,match="Mapa zmieniła"):
        ws.topology_audit(state["documentToken"],state["revision"]+1)
    with pytest.raises(ValueError,match="Limit"):
        ws.topology_audit(state["documentToken"],state["revision"],0)


def test_local_api_blocks_unauthenticated_and_stale_topology_requests():
    app=create_app()
    source=MapBuilder().object("5310","A",{},_square(0,0,10,10)).build()
    with TestClient(app) as client:
        auth={"X-GeoStudio-Token":app.state.api_token}
        loaded=client.post("/api/map",headers={**auth,"X-Map-Name":"test.MAP"},
                           content=source)
        assert loaded.status_code==200,loaded.text
        meta=loaded.json()
        params={"documentToken":meta["documentToken"],
                "revision":meta["revision"],"limit":50}
        assert client.get("/api/topology/audit",params=params).status_code==403
        response=client.get("/api/topology/audit",params=params,headers=auth)
        assert response.status_code==200,response.text
        assert response.json()["issues"]==[]
        assert client.get("/api/topology/audit",headers=auth,params={
            **params,"revision":meta["revision"]+1}).status_code==409


def test_map_audit_ui_has_live_list_and_manual_fix_actions():
    root=Path(__file__).resolve().parents[1]/"geostudio/web_app/static"
    html=(root/"index.html").read_text(encoding="utf-8")
    js=(root/"map.js").read_text(encoding="utf-8")
    css=(root/"styles.css").read_text(encoding="utf-8")
    for name in (
        "tool-topology-scan","topology-panel",
        "topology-issues","topology-filter","topology-rescan","topology-edit",
        "topology-delete-duplicate"
    ):
        assert f'id="{name}"' in html
    assert 'id="tool-topology-list"' not in html
    assert "Kontrola poligonów" in html
    assert "/api/topology/audit?" in js
    assert "drawTopologyHighlight(features)" in js
    assert "function focusTopologyIssue(issue)" in js
    assert "function removeTopologyDuplicate()" in js
    assert "className=\"topology-issue\"" in js
    assert ".topology-panel" in css
