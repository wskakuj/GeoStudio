from unittest.mock import Mock
import pytest
from geostudio.web_app import firebase_auth as auth
from geostudio.web_app import firebase_admin_client

PROJECT = "test-geostudio"
EMAIL = "test@example.invalid"
KEY = "test_key_not_a_real_firebase_key"
URL = "https://admin.example.workers.dev"
PASSWORD = "test-password-123"
CODE = "GS-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA"
CREDENTIALS = {"localId":"test-user","idToken":"user-token","refreshToken":"refresh","expiresIn":"3600"}


@pytest.fixture
def client(monkeypatch):
    client = auth.FirebaseClient(auth.FirebaseConfig(PROJECT, KEY, admin_url=URL), machine_id="a"*64)
    events = []
    def post(op, payload):
        events.append(("firebase", op, payload))
        return CREDENTIALS if op in ("signUp","signInWithPassword") else {}
    def remote(url, identity, payload):
        events.append(("worker", url, identity, payload))
        return {"ok":True,"active":True,"pending":False}
    monkeypatch.setattr(client, "_post", post)
    monkeypatch.setattr(firebase_admin_client, "call_admin", remote)
    return client, events


def test_registration_checks_code_before_firebase_account_creation(client):
    c, events = client
    assert c.begin_registration(EMAIL,PASSWORD,CODE)["ok"]
    assert events[0] == ("worker", URL+"/registration", "", {"action":"invite_check","code":CODE,"email":EMAIL})
    assert events[1][1] == "signUp"
    assert events[2] == ("firebase","sendOobCode",{"requestType":"VERIFY_EMAIL","idToken":"user-token"})
    assert PASSWORD not in repr(events[0])


def test_rejected_invitation_cannot_start_signup(client,monkeypatch):
    c, events = client
    def denied(*_):
        raise firebase_admin_client.AdminAPIError("invite_invalid",400)
    monkeypatch.setattr(firebase_admin_client,"call_admin",denied)
    with pytest.raises(auth.AuthError):
        c.begin_registration(EMAIL,PASSWORD,CODE)
    assert events == []


def test_finish_uses_verified_server_result_and_never_grants_local_session(client):
    c, events = client
    result = c.finish_registration(EMAIL,PASSWORD,CODE)
    assert result["active"]
    assert events[0][1] == "signInWithPassword"
    assert events[1] == ("worker",URL+"/registration","user-token",{"action":"invite_redeem","code":CODE})
    assert PASSWORD not in repr(events[1])


def test_resend_checks_code_and_authentication(client):
    c, events = client
    assert c.resend_registration(EMAIL,PASSWORD,CODE)["ok"]
    assert [e[1] for e in events] == [URL+"/registration","signInWithPassword","sendOobCode"]


def test_unapproved_registration_message_on_login(client,monkeypatch):
    c, events = client
    def reject(_):
        raise auth.AuthDenied("blocked")
    monkeypatch.setattr(c,"_authorize",reject)
    monkeypatch.setattr(firebase_admin_client,"call_admin",
                        lambda *_: {"pending":True,"unregistered":False})
    with pytest.raises(auth.AuthDenied,match="oczekuje"):
        c.login(EMAIL,PASSWORD)


def test_no_registration_with_missing_code_or_short_password(client):
    c,events = client
    for email,password,code in [(EMAIL,PASSWORD,""),(EMAIL,"short",CODE),("bad",PASSWORD,CODE)]:
        with pytest.raises(auth.AuthDenied):
            c.begin_registration(email,password,code)
    assert events == []
