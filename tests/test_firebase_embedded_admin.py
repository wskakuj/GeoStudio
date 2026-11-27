import base64
import json
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient

from geostudio.web_app import firebase_auth as auth
from geostudio.web_app.server import create_app
from tools.windows.configure_firebase import render_config

PROJECT = "test-geostudio"
KEY = "test_key_not_a_real_firebase_key"
URL = "https://admin.example.workers.dev"


def token(admin):
    claims = base64.urlsafe_b64encode(json.dumps({"admin": admin}).encode()).decode().rstrip("=")
    return "header." + claims + ".signature"


def gate(admin=True, offline=False, url=URL):
    from datetime import datetime, timezone, timedelta
    client = SimpleNamespace(config=auth.FirebaseConfig(PROJECT, KEY, admin_url=url))
    grant = auth.Grant(auth.Credentials("user", token(admin), "refresh", 3600), None,
                       offline=offline, offline_until=datetime.now(timezone.utc)+timedelta(hours=1)
                       if offline else None)
    return auth.AccessGate(client, grant)


@pytest.mark.parametrize("admin,offline,url,expected", [
    (True, False, URL, True), (False, False, URL, False),
    (True, True, URL, False), (True, False, "", False),
])
def test_admin_menu_hint_and_server_gate(admin, offline, url, expected):
    g = gate(admin, offline, url)
    assert g.status()["admin"] is expected
    assert "refresh" not in json.dumps(g.status()).replace("canRefresh", "")
    if not expected:
        with pytest.raises(auth.AuthDenied):
            g.admin_request({"action": "list"})


def test_local_admin_route_requires_token_and_online_admin(monkeypatch):
    from geostudio.web_app import firebase_admin_client
    calls = []
    def remote(url, identity, payload):
        calls.append((url, identity, payload))
        return {"rows": []}
    monkeypatch.setattr(firebase_admin_client, "call_admin", remote)
    g = gate()
    app = create_app(multi_document=True, access_gate=g)
    headers = {"X-GeoStudio-Token": app.state.api_token}
    with TestClient(app) as c:
        assert c.post("/auth/admin", json={"action": "list"}).status_code == 403
        assert c.post("/auth/admin", headers=headers, json={"action": "activity"}).status_code == 400
        r = c.post("/auth/admin", headers=headers, json={"action": "list"})
        assert r.status_code == 200 and r.json() == {"rows": []}
        assert r.headers["cache-control"] == "no-store"
        assert calls == [(URL, token(True), {"action": "list"})]
        g.logout()
        assert c.post("/auth/admin", headers=headers, json={"action": "list"}).status_code == 403
        assert len(calls) == 1


def test_regular_and_diagnostic_sessions_cannot_call_admin():
    for g in (gate(False), gate(True, True), auth.DiagnosticGate()):
        app = create_app(multi_document=True, access_gate=g)
        with TestClient(app) as c:
            r = c.post("/auth/admin", headers={"X-GeoStudio-Token": app.state.api_token},
                       json={"action": "list"})
            assert r.status_code == 403


def test_admin_worker_build_config_only_accepts_https_workers():
    namespace = {}
    exec(render_config(PROJECT, KEY, admin_url=URL), namespace)
    assert namespace["ADMIN_URL"] == URL
    for url in ("http://admin.example.workers.dev", "https://evil.example.com",
                "https://user:pass@admin.example.workers.dev", URL + "?key=x", URL + "/other"):
        with pytest.raises(auth.AuthError):
            auth.FirebaseConfig(PROJECT, KEY, admin_url=url)


def test_manual_refresh_does_not_wait_for_schedule():
    g = gate()
    def refresh(_):
        return auth.Grant(auth.Credentials("user", token(True), "refresh-new", 3600), None)
    g._client.refresh = refresh
    assert g.refresh_now()["active"]
    assert g._grant.credentials.refresh_token == "refresh-new"
    g.logout()
    assert not g.refresh_now()["active"]


def test_local_admin_route_accepts_invite_management_but_not_public_redemption(monkeypatch):
    from geostudio.web_app import firebase_admin_client
    calls = []
    def remote(url, identity, payload):
        calls.append(payload)
        return {"ok": True}
    monkeypatch.setattr(firebase_admin_client, "call_admin", remote)
    g = gate()
    app = create_app(multi_document=True, access_gate=g)
    headers = {"X-GeoStudio-Token": app.state.api_token}
    with TestClient(app) as c:
        for action in ("invites_list", "invite_create", "invite_revoke", "invite_history", "invite_settings"):
            assert c.post("/auth/admin", headers=headers, json={"action": action}).status_code == 200
        assert c.post("/auth/admin", headers=headers, json={"action": "invite_redeem"}).status_code == 400
        g.logout()
        assert c.post("/auth/admin", headers=headers, json={"action": "invites_list"}).status_code == 403
        assert len(calls) == 5
