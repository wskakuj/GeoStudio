"""Multiple MAPs are separate working documents, including HTTP and native routes."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from conftest import MapBuilder
from geostudio.web_app.server import create_app
from geostudio.web_app.documents import DocumentNativeBridge, MAX_DOCUMENTS


def _map(uid, start):
    x = start
    return MapBuilder().object("5310", uid, {"A1": uid},
                               [(x,0),(x,10),(x+10,10),(x+10,0)]).build()


def test_two_tabs_preserve_distinct_map_history_and_exports():
    app = create_app(multi_document=True)
    with TestClient(app) as client:
        auth = {"X-GeoStudio-Token": app.state.api_token}
        a = client.get("/api/documents", headers=auth).json()["documents"][0]
        b = client.post("/api/documents", headers=auth).json()["id"]
        def h(key):
            return {**auth, "X-GeoStudio-Document": key}
        source_a, source_b = _map("A",0), _map("B",100)
        def upload(key, raw, name):
            response = client.post("/api/map", content=raw,
                                  headers={**h(key),"X-Map-Name":name})
            assert response.status_code == 200, response.text
            return response.json()
        with ThreadPoolExecutor(max_workers=2) as pool:
            fa = pool.submit(upload,a,source_a,"first.MAP")
            fb = pool.submit(upload,b,source_b,"second.MAP")
            ma, mb = fa.result(), fb.result()
        assert ma["documentToken"] != mb["documentToken"]
        def meta(key):
            return client.get("/api/map",headers=h(key)).json()
        assert meta(a)["name"] == "first.MAP"
        assert meta(b)["name"] == "second.MAP"
        body = {"documentToken":ma["documentToken"],"revision":ma["revision"],
                "operation":{"action":"create","code":"5310","fields":{"A1":"new"},
                             "points":[[12,0],[12,10],[20,10],[20,0]]}}
        preview = client.post("/api/objects/preview",headers=h(a),json=body)
        assert preview.status_code == 200, preview.text
        assert client.post("/api/objects/preview",headers=h(b),json=body).status_code==409
        created = client.post("/api/objects/apply",headers=h(a),
                              json={**body,"previewKey":preview.json()["previewKey"]})
        assert created.status_code == 200, created.text
        assert meta(a)["objectCount"]==2
        assert meta(a)["dirty"]
        assert meta(b)["objectCount"]==1
        assert not meta(b)["dirty"]
        assert client.get("/api/export/map",headers=h(b),
                          params={"documentToken":ma["documentToken"]}).status_code==409
        def export(key, token):
            result=client.get("/api/export/map",headers=h(key),params={"documentToken":token})
            assert result.status_code==200, result.text
            return result.content
        assert export(b,mb["documentToken"])==source_b
        # The server won't close a dirty document without explicit consent.
        assert client.delete("/api/documents/"+a,headers=auth).status_code==409
        undo = client.post("/api/edit/undo",headers=h(a),json={
            "documentToken":ma["documentToken"],"revision":created.json()["revision"]})
        assert undo.status_code==200, undo.text
        assert export(a,ma["documentToken"])==source_a
        assert export(b,mb["documentToken"])==source_b
        assert client.delete("/api/documents/"+a,headers=auth).status_code==200
        assert client.get("/api/map",headers=h(a)).status_code==404
        assert meta(b)["name"]=="second.MAP"


def test_tab_host_security_limit_and_single_open():
    app=create_app(multi_document=True)
    with TestClient(app) as client:
        auth={"X-GeoStudio-Token":app.state.api_token}
        host=client.get("/")
        assert "tab-list" in host.text
        assert "frame-src 'self'" in host.headers["content-security-policy"]
        assert host.headers["x-frame-options"]=="DENY"
        assert client.get("/api/documents").status_code==403
        initial=client.get("/api/documents",headers=auth).json()["documents"][0]
        editor=client.get("/document/"+initial)
        assert editor.status_code==200
        assert initial in editor.text
        assert editor.headers["x-frame-options"]=="SAMEORIGIN"
        assert "frame-ancestors 'self'" in editor.headers["content-security-policy"]
        assert 'id="btn-open"' in editor.text
        assert 'id="btn-open-direct"' not in editor.text
        assert 'id="map-picker-retry"' in editor.text
        assert client.get("/api/map",headers=auth).status_code==400
        for _ in range(MAX_DOCUMENTS-1):
            assert client.post("/api/documents",headers=auth).status_code==201
        assert client.post("/api/documents",headers=auth).status_code==409
        assert client.get("/document/not-a-tab").status_code==404


def test_native_bridge_pickers_and_exports_are_scoped(tmp_path, monkeypatch):
    app=create_app(multi_document=True)
    registry=app.state.documents
    a,b=registry.initial_id,registry.create()
    pa,pb=tmp_path/"first.MAP",tmp_path/"second.MAP"
    pa.write_bytes(_map("A",0))
    pb.write_bytes(_map("B",100))
    from geostudio.web_app.native_picker import NativeMapPicker
    paths=iter([str(pa),str(pb)])
    monkeypatch.setattr(NativeMapPicker,"_choose_path",lambda self:next(paths))
    # Avoid writing real user preferences during the test.
    registry.get(a).native._settings=tmp_path/"preferences.json"
    registry.get(b).native._settings=tmp_path/"preferences.json"
    bridge=DocumentNativeBridge(registry)
    assert bridge.document_call(a,"open_map",[])["metadata"]["name"]=="first.MAP"
    assert bridge.document_call(b,"open_map",[])["metadata"]["name"]=="second.MAP"
    assert registry.get(a).native._source_path==pa.resolve()
    assert registry.get(b).native._source_path==pb.resolve()
    assert registry.get(a).tile_exports is not registry.get(b).tile_exports
    with pytest.raises(ValueError):
        bridge.document_call(a,"_choose_path",[])
    registry.close(a)
    with pytest.raises(KeyError):
        bridge.document_call(a,"open_map",[])
    assert registry.get(b).workspace.metadata()["name"]=="second.MAP"


def test_editor_fetch_and_host_keep_alive_contract():
    root=Path(__file__).resolve().parents[1]/"geostudio"/"web_app"/"static"
    editor=(root/"map.js").read_text(encoding="utf-8")
    host=(root/"tabs.js").read_text(encoding="utf-8")
    css=(root/"tabs.css").read_text(encoding="utf-8")
    assert 'headers.set("X-GeoStudio-Document",documentId)' in editor
    assert "bridge.document_call(documentId,name,args)" in editor
    assert "host().openFileInNew(file)" in editor
    assert "window.GeoStudioDocument" in editor
    assert "frame.inert=!selected" in host
    assert "tab.frame.remove()" in host
    assert "visibility:hidden" in css and "visibility:visible" in css
