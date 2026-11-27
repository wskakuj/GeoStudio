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
