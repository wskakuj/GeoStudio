from dataclasses import replace
from datetime import datetime, timezone
import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from geostudio.web_app import firebase_auth as auth
from geostudio.web_app.firebase_offline import verify_permit
from geostudio.web_app.firebase_vault import WindowsSessionVault

DEVICE = "a"*64
PROJECT = "test-geostudio"


def b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


@pytest.fixture
def signer():
    key = ec.generate_private_key(ec.SECP256R1())
    public = b64(key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))

    def sign(**changes):
        now = int(time.time())
        data = {"v": 1, "project": PROJECT, "uid": "tester", "device": DEVICE,
                "email": "tester@example.invalid", "iat": now,
                "exp": now + 72*3600, "accountExp": None,
                "deviceLimit": 2, "deviceCount": 1}
        data.update(changes)
        raw = json.dumps(data, separators=(",", ":")).encode()
        r, s = utils.decode_dss_signature(key.sign(raw, ec.ECDSA(hashes.SHA256())))
        return b64(raw) + "." + b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))

    return public, sign


def make_client(public, transport):
    config = auth.FirebaseConfig(PROJECT, "test_key_not_a_real_firebase_key",
                                 "https://example.invalid/lease", public)
    return auth.FirebaseClient(config, transport, machine_id=DEVICE)


def test_signed_permit_bounded_and_device_bound(signer):
    public, sign = signer
    now = int(time.time())
    token = sign(iat=now, exp=now+120)
    assert verify_permit(token, public, PROJECT, DEVICE, now).uid == "tester"
    for project, device, at, seen in (
            ("other-project", DEVICE, now, 0), (PROJECT, "b"*64, now, 0),
            (PROJECT, DEVICE, now+120, 0), (PROJECT, DEVICE, now, now+121)):
        with pytest.raises(ValueError):
            verify_permit(token, public, project, device, at, seen)
    for invalid in (
        sign(iat=now, exp=now+72*3600+1),
        sign(iat=now, exp=now+120, accountExp=now+100),
        sign(iat=now, exp=now+120, deviceCount=3),
    ):
        with pytest.raises(ValueError):
            verify_permit(invalid, public, PROJECT, DEVICE, now)
    payload, signature = token.split(".")
    raw = json.loads(base64.urlsafe_b64decode(payload+"="*(-len(payload)%4)))
    raw["exp"] += 1
    with pytest.raises(ValueError):
        verify_permit(b64(json.dumps(raw).encode())+"."+signature,
                      public, PROJECT, DEVICE, now)


def test_restore_only_on_network_failure_and_not_explicit_denial(signer):
    public, sign = signer
    token = sign()
    state = {"refreshToken":"refresh", "offlineLease":token, "lastSeen":time.time()}

    def unavailable(*_):
        raise auth.AuthNetwork("offline")
    client = make_client(public, unavailable)
    grant = client.restore(state)
    assert grant.offline
    assert grant.credentials.id_token == ""
    assert grant.credentials.uid == "tester"
    assert grant.offline_until is not None

    for error in (auth.AuthDenied("blocked"), auth.AuthUnavailable("bad config")):
        def rejected(*_):
            raise error
        with pytest.raises(type(error)):
            make_client(public, rejected).restore(state)


def test_online_issuer_is_optional_and_validates_the_signature(signer):
    public, sign = signer
    now = int(time.time())
    lease = sign(iat=now, exp=now+3600)
    calls = []

    def transport(method, url, body, headers):
        calls.append((method, url, headers))
        if "signInWithPassword" in url:
            return {"localId":"tester", "idToken":"id-token", "refreshToken":"refresh",
                    "expiresIn":"3600"}
        if url.endswith("/lease"):
            assert headers["Authorization"] == "Bearer id-token"
            assert headers["User-Agent"] == "GeoStudio-Offline/1.0"
            assert json.loads(body) == {"deviceId":DEVICE}
            return {"lease":lease}
        return {"fields":{"active":{"booleanValue":True}, "expiresAt":{"nullValue":None},
                          "deviceLimit":{"integerValue":"2"},
                          "devices":{"arrayValue":{"values":[{"stringValue":DEVICE}]}},
                          "offlineHours":{"integerValue":"72"}}}

    grant = make_client(public, transport).login("tester@example.invalid", "password")
    assert grant.offline_lease == lease and not grant.offline
    assert grant.offline_until == datetime.fromtimestamp(now+3600, timezone.utc)

    def signer_down(method, url, body, headers):
        if url.endswith("/lease"):
            raise auth.AuthUnavailable("signer down")
        return transport(method, url, body, headers)
    assert make_client(public, signer_down).login("tester@example.invalid", "password").offline_lease == ""


def test_offline_gate_reconnect_denial_clears_remembered_permit(tmp_path, signer):
    public, sign = signer
    now = int(time.time())
    wall, mono = [float(now)], [0.0]
    failure = [auth.AuthNetwork("offline")]
    def transport(*_):
        raise failure[0]
    client = make_client(public, transport)
    lease = sign(iat=now, exp=now+7200)
    offline = client.offline_grant("refresh", lease, now=wall[0])
    online = replace(offline, offline=False,
                     credentials=auth.Credentials("tester","id-token","refresh",3600,"tester@example.invalid"))
    vault = WindowsSessionVault(PROJECT, tmp_path/"session.bin",
                                crypt=lambda data,decrypt:data[::-1])
    gate = auth.AccessGate(client, online, vault, True,
                           clock=lambda:mono[0], wall_clock=lambda:wall[0])
    mono[0] += 880
    wall[0] += 880
    gate.tick()
    assert gate.status()["active"] and gate.status()["offline"]
    assert vault.load_state()["offlineLease"] == lease
    mono[0] += 30
    wall[0] += 30
    failure[0] = auth.AuthDenied("account blocked")
    gate.tick()
    assert not gate.status()["active"]
    assert gate.allows_native("save_map") and not gate.allows_native("open_map")
    assert vault.load_state() is None


def test_offline_gate_expires_monotonically_even_after_clock_rollback(signer):
    public, sign = signer
    now = int(time.time())
    wall, mono = [float(now)], [0.]
    def transport(*_):
        raise auth.AuthNetwork("offline")
    client = make_client(public, transport)
    grant = client.offline_grant("refresh", sign(iat=now,exp=now+60), now=now)
    gate = auth.AccessGate(client, grant, clock=lambda:mono[0], wall_clock=lambda:wall[0])
    assert gate.status()["active"]
    mono[0] += 61
    # Wall clock did not advance (for example it was set backwards).
    assert not gate.status()["active"]
    gate.tick()
    assert not gate.status()["active"]


def test_vault_accepts_old_session_and_retains_new_fields(tmp_path):
    vault = WindowsSessionVault(PROJECT,tmp_path/"session.bin",crypt=lambda data,decrypt:data[::-1])
    old = {"project":PROJECT,"refreshToken":"refresh"}
    vault.path.write_bytes(json.dumps(old).encode()[::-1])
    assert vault.load_state() == {"refreshToken":"refresh","offlineLease":"","lastSeen":0}
    vault.save("refresh",offline_lease="signed.permit",last_seen=1234)
    assert vault.load_state() == {"refreshToken":"refresh","offlineLease":"signed.permit","lastSeen":1234}
