import json
from datetime import datetime, timedelta, timezone

import pytest

from geostudio.web_app import firebase_auth as auth
from geostudio.web_app.firebase_vault import WindowsSessionVault


CONFIG = auth.FirebaseConfig("test-geostudio", "test_key_not_a_real_firebase_key")


def response(*, uid="user-1", refresh=False):
    if refresh:
        return {"user_id": uid, "id_token": "id-new", "refresh_token": "refresh-new",
                "expires_in": "3600"}
    return {"localId": uid, "idToken": "id", "refreshToken": "refresh",
            "expiresIn": "3600"}


def entitlement(active=True, expires=None):
    value = {"nullValue": None} if expires is None else {"timestampValue": expires}
    return {"fields": {"active": {"booleanValue": active}, "expiresAt": value}}


class Transport:
    def __init__(self, access=None):
        self.access = entitlement() if access is None else access
        self.calls = []
        self.failure = None

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url, body, headers))
        if self.failure:
            raise self.failure
        if "signInWithPassword" in url:
            return response()
        if "securetoken.googleapis.com" in url:
            return response(refresh=True)
        if "sendOobCode" in url:
            return {}
        return self.access


def test_login_checks_entitlement_with_user_token():
    transport = Transport()
    client = auth.FirebaseClient(CONFIG, transport)
    grant = client.login("tester@example.invalid", "test-password")
    assert grant.credentials.uid == "user-1"
    assert grant.expires_at is None
    assert len(transport.calls) == 2
    assert json.loads(transport.calls[0][2])["returnSecureToken"] is True
    assert transport.calls[1][1].endswith("/documents/geostudio_access/user-1")
    assert transport.calls[1][3]["Authorization"] == "Bearer id"


@pytest.mark.parametrize("access", [
    entitlement(False), {},
    {"fields": {"active": {"booleanValue": True}}},
    entitlement(True, "2000-01-01T00:00:00Z"),
    entitlement(True, "invalid"),
])
def test_unapproved_or_expired_accounts_do_not_get_grant(access):
    with pytest.raises(auth.AuthDenied):
        auth.FirebaseClient(CONFIG, Transport(access)).login("a@b", "password")


def test_future_expiry_and_refresh():
    expiry = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    transport = Transport(entitlement(True, expiry))
    client = auth.FirebaseClient(CONFIG, transport)
    grant = client.refresh("refresh-old")
    assert grant.credentials.refresh_token == "refresh-new"
    assert grant.expires_at.isoformat() == expiry
    assert b"grant_type=refresh_token" in transport.calls[0][2]


def test_gate_rechecks_and_failures_preserve_save_paths():
    transport = Transport()
    client = auth.FirebaseClient(CONFIG, transport)
    now = [0.0]
    gate = auth.AccessGate(client, client.login("a@b", "password"), clock=lambda: now[0])
    assert gate.allows_http("POST", "/api/map")
    now[0] = 880
    transport.failure = auth.AuthUnavailable("offline")
    gate.tick()
    assert not gate.status()["active"]
    assert not gate.allows_http("POST", "/api/map")
    assert not gate.allows_http("GET", "/api/export/dxf")
    assert gate.allows_http("GET", "/api/export/map")
    assert gate.allows_native("save_map")
    assert not gate.allows_native("open_map")
    now[0] += 30
    transport.failure = None
    gate.tick()
    assert gate.status()["active"]
    now[0] += 880
    transport.access = entitlement(False)
    gate.tick()
    assert not gate.status()["active"]
    now[0] += 1000
    transport.access = entitlement()
    gate.tick()
    assert not gate.status()["active"]  # explicit denial needs fresh login


def test_lease_expires_even_if_monitor_stops():
    client = auth.FirebaseClient(CONFIG, Transport())
    now = [0]
    gate = auth.AccessGate(client, client.login("a@b", "password"), clock=lambda: now[0])
    now[0] = 901
    assert not gate.allows_http("POST", "/api/objects/apply")


def test_logout_clears_vault(tmp_path):
    # Test the persistence plumbing with a fake transport only. Production
    # always uses DPAPI; this is not a fallback encryption scheme.
    vault = WindowsSessionVault(CONFIG.project_id, tmp_path / "session.bin",
                                crypt=lambda data, decrypt: data[::-1])
    client = auth.FirebaseClient(CONFIG, Transport())
    gate = auth.AccessGate(client, client.login("a@b", "password"), vault, True)
    assert vault.load() == "refresh"
    assert b"refresh" not in vault.path.read_bytes()
    assert not gate.logout()["active"]
    assert not vault.path.exists()


def test_no_frozen_environment_override(monkeypatch):
    monkeypatch.setattr(auth.sys, "frozen", True, raising=False)
    monkeypatch.setenv("GEOSTUDIO_FIREBASE_PROJECT_ID", CONFIG.project_id)
    monkeypatch.setenv("GEOSTUDIO_FIREBASE_WEB_API_KEY", CONFIG.api_key)
    with pytest.raises(auth.AuthError):
        auth.load_config()


