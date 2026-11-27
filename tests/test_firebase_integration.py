from fastapi.testclient import TestClient

from geostudio.web_app.server import create_app
from geostudio.web_app.documents import DocumentNativeBridge


class Gate:
    active = False

    def status(self):
        return {"enabled": True, "active": self.active}

    def allows_http(self, method, path):
        return self.active or (method == "GET" and path in {"/api/documents", "/api/edit/status"})

    def allows_native(self, operation):
        return self.active or operation == "save_map"

    def logout(self):
        self.active = False
        return self.status()


def test_restricted_api_and_logout():
    gate = Gate()
    app = create_app(multi_document=True, access_gate=gate)
    with TestClient(app) as client:
        headers = {"X-GeoStudio-Token": app.state.api_token}
        assert client.get("/auth/status").status_code == 403
        assert client.get("/auth/status", headers=headers).json()["active"] is False
        assert client.post("/api/documents", headers=headers).status_code == 403
        assert client.get("/api/documents", headers=headers).status_code == 200
        gate.active = True
        assert client.post("/api/documents", headers=headers).status_code == 201
        assert client.post("/auth/logout", headers=headers).json()["active"] is False
        assert client.post("/api/documents", headers=headers).status_code == 403


def test_native_gate_and_updater():
    import pytest
    gate = Gate()
    app = create_app(multi_document=True, access_gate=gate)
    bridge = DocumentNativeBridge(app.state.documents, access_gate=gate)
    with pytest.raises(PermissionError):
        bridge.document_call(app.state.documents.initial_id, "open_map", [])
    assert not bridge.install_update()["started"]


def test_real_gate_preserves_map_and_native_save_after_logout(tmp_path, monkeypatch):
    from conftest import MapBuilder
    from geostudio.geomap import GeoMap
    from geostudio.web_app import native_picker
    from geostudio.web_app.firebase_auth import AccessGate, Credentials, Grant

    gate = AccessGate(None, Grant(Credentials("tester", "id", "refresh", 3600), None))
    app = create_app(multi_document=True, access_gate=gate)
    registry = app.state.documents
    document_id = registry.initial_id
    session = registry.get(document_id)
    session.native._settings = tmp_path / "preferences.json"
    target = tmp_path / "saved.MAP"
    monkeypatch.setattr(native_picker, "_ask_save_as", lambda *_: str(target))
    bridge = DocumentNativeBridge(registry, access_gate=gate)

    with TestClient(app) as client:
        headers = {"X-GeoStudio-Token": app.state.api_token,
                   "X-GeoStudio-Document": document_id}
        source = MapBuilder().object("5216", "TEST-1", {"A1": "before"}).build()
        opened = client.post("/api/map", content=source,
                             headers={**headers, "X-Map-Name": "test.MAP"})
        assert opened.status_code == 200
        meta = opened.json()
        changed = client.patch("/api/object/f0/fields", headers=headers, json={
            "changes": {"A1": "after"}, "documentToken": meta["documentToken"],
            "revision": meta["revision"]})
        assert changed.status_code == 200, changed.text
        assert session.workspace.editing_status()["dirty"]

        gate.logout()
        assert client.post("/api/map", content=source, headers=headers).status_code == 403
        assert client.patch("/api/object/f0/fields", headers=headers, json={}).status_code == 403
        assert client.get("/api/export/dxf", headers=headers).status_code == 403
        copy = client.get("/api/export/map", headers=headers,
                          params={"documentToken": meta["documentToken"]})
        assert copy.status_code == 200
        assert GeoMap(copy.content).by_id["TEST-1"].fields["A1"] == "after"
        saved = bridge.document_call(document_id, "save_map", [])
        assert not saved.get("cancelled")
        assert GeoMap(target.read_bytes()).by_id["TEST-1"].fields["A1"] == "after"


def test_diagnostic_server_cannot_open_or_read_maps():
    from geostudio.web_app.firebase_auth import DiagnosticGate
    app = create_app(multi_document=True, access_gate=DiagnosticGate())
    with TestClient(app) as client:
        headers = {"X-GeoStudio-Token": app.state.api_token}
        assert client.get("/").status_code == 200  # static packaging probe only
        assert client.get("/api/documents", headers=headers).status_code == 403
        assert client.post("/api/documents", headers=headers).status_code == 403
        assert not client.get("/auth/status", headers=headers).json()["active"]


def test_change_account_never_closes_existing_workspace(monkeypatch):
    from geostudio.web_app import documents
    from geostudio.web_app.firebase_auth import AccessGate, Credentials, Grant
    gate = AccessGate(None, Grant(Credentials("tester", "id", "refresh", 3600), None))
    app = create_app(multi_document=True, access_gate=gate)
    registry = app.state.documents
    bridge = DocumentNativeBridge(registry, access_gate=gate)
    calls = []
    monkeypatch.setattr(documents.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
    assert not bridge.change_account()["started"]
    assert calls == []
    gate.logout()
    assert bridge.change_account()["started"]
    assert calls[0][0][0][-1] == "--login"
    assert registry.get(registry.initial_id) is not None
