"""Stage 10B — whole-document GIS search and safe phrase replacements.

Native MAP is a CP1250 record format: only existing A-fields may change,
every replacement must be previewed, and one Ctrl+Z restores the whole batch.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app


def make_map():
    return (MapBuilder()
        .object("5310","B-01",{"A1":"l","A2":"So120|II-0.3","A3":"Opis 5310"},
            [(0,0),(0,8),(10,8),(10,0)])
        .object("5310","B-02",{"A1":"b","A2":"so120|I-0.5","A3":"Opis domu"},
            [(20,0),(20,8),(30,8),(30,0)])
        .object("5216","D-03",{"A1":"dz","A2":"So120|II-0.3","A3":"Tylko działka"},
            [(40,0),(40,8),(50,8),(50,0)])
        .object("5310","B-04",{"A1":"b","A2":"Inne","A3":"Opis lasu"},
            [(60,0),(60,8),(70,8),(70,0)])
        .build())


def credentials(ws):
    status=ws.editing_status()
    return {"document_token":status["documentToken"],
            "revision":status["revision"]}


def op(**kwargs):
    return {
        "field":"A2", "needle":"So120", "replacement":"So130",
        "caseSensitive":False,"scope":"all","ids":[],"code":"",
        **kwargs,
    }


def test_find_by_code_uid_partial_all_fields_entire_map():
    raw=make_map()
    ws=PreviewWorkspace()
    ws.load_map(raw,"SOURCE.MAP")
    result=ws.find_objects(code="5310",limit=2)
    assert result["count"]==3
    assert result["truncated"]
    assert [x["uid"] for x in result["results"]]==["B-01","B-02"]
    result=ws.find_objects(field="ID",value="b-02",match="exact")
    assert result["count"]==1 and result["results"][0]["code"]=="5310"
    result=ws.find_objects(field="A2",value="SO120",match="contains")
    assert result["count"]==3
    result=ws.find_objects(field="A2",value="so120|I-0.5",match="exact")
    assert result["count"]==1
    result=ws.find_objects(field="*",value="opis",match="contains")
    assert result["count"]==3
    result=ws.find_objects(code="5310",field="A1",value="b",match="exact")
    assert [x["uid"] for x in result["results"]]==["B-02","B-04"]
    assert ws.export_copy(ws.editing_status()["documentToken"])[1]==raw
    assert not ws.editing_status()["dirty"]


@pytest.mark.parametrize("params",[
    {},{"code":"53"},{"code":"000a"},{"field":"__"},
    {"match":"regex","value":"So120"},
    {"value":"a"*161},{"value":"abc","limit":1000},
])
def test_search_rejects_missing_or_invalid_criteria(params):
    ws=PreviewWorkspace()
    ws.load_map(make_map(),"source.MAP")
    with pytest.raises(ValueError):
        ws.find_objects(**params)


def test_preview_is_readonly_then_apply_is_single_undo_batch():
    raw=make_map()
    ws=PreviewWorkspace()
    ws.load_map(raw,"source.MAP")
    request=op(code="5310")
    report=ws.preview_replace_phrase(request,**credentials(ws))
    assert report["changedObjects"]==2
    assert report["occurrences"]==2
    assert report["canApply"]
    assert report["scanned"]==3
    assert len(report["examples"])==2
    assert report["examples"][0]["before"]=="So120|II-0.3"
    assert report["examples"][0]["after"]=="So130|II-0.3"
    assert ws.export_copy(ws.editing_status()["documentToken"])[1]==raw
    assert not ws.editing_status()["dirty"]
    applied=ws.apply_replace_phrase(request,preview_key=report["previewKey"],
                                    **credentials(ws))
    assert applied["changedObjects"]==2 and applied["occurrences"]==2
    assert applied["dirty"] and applied["canUndo"]
    assert ws.details("f0")["fields"]["A2"]=="So130|II-0.3"
    assert ws.details("f1")["fields"]["A2"]=="So130|I-0.5"
    assert ws.details("f2")["fields"]["A2"]=="So120|II-0.3"
    changed=ws.export_copy(ws.editing_status()["documentToken"])[1]
    assert changed!=raw
    assert b':A1[b]' in changed and b':A1[l]' in changed
    ws.step_history("undo",**credentials(ws))
    assert ws.export_copy(ws.editing_status()["documentToken"])[1]==raw
    ws.step_history("redo",**credentials(ws))
    assert ws.export_copy(ws.editing_status()["documentToken"])[1]==changed


def test_selection_only_and_case_sensitivity_with_empty_replacement():
    ws=PreviewWorkspace()
    ws.load_map(make_map(),"source.MAP")
    needle=op(scope="selection",ids=["f1"],code="5310",
              caseSensitive=True)
    report=ws.preview_replace_phrase(needle,**credentials(ws))
    assert report["changedObjects"]==0
    with pytest.raises(RuntimeError):
        ws.apply_replace_phrase(needle,preview_key="bad",**credentials(ws))
    request=op(scope="selection",ids=["f1"],code="5310",
               caseSensitive=False,replacement="")
    report=ws.preview_replace_phrase(request,**credentials(ws))
    assert report["changedObjects"]==1 and report["occurrences"]==1
    ws.apply_replace_phrase(request,preview_key=report["previewKey"],
                            **credentials(ws))
    assert ws.details("f0")["fields"]["A2"]=="So120|II-0.3"
    assert ws.details("f1")["fields"]["A2"]=="|I-0.5"
    assert ws.details("f2")["fields"]["A2"]=="So120|II-0.3"


def test_replacement_requires_issued_preview_and_fails_for_stale_revision():
    ws=PreviewWorkspace()
    ws.load_map(make_map(),"source.MAP")
    request=op()
    with pytest.raises(RuntimeError):
        ws.apply_replace_phrase(request,preview_key="0"*64,**credentials(ws))
    a=ws.preview_replace_phrase(request,**credentials(ws))
    with pytest.raises(RuntimeError):
        ws.apply_replace_phrase(op(replacement="ANOTHER"),
                                preview_key=a["previewKey"],**credentials(ws))
    ws.move_label("f0","A2",3,4,**credentials(ws))
    with pytest.raises(RuntimeError):
        ws.apply_replace_phrase(request,preview_key=a["previewKey"],
                                document_token=ws.editing_status()["documentToken"],
                                revision=a["revision"])
    assert ws.details("f0")["fields"]["A2"]=="So120|II-0.3"


@pytest.mark.parametrize("override",[
    {"needle":""},
    {"field":"ID"},
    {"replacement":"abc]"},
    {"replacement":"abc\n"},
    {"replacement":"☃"},
    {"replacement":"x"*513},
    {"scope":"selection","ids":[]},
    {"scope":"all","ids":["f0"]},
    {"scope":"selection","ids":["f0","f0"]},
    {"code":"99999"},
])
def test_replacement_rejects_invalid_scope_and_geographic_encoding(override):
    ws=PreviewWorkspace()
    ws.load_map(make_map(),"source.MAP")
    with pytest.raises((ValueError,LookupError)):
        ws.preview_replace_phrase(op(**override),**credentials(ws))


def test_replacement_limit_is_checked_on_final_cp1250_value():
    ws=PreviewWorkspace()
    ws.load_map(make_map(),"source.MAP")
    with pytest.raises(ValueError,match="512"):
        ws.preview_replace_phrase(
            op(needle="So120",replacement="ą"*510),**credentials(ws))


def test_replacement_http_search_and_stale_previews_return_status_codes():
    ws=PreviewWorkspace()
    ws.load_map(make_map(),"source.MAP")
    app=create_app(ws)
    with TestClient(app) as client:
        header={"X-GeoStudio-Token":app.state.api_token}
        assert client.get("/api/find",params={"code":"5310"}).status_code==403
        res=client.get("/api/find",params={"code":"5310"},headers=header)
        assert res.status_code==200 and res.json()["count"]==3
        status=ws.editing_status()
        body={"operation":op(),"documentToken":status["documentToken"],
              "revision":status["revision"]}
        assert client.post("/api/replace/preview",json=body).status_code==403
        pre=client.post("/api/replace/preview",headers=header,json=body)
        assert pre.status_code==200,pre.text
        assert not ws.editing_status()["dirty"]
        result=client.post("/api/replace/apply",headers=header,json={
            **body,"previewKey":pre.json()["previewKey"]})
        assert result.status_code==200,result.text
        assert result.json()["changedObjects"]==3
        stale=client.post("/api/replace/apply",headers=header,json={
            **body,"previewKey":pre.json()["previewKey"]})
        assert stale.status_code==409


def test_whole_map_viewport_returns_all_corners_without_further_spatial_requery():
    ws=PreviewWorkspace()
    ws.load_map(make_map(),"source.MAP")
    bounds=tuple(ws.metadata()["bounds"])
    data=ws.viewport(bounds)
    assert data["total"]==4
    assert [f["id"] for f in data["features"]]==[
        "f0","f1","f2","f3"]
    assert not data["limited"]


def test_fixed_size_font_and_no_http_on_subsequent_zoom_small_map():
    static=Path(__file__).resolve().parents[1]/"geostudio/web_app/static"
    src=(static/"map.js").read_text(encoding="utf-8")
    assert "state.localMapCandidate=meta.objectCount<=50000" in src
    assert "if(state.localMapReady){" in src
    assert "let view=state.localMapCandidate?[...state.meta.bounds]" in src
    assert "beginNavigationPreview();" in src
    assert "renderLabels(state.features.filter" in src
    assert "function labelFontSize(feature,label,selected)" in src
    node=shutil.which("node")
    if not node:pytest.skip("Node is optional for JS zoom regression")
    js=r"""
