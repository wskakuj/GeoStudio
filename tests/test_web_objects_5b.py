"""Object operations stage 5B: copy, delete, create, history and MAP safety."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.geomap import GeoMap
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.native_picker import NativeMapPicker
from geostudio.web_app.server import create_app


def source():
    return (MapBuilder(ext=(5000, 0, 0, 100, 100))
        .raw(";# unknown record before objects")
        .object("5310", "A", {"A1":"Dom", "A2":"Łąka"},
                [(0,0),(0,10),(10,10),(10,0)])
        .object("5310", "B", {"A1":"Garaż"},
                [(20,0),(20,10),(30,10),(30,0)])
        .object("5230", "R", {"A1":"dr"},
                [(0,20),(0,30),(10,30),(10,20)])
        .build())


@pytest.fixture
def ws():
    w=PreviewWorkspace()
    w.load_map(source(),"MOKRA WIEŚ.MAP")
    return w


def auth(w):
    d=w.editing_status()
    return {"document_token":d["documentToken"],"revision":d["revision"]}


def change(w,operation):
    report=w.preview_object_operation(operation,**auth(w))
    return w.apply_object_operation(
        operation,preview_key=report["previewKey"],**auth(w))


def objlines(doc,uid):
    obj=doc.by_id[uid]
    return doc.lines[obj.start:obj.end]


def test_copy_preserves_native_records_and_unique_ids_and_undo(ws):
    original=source()
    result=change(ws,{"action":"copy","ids":["f0","f1"],"dx":0,"dy":40})
    assert result["changed"] and len(result["createdUids"])==2
    assert len(set(result["createdUids"]))==2
    after=GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    before=GeoMap(original)
    assert after.checksum_valid
    for uid in ("A","B","R"):
        assert objlines(before,uid)==objlines(after,uid)
    for original_uid,new_uid in zip(("A","B"),result["createdUids"]):
        a=before.by_id[original_uid]
        b=after.by_id[new_uid]
        assert b.code==a.code and b.style==a.style and b.fields["A1"]==a.fields["A1"]
        assert b.points[0].x==a.points[0].x
        assert b.points[0].y==a.points[0].y+40
    ws.step_history("undo",**auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1]==original
    ws.step_history("redo",**auth(ws))
    assert set(result["createdUids"])<=set(
        GeoMap(ws.export_copy(auth(ws)["document_token"])[1]).by_id)


def test_copy_overlaps_as_reversible_overlay_without_changing_original(ws):
    original=ws.export_copy(auth(ws)["document_token"])[1]
    operation={"action":"copy","ids":["f0"],"dx":1,"dy":0}
    report=ws.preview_object_operation(operation,**auth(ws))
    assert report["canApply"]
    result=ws.apply_object_operation(operation,preview_key=report["previewKey"],**auth(ws))
    assert len(result["createdUids"])==1
    after=GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    assert objlines(after,"A")==objlines(GeoMap(original),"A")
    assert ws.editing_status()["hasReversibleMasks"]


def test_delete_exact_selection_and_restore(ws):
    original=source()
    report=change(ws,{"action":"delete","ids":["f0"]})
    assert report["changed"]
    doc=GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    before=GeoMap(original)
    assert "A" not in doc.by_id
    for uid in ("B","R"):
        assert objlines(doc,uid)==objlines(before,uid)
    ws.step_history("undo",**auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1]==original
    ws.step_history("redo",**auth(ws))
    assert "A" not in GeoMap(ws.export_copy(auth(ws)["document_token"])[1]).by_id


def test_create_closed_polygon_with_polish_attributes(ws):
    result=change(ws,{"action":"create","code":"5310",
                      "points":[[60,0],[60,10],[70,10],[70,0]],
                      "fields":{"A1":"Żółć","A2":"Gospodarczy"}})
    assert len(result["createdUids"])==1
    raw=ws.export_copy(auth(ws)["document_token"])[1]
    doc=GeoMap(raw)
    assert doc.checksum_valid and doc.declared_lines==len(doc.lines)
    obj=doc.by_id[result["createdUids"][0]]
    assert obj.is_closed and len(obj.points)==5
    assert obj.fields["A1"]=="Żółć"
    assert obj.fields["A2"]=="Gospodarczy"
    ws.step_history("undo",**auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1]==source()


def test_create_same_code_overlap_and_stale_preview_rejected(ws):
    operation={"action":"create","code":"5310",
               "points":[[0,0],[0,8],[8,8],[8,0]],"fields":{}}
    with pytest.raises(ValueError,match="nakłada"):
        ws.preview_object_operation(operation,**auth(ws))
    operation["points"]=[[60,0],[60,10],[70,10],[70,0]]
    plan=ws.preview_object_operation(operation,**auth(ws))
    with pytest.raises(RuntimeError):
        ws.apply_object_operation(
            {**operation,"code":"5230"},preview_key=plan["previewKey"],**auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1]==source()


def test_http_object_preview_apply_auth_and_checksum():
    app=create_app()
    with TestClient(app) as c:
        headers={"X-GeoStudio-Token":app.state.api_token}
        opened=c.post("/api/map",content=source(),headers={
            **headers,"X-Map-Name":"test.MAP"}).json()
        payload={"documentToken":opened["documentToken"],"revision":0,
                 "operation":{"action":"copy","ids":["f0"],"dx":0,"dy":40}}
        assert c.post("/api/objects/preview",json=payload).status_code==403
        preview=c.post("/api/objects/preview",json=payload,headers=headers)
        assert preview.status_code==200,preview.text
        result=c.post("/api/objects/apply",headers=headers,json={
            **payload,"previewKey":preview.json()["previewKey"]})
        assert result.status_code==200,result.text
        assert len(result.json()["createdUids"])==1
        assert c.post("/api/objects/apply",headers=headers,json={
            **payload,"previewKey":preview.json()["previewKey"]}).status_code==409
        saved=c.get("/api/export/map",headers=headers,
                    params={"documentToken":opened["documentToken"]})
        assert GeoMap(saved.content).checksum_valid


def test_native_save_as_writes_to_explicit_path(tmp_path,monkeypatch,ws):
    destination=tmp_path/"MOKRA WIEŚ_GeoStudio2_kopia.MAP"
    class Root:
        def withdraw(self): pass
        def attributes(self,*args): pass
        def update(self): pass
        def destroy(self): pass
    fake=SimpleNamespace(Tk=Root,filedialog=SimpleNamespace(
        asksaveasfilename=lambda **kwargs: str(destination)))
    monkeypatch.setitem(sys.modules,"tkinter",fake)
    picker=NativeMapPicker(ws,settings=tmp_path/"settings.json")
    result=picker.save_map()
    assert not result["cancelled"] and result["path"]==str(destination)
    assert GeoMap(destination.read_bytes()).checksum_valid
    # Native Save As normalizes winding without touching the open original.
    assert ws.export_copy(ws.editing_status()["documentToken"])[1]==source()
    output=GeoMap(destination.read_bytes())
    assert [(p.x,p.y) for p in output.by_id["A"].points]!=[
        (p.x,p.y) for p in GeoMap(source()).by_id["A"].points]
    assert output.by_id["A"].area_m2==GeoMap(source()).by_id["A"].area_m2
    assert output.checksum_valid


def test_ui_has_object_tools_and_actions():
    from pathlib import Path
    folder=Path(__file__).resolve().parents[1]/"geostudio/web_app/static"
    html=(folder/"index.html").read_text(encoding="utf-8")
    js=(folder/"map.js").read_text(encoding="utf-8")
    for part in ("tool-copy","tool-delete-objects","tool-new-polygon",
                 "copy-dialog","create-dialog","copy-preview","copy-apply",
                 "create-preview","create-apply"):
        assert 'id="'+part+'"' in html
    assert "/api/objects/preview" in js and "/api/objects/apply" in js
    assert "function drawDraftPolygon" in js
