"""Stage 10A: separate label moves, presentation scales, safe saving and drawing UX."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile
import json
import sys

import pytest
from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app
from geostudio.web_app.native_picker import NativeMapPicker


def _source():
    return (MapBuilder()
        .object("5310","B1",{"A1":"l","A2":"So120|II-0.3"},
                [(0,0),(0,20),(20,20),(20,0)])
        .object("5310","B2",{"A1":"b","A2":"So80|I-0.5"},
                [(35,0),(35,20),(55,20),(55,0)])
        .build())


def _auth(ws):
    status=ws.editing_status()
    return {"document_token":status["documentToken"],
            "revision":status["revision"]}


def test_separate_a1_a2_movements_are_undoable_and_map_records_unchanged():
    source=_source()
    ws=PreviewWorkspace()
    ws.load_map(source,"source.MAP")
    start=ws.viewport((-30,-70,30,2))["features"][0]["labels"]
    assert [x["field"] for x in start]==["A1","A2"]
    result=ws.move_label("f0","A2",11.023,12.456,**_auth(ws))
    assert result["changed"] and result["dirty"]
    assert ws._label_positions["B1"]["A2"]==[11.023,12.456]
    labels=ws.viewport((-30,-70,30,2))["features"][0]["labels"]
    assert labels[0]["field"]=="A1" and not labels[0]["manuallyPlaced"]
    assert labels[1]["field"]=="A2" and labels[1]["manuallyPlaced"]
    assert labels[1]["x"]==12.456 and labels[1]["y"]==-11.023
    assert ws.export_copy(ws.editing_status()["documentToken"])[1]==source
    ws.step_history("undo",**_auth(ws))
    assert "B1" not in ws._label_positions or "A2" not in ws._label_positions["B1"]
    assert ws.export_copy(ws.editing_status()["documentToken"])[1]==source
    ws.step_history("redo",**_auth(ws))
    assert ws._label_positions["B1"]["A2"]==[11.023,12.456]


def test_5310_style_for_a1_does_not_hide_a2_and_scale_does_not_change_map():
    source=_source()
    ws=PreviewWorkspace()
    ws.load_map(source,"source.MAP")
    assert ws.metadata()["sourceCompilationScale"]>=100
    s=ws.set_label_settings("5310","A1",{
        "visible":True,"size":22,"color":"#112233","bold":False},**_auth(ws))
    assert s["dirty"]
    labels=ws.viewport((-30,-70,30,2))["features"][0]["labels"]
    assert [x["field"] for x in labels]==["A1","A2"]
    assert labels[0]["size"]==22 and labels[0]["color"]=="#112233"
    s=ws.set_compilation_scale(2000,**_auth(ws))
    assert s["compilationScale"]==2000
    assert ws.metadata()["compilationScale"]==2000
    assert ws.label_settings("5310")["fields"]["A1"]["size"]==22
    assert ws.export_copy(ws.editing_status()["documentToken"])[1]==source
    ws.step_history("undo",**_auth(ws))
    assert ws.metadata()["compilationScale"]==ws.metadata()["sourceCompilationScale"]
    ws.step_history("redo",**_auth(ws))
    assert ws.metadata()["compilationScale"]==2000


def test_label_sidecar_is_checksum_bound_preserves_independent_positions_and_scale():
    raw=_source()
    ws=PreviewWorkspace()
    ws.load_map(raw,"base.MAP")
    ws.move_label("f0","A1",1,2,**_auth(ws))
    ws.move_label("f0","A2",3,4,**_auth(ws))
    ws.set_compilation_scale(1000,**_auth(ws))
    meta=ws.export_visual_sidecar(raw)
    assert json.loads(meta)["sha256"]==sha256(raw).hexdigest()
    assert len(json.loads(meta)["labels"]["B1"])==2
    another=PreviewWorkspace()
    another.load_map(raw,"base.MAP")
    result=another.set_visual_sidecar(meta)
    assert result["labelPositions"]==1
    assert another._label_positions["B1"]=={"A1":[1,2],"A2":[3,4]}
    assert another.metadata()["compilationScale"]==1000
    assert another.export_copy(another.editing_status()["documentToken"])[1]==raw
    altered=PreviewWorkspace()
    altered.load_map(raw+b" ", "base.MAP")
    with pytest.raises(ValueError,match="nie pasuje"):
        altered.set_visual_sidecar(meta)


def test_http_label_move_and_settings_use_token_revision_validation():
    ws=PreviewWorkspace()
    ws.load_map(_source(),"base.MAP")
    app=create_app(ws)
    with TestClient(app) as client:
        headers={"X-GeoStudio-Token":app.state.api_token}
        first=ws.editing_status()
        payload={"fid":"f0","field":"A2","x":5,"y":7,
                 "documentToken":first["documentToken"],
                 "revision":first["revision"]}
        denied=client.post("/api/labels/move",json=payload)
        assert denied.status_code==403
        moved=client.post("/api/labels/move",headers=headers,json=payload)
        assert moved.status_code==200,moved.text
        assert moved.json()["changed"] is True
        stale=client.post("/api/labels/move",headers=headers,json=payload)
        assert stale.status_code==409
        malformed=client.post("/api/labels/move",headers=headers,json={
            **payload,"revision":ws.editing_status()["revision"],
            "x":1e100})
        assert malformed.status_code==400
        config=client.get("/api/labels/settings",headers=headers,
                          params={"code":"5310"})
        assert config.status_code==200
        spec=client.post("/api/labels/settings",headers=headers,json={
            "documentToken":ws.editing_status()["documentToken"],
            "revision":ws.editing_status()["revision"],
            "code":"5310","field":"A2",
            "properties":{"visible":True,"size":18,
                          "color":"#B01122","bold":True}})
        assert spec.status_code==200,spec.text
        scale=client.post("/api/compilation-scale",headers=headers,json={
            "documentToken":ws.editing_status()["documentToken"],
            "revision":ws.editing_status()["revision"],
            "denominator":2000})
        assert scale.status_code==200,scale.text
        assert scale.json()["compilationScale"]==2000


def test_browser_download_with_labels_includes_map_and_visual_json_without_masks():
    ws=PreviewWorkspace()
    ws.load_map(_source(),"base.MAP")
    ws.move_label("f0","A2",1,2,**_auth(ws))
    assert not ws.editing_status()["hasReversibleMasks"]
    assert ws.editing_status()["hasVisualStyles"]
    app=create_app(ws)
    with TestClient(app) as client:
        response=client.get("/api/export/package",
            params={"documentToken":ws.editing_status()["documentToken"]},
            headers={"X-GeoStudio-Token":app.state.api_token})
    assert response.status_code==200,response.text
    archive=ZipFile(BytesIO(response.content))
    names=archive.namelist()
    assert len(names)==2
    assert names[0].endswith(".MAP") and names[1].endswith(".geostudio.json")
    content=archive.read(names[0])
    style=json.loads(archive.read(names[1]))
    assert style["sha256"]==sha256(content).hexdigest()
    assert style["labels"]["B1"]["A2"]==[1,2]


def test_windows_save_as_and_reopen_preserves_individual_a1_a2(tmp_path,monkeypatch):
    raw=_source()
    source=tmp_path/"source.MAP"
    source.write_bytes(raw)
    dest=tmp_path/"saved_labels.MAP"
    class Root:
        def withdraw(self):pass
        def attributes(self,*args):pass
        def update(self):pass
        def destroy(self):pass
    tkinter=SimpleNamespace(Tk=Root,
        filedialog=SimpleNamespace(
            asksaveasfilename=lambda **kw:str(dest),
            askopenfilename=lambda **kw:str(dest)))
    monkeypatch.setitem(sys.modules,"tkinter",tkinter)
    ws=PreviewWorkspace()
    ws.load_map(raw,source.name)
    ws.move_label("f0","A1",1,2,**_auth(ws))
    ws.move_label("f0","A2",3,4,**_auth(ws))
    bridge=NativeMapPicker(ws,settings=tmp_path/"cfg"/"preferences.json")
    result=bridge.save_map()
    assert result["visualPath"] and Path(result["visualPath"]).exists()
    assert source.read_bytes()==raw
    reopened=PreviewWorkspace()
    bridge2=NativeMapPicker(reopened,settings=tmp_path/"cfg"/"preferences.json")
    info=bridge2.open_map()
    assert info["metadata"]["visualImported"]["labelPositions"]==1
    assert reopened._label_positions["B1"]=={"A1":[1,2],"A2":[3,4]}
    assert dest.read_bytes()!=b""


def test_esc_undoes_last_sketch_point_and_first_vertex_closes_one_click():
    ui=(Path(__file__).resolve().parents[1]/
        "geostudio/web_app/static/map.js").read_text("utf-8")
    assert "state.drawPoints.pop();" in ui
    assert 'state.tool==="draw"&&snapped.kind==="start"' in ui
    assert "finishDrawPolygon();" in ui
    assert 'finishDrawPolygon();' in ui
    assert 'quickCreatePolygon(ev)' in ui
    assert "first=state.drawPoints[0]" in ui
    assert 'state.drawPoints.length>=3' in ui
    assert 'state.drawMagnet' in ui


def test_zoom_uses_live_vectors_instead_of_blurred_bitmap():
    ui=(Path(__file__).resolve().parents[1]/
        "geostudio/web_app/static/map.js").read_text("utf-8")
    assert "function beginNavigationPreview()" not in ui
    assert "function drawNavigationPreview()" not in ui
    assert "snapshotContext.drawImage(canvas,0,0);" not in ui
    for source in (
        "renderScreenLabels(features);drawGcpMapMarkers();",
        "state.previewActive=false;state.previewCamera=null;",
        "// Render current vector coordinates at the current camera on EVERY",
        "for(const feature of features) renderFill(feature);",
        "for(const feature of features) renderStroke(feature);"
    ):
        assert source in ui


def test_native_recovery_includes_visual_positions_and_compilation_scale(
        tmp_path,monkeypatch):
    raw=_source()
    source=tmp_path/"source.MAP"
    source.write_bytes(raw)
    monkeypatch.setattr(NativeMapPicker,"_choose_path",lambda _:str(source))
    ws=PreviewWorkspace()
    bridge=NativeMapPicker(ws,settings=tmp_path/"cfg"/"preferences.json")
    assert not bridge.open_map()["cancelled"]
    ws.move_label("f0","A2",14,15,**_auth(ws))
    ws.set_compilation_scale(1000,**_auth(ws))
    assert bridge.save_recovery()["saved"]
    recovered=PreviewWorkspace()
    picker=NativeMapPicker(recovered,settings=tmp_path/"cfg"/"preferences.json")
    assert picker.open_map()["metadata"]["recoveryAvailable"]
    assert picker.restore_recovery()["restored"]
    assert recovered._label_positions["B1"]["A2"]==[14,15]
    assert recovered.metadata()["compilationScale"]==1000
    assert recovered.editing_status()["dirty"]
    assert source.read_bytes()==raw