def test_password_reset_does_not_expose_unknown_email():
    transport = Transport()
    transport.failure = auth.AuthDenied("not found")
    auth.FirebaseClient(CONFIG, transport).reset_password("a@b")


def test_diagnostic_gate_denies_all_api_and_native_access():
    gate = auth.DiagnosticGate()
    assert not gate.allows_http("GET", "/api/documents")
    assert not gate.allows_http("GET", "/api/export/map")
    assert not gate.allows_http("POST", "/api/map")
    assert not gate.allows_native("save_map")


@pytest.mark.skipif(auth.os.name != "nt", reason="Requires native Windows DPAPI")
def test_real_dpapi_roundtrip(tmp_path):
    vault = WindowsSessionVault(CONFIG.project_id, tmp_path / "session.bin")
    vault.save("synthetic-token")
    assert vault.load() == "synthetic-token"
    assert b"synthetic-token" not in vault.path.read_bytes()
    vault.clear()
    assert not vault.path.exists()


def test_build_config_validation_and_no_secret_repr():
    from tools.windows.configure_firebase import render_config
    namespace = {}
    exec(render_config(CONFIG.project_id, CONFIG.api_key), namespace)
    assert namespace["PROJECT_ID"] == CONFIG.project_id
    assert namespace["WEB_API_KEY"] == CONFIG.api_key
    assert CONFIG.api_key not in repr(CONFIG)
    with pytest.raises(auth.AuthError):
        render_config("", CONFIG.api_key)
    with pytest.raises(auth.AuthError):
        render_config(CONFIG.project_id, "not-valid")


def test_account_email_and_expiry_are_safe_status_fields():
    import base64
    email = "tester@example.invalid"
    payload = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    identity = "header." + payload + ".signature"
    data = response()
    data["idToken"] = identity
    credential = auth.FirebaseClient._credentials(data)
    expiry = datetime.now(timezone.utc) + timedelta(days=1)
    gate = auth.AccessGate(None, auth.Grant(credential, expiry))
    status = gate.status()
    assert status["email"] == email
    assert status["expiresAt"] == expiry.isoformat()
    assert identity not in json.dumps(status)
    assert credential.refresh_token not in json.dumps(status)
    assert gate.logout()["email"] == ""


def _device_entitlement(limit, devices):
    document = entitlement()
    document["updateTime"] = "2026-01-01T10:00:00Z"
    document["fields"].update({
        "deviceLimit": {"integerValue": str(limit)},
        "devices": {"arrayValue": {"values": [{"stringValue": d} for d in devices]}},
    })
    return document


def test_devices_append_with_precondition_and_existing_id_no_write():
    import urllib.parse
    a, b = "a"*64, "b"*64
    transport = Transport(_device_entitlement(2, [a]))
    client = auth.FirebaseClient(CONFIG, transport, machine_id=b)
    grant = client.login("tester@example.invalid", "test-password")
    assert (grant.device_limit, grant.device_count) == (2, 2)
    method, url, body, headers = transport.calls[-1]
    assert method == "PATCH"
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["updateMask.fieldPaths"] == ["devices"]
    assert query["currentDocument.updateTime"] == ["2026-01-01T10:00:00Z"]
    assert json.loads(body)["fields"]["devices"]["arrayValue"]["values"] == [
        {"stringValue": a}, {"stringValue": b}]
    assert headers["Authorization"] == "Bearer id"
    existing = Transport(_device_entitlement(2, [a, b]))
    assert auth.FirebaseClient(CONFIG, existing, machine_id=b).login("a@b", "p").device_count == 2
    assert not any(call[0] == "PATCH" for call in existing.calls)


def test_device_limit_blocks_third_computer_and_bad_policy():
    devices = ["a"*64, "b"*64]
    transport = Transport(_device_entitlement(2, devices))
    with pytest.raises(auth.DeviceDenied, match="Limit komputerów"):
        auth.FirebaseClient(CONFIG, transport, machine_id="c"*64).login("a@b", "p")
    assert not any(call[0] == "PATCH" for call in transport.calls)
    bad = Transport(_device_entitlement(1, devices))
    with pytest.raises(auth.DeviceDenied):
        auth.FirebaseClient(CONFIG, bad, machine_id="a"*64).login("a@b", "p")


def test_device_registration_rechecks_after_conflicting_write():
    a, b, c = "a"*64, "b"*64, "c"*64

    class RacingTransport(Transport):
        def __call__(self, method, url, body, headers):
            if method == "PATCH":
                self.access = _device_entitlement(2, [a, c])
                raise auth.AuthConflict("concurrent update")
            return super().__call__(method, url, body, headers)

    with pytest.raises(auth.DeviceDenied, match="Limit komputerów"):
        auth.FirebaseClient(CONFIG, RacingTransport(_device_entitlement(2, [a])),
                            machine_id=b).login("a@b", "p")
