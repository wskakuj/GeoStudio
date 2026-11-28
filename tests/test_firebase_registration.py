import base64
import json
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
        if payload["action"] == "invite_status":
            return {"pending":False,"unregistered":True}
        return {"ok":True,"active":True,"pending":False}
    def refresh(refresh_token):
        events.append(("refresh", refresh_token))
        return auth.Credentials("test-user", "fresh-user-token", "rotated-refresh", 3600, EMAIL)
    monkeypatch.setattr(client, "_post", post)
    monkeypatch.setattr(client, "_refresh_credentials", refresh)
    monkeypatch.setattr(firebase_admin_client, "call_admin", remote)
    return client, events


def test_registration_checks_code_before_firebase_account_creation(client):
    c, events = client
    session = c.begin_registration(EMAIL,PASSWORD,CODE)
    assert session.email_sent
    assert session.email == EMAIL and session.uid == "test-user"
    assert session.refresh_token == "refresh"
    assert PASSWORD not in repr(session.__dict__)
    assert CODE not in repr(session)
    assert "refresh" not in repr(session)
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


def test_finish_does_not_require_password_reentry_or_local_grant(client):
    c, events = client
    session = c.begin_registration(EMAIL,PASSWORD,CODE)
    events.clear()
    result = c.finish_registration(session)
    assert result["active"]
    assert events[0] == ("refresh","refresh")
    assert events[1] == ("worker",URL+"/registration","fresh-user-token",{"action":"invite_redeem","code":CODE})
    assert PASSWORD not in repr(events)
    assert session.refresh_token == "rotated-refresh"
    session.clear()
    assert not session.refresh_token and not session.code
    with pytest.raises(auth.AuthDenied):
        c.finish_registration(session)


def test_resend_uses_session_and_rechecks_code(client):
    c, events = client
    session = c.begin_registration(EMAIL,PASSWORD,CODE)
    events.clear()
    assert c.resend_registration(session).email_sent
    assert events == [
        ("refresh","refresh"),
        ("worker", URL+"/registration", "", {"action":"invite_check","code":CODE,"email":EMAIL}),
        ("firebase","sendOobCode",{"requestType":"VERIFY_EMAIL","idToken":"fresh-user-token"})
    ]


def test_resume_same_form_signs_in_after_existing_account(client,monkeypatch):
    c, events = client
    post = c._post
    def existing(op, payload):
        if op == "signUp":
            events.append(("firebase",op,payload))
            raise auth.AuthDenied("email exists")
        return post(op,payload)
    monkeypatch.setattr(c,"_post",existing)
    session = c.begin_registration(EMAIL,PASSWORD,CODE)
    assert session.email_sent
    assert events[1][1] == "signUp"
    assert events[2][1] == "signInWithPassword"
    assert events[3][3] == {"action":"invite_status"}
    assert events[4][1] == "sendOobCode"


def test_resume_cannot_replace_existing_entitlement(client,monkeypatch):
    c, events = client
    post = c._post
    def existing(op, payload):
        if op == "signUp":
            raise auth.AuthDenied("email exists")
        return post(op,payload)
    remote = firebase_admin_client.call_admin
    def existing_policy(url, identity, payload):
        if payload["action"] == "invite_status":
            return {"unregistered":False,"pending":False}
        return remote(url,identity,payload)
    monkeypatch.setattr(c,"_post",existing)
    monkeypatch.setattr(firebase_admin_client,"call_admin",existing_policy)
    with pytest.raises(auth.AuthDenied,match="już istnieje"):
        c.begin_registration(EMAIL,PASSWORD,CODE)
    assert not any(e[0]=="firebase" and e[1]=="sendOobCode" for e in events)


def test_failed_mail_still_opens_verification_step(client,monkeypatch):
    c, events = client
    post = c._post
    def fail_mail(op, payload):
        if op == "sendOobCode":
            raise auth.AuthUnavailable("temporary")
        return post(op,payload)
    monkeypatch.setattr(c,"_post",fail_mail)
    session = c.begin_registration(EMAIL,PASSWORD,CODE)
    assert not session.email_sent
    assert session.refresh_token == "refresh"
    monkeypatch.setattr(c,"_post",post)
    assert c.resend_registration(session).email_sent


def test_unverified_redemption_can_retry_with_rotated_refresh_token(client,monkeypatch):
    c, events = client
    session = c.begin_registration(EMAIL,PASSWORD,CODE)
    remote = firebase_admin_client.call_admin
    def unverified(*_):
        raise firebase_admin_client.AdminAPIError("email_unverified",403)
    monkeypatch.setattr(firebase_admin_client,"call_admin",unverified)
    with pytest.raises(auth.AuthError):
        c.finish_registration(session)
    assert session.refresh_token == "rotated-refresh"
    monkeypatch.setattr(firebase_admin_client,"call_admin",remote)
    assert c.finish_registration(session)["active"]
    assert ("refresh","rotated-refresh") in events


def test_registration_rejects_changed_uid_and_clears_session(client,monkeypatch):
    c, events = client
    session = c.begin_registration(EMAIL,PASSWORD,CODE)
    monkeypatch.setattr(c,"_refresh_credentials",
                        lambda _: auth.Credentials("other-user","id","refresh",3600))
    events.clear()
    with pytest.raises(auth.AuthDenied,match="zmieniła konto"):
        c.finish_registration(session)
    assert events == []
    assert not session.refresh_token and not session.code


def test_verified_hint_skips_redundant_mail_but_still_calls_worker(client,monkeypatch):
    c, events = client
    claim = base64.urlsafe_b64encode(json.dumps({"email_verified":True}).encode()).decode().rstrip("=")
    identity = "header."+claim+".signature"
    monkeypatch.setattr(c,"_post",lambda *args:{**CREDENTIALS,"idToken":identity})
    session = c.begin_registration(EMAIL,PASSWORD,CODE)
    assert session.email_verified and not session.email_sent
    assert c.finish_registration(session)["active"]
    assert events[-1][3]["action"] == "invite_redeem"


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