const assert=require('node:assert/strict');
const fs=require('node:fs');
const src=fs.readFileSync('map.js','utf-8');
const a=src.indexOf('  function labelFontSize(');
const b=src.indexOf('  function labelTextRows(',a);
const font=new Function('state',src.slice(a,b)+'return labelFontSize;');
const label={size:16,field:'A1'};
for(const scale of [.0001,.002,.2,1,10,100,3000]){
  const fn=font({scale,edit:{sourceCompilationScale:5000,
                              compilationScale:5000}});
  assert.equal(fn({code:'5310'},label,false),16);
}
assert.equal(font({scale:1,edit:{sourceCompilationScale:5000,
         compilationScale:10000}})({code:'5310'},label,false),32);
"""
    result=subprocess.run([node,"-e",js],cwd=static,
                          capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr


def test_ui_shortcuts_and_safe_result_text():
    root=Path(__file__).resolve().parents[1]/"geostudio/web_app/static"
    html=(root/"index.html").read_text(encoding="utf-8")
    js=(root/"map.js").read_text(encoding="utf-8")
    for text in ('id="find-dialog"','id="find-field"','id="find-code"',
                 'id="replace-dialog"','id="replace-scope"',
                 'id="replace-needle"','id="replace-apply"'):
        assert text in html
    assert "function openFindDialog()" in js
    assert "function openReplaceDialog()" in js
    assert '"/api/replace/preview"' in js
    assert '"/api/replace/apply"' in js
    assert '"/api/find?"' in js
    assert "title.textContent=result.code" in js
    assert "before.textContent=" in js and "after.textContent=" in js
    assert 'previewKey:report.previewKey' in js
