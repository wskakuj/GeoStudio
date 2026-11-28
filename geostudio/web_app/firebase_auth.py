"""Firebase end-user authentication and short-lived GeoStudio access grants.

All map processing remains local. This client never needs admin credentials.
Firebase Security Rules, not editable client fields, authorize the account.
"""
from __future__ import annotations

import base64
import json
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from . import firebase_settings
from .firebase_devices import device_id
from .firebase_offline import b64decode, verify_permit, CLOCK_TOLERANCE, OFFLINE_UNLIMITED


class AuthError(Exception):
    """Safe, user-facing message; never contains a token or a password."""


class AuthDenied(AuthError):
    pass


class AuthUnavailable(AuthError):
    pass


class AuthNetwork(AuthUnavailable):
    """Transport failure, not rejected authentication or a bad server config."""


class DeviceDenied(AuthDenied):
    pass


class AuthConflict(AuthUnavailable):
    pass


@dataclass(frozen=True, repr=False)
class FirebaseConfig:
    project_id: str
    api_key: str
    offline_url: str = ""
    offline_public_key: str = ""
    admin_url: str = ""

    def __post_init__(self):
        if not (re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", self.project_id)
                and re.fullmatch(r"[A-Za-z0-9_-]{20,128}", self.api_key)):
            raise AuthError("Nie skonfigurowano projektu Firebase dla GeoStudio.")
        if self.offline_url or self.offline_public_key:
            try:
                url = urllib.parse.urlsplit(self.offline_url)
                key = b64decode(self.offline_public_key)
                if (url.scheme != "https" or not url.hostname or url.username
                        or url.password or url.query or url.fragment or len(key) != 65 or key[0] != 4):
                    raise ValueError
            except ValueError:
                raise AuthError("Nieprawidłowa konfiguracja licencji offline.") from None

        if self.admin_url:
            try:
                url = urllib.parse.urlsplit(self.admin_url)
                if (url.scheme != "https" or not url.hostname
                        or not url.hostname.endswith(".workers.dev")
                        or url.port not in (None, 443) or url.username
                        or url.password or url.query or url.fragment
                        or url.path not in ("", "/")):
                    raise ValueError
            except ValueError:
                raise AuthError("Nieprawidłowy adres usługi administracyjnej.") from None


def require_full_config(config: FirebaseConfig) -> FirebaseConfig:
    """Official Windows builds require login, invitations and offline support."""
    if not (config.admin_url and config.offline_url and config.offline_public_key):
        raise AuthError("Brakuje konfiguracji rejestracji, administracji lub licencji offline.")
    from cryptography.hazmat.primitives.asymmetric import ec
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), b64decode(config.offline_public_key))
    except ValueError:
        raise AuthError("Nieprawidłowy klucz publiczny licencji offline.") from None
    return config


def load_config() -> FirebaseConfig:
    project = firebase_settings.PROJECT_ID
    key = firebase_settings.WEB_API_KEY
    url = firebase_settings.OFFLINE_URL
    public_key = firebase_settings.OFFLINE_PUBLIC_KEY
    admin_url = firebase_settings.ADMIN_URL
    if not getattr(sys, "frozen", False):
        project = os.environ.get("GEOSTUDIO_FIREBASE_PROJECT_ID", project)
        key = os.environ.get("GEOSTUDIO_FIREBASE_WEB_API_KEY", key)
        url = os.environ.get("GEOSTUDIO_OFFLINE_URL", url)
        public_key = os.environ.get("GEOSTUDIO_OFFLINE_PUBLIC_KEY", public_key)
        admin_url = os.environ.get("GEOSTUDIO_ADMIN_URL", admin_url)
    return FirebaseConfig(project.strip(), key.strip(), url.strip(), public_key.strip(), admin_url.strip())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _transport(method, url, body, headers):
    try:
        try:
            import certifi
            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            context = ssl.create_default_context()
        opener = urllib.request.build_opener(
            _NoRedirect(), urllib.request.HTTPSHandler(context=context))
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        with opener.open(request, timeout=8) as response:
            raw = response.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise ValueError("response too large")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("invalid response")
        return result
    except urllib.error.HTTPError as error:
        # Firebase uses 400 for invalid credentials and revoked refresh tokens;
        # Firestore uses 403/404 for denied or absent entitlements.
        try:
            failure = json.loads(error.read(65536))
            problem = failure.get("error", {})
            code = problem.get("message", "").split(" : ", 1)[0]
            status = problem.get("status", "")
        except (OSError, ValueError, AttributeError, TypeError):
            code = ""
            status = ""
        if method == "PATCH" and (error.code in (409, 412) or status in ("ABORTED", "FAILED_PRECONDITION")):
            raise AuthConflict("Lista komputerów zmieniła się. Ponawiam sprawdzenie.") from None
        if code in {"OPERATION_NOT_ALLOWED", "API_KEY_INVALID",
                    "API_KEY_SERVICE_BLOCKED", "PROJECT_NOT_FOUND",
                    "CONFIGURATION_NOT_FOUND", "API_KEY_HTTP_REFERRER_BLOCKED"}:
            raise AuthUnavailable("Konfiguracja Firebase wymaga sprawdzenia przez administratora.") from None
        if code == "TOO_MANY_ATTEMPTS_TRY_LATER" or error.code == 429:
            raise AuthUnavailable("Za dużo prób logowania. Spróbuj ponownie później.") from None
        if error.code in (400, 401, 403, 404):
            raise AuthDenied("Nieprawidłowe dane lub brak aktywnego dostępu.") from None
        raise AuthUnavailable("Usługa logowania jest chwilowo niedostępna.") from None
    except urllib.error.URLError as error:
        if isinstance(error.reason, ssl.SSLError):
            raise AuthUnavailable("Nie udało się zweryfikować bezpiecznego połączenia.") from None
        raise AuthNetwork("Brak połączenia z usługą logowania.") from None
    except ssl.SSLError:
        raise AuthUnavailable("Nie udało się zweryfikować bezpiecznego połączenia.") from None
    except OSError:
        raise AuthNetwork("Brak połączenia z usługą logowania.") from None
    except (ValueError, UnicodeError):
        raise AuthUnavailable("Nieprawidłowa odpowiedź usługi logowania.") from None


@dataclass(frozen=True, repr=False)
class Credentials:
    uid: str
    id_token: str
    refresh_token: str
    ttl: int
    email: str = ""


def _display_email(response, identity):
    # Display only: the token comes from Firebase over TLS, and Firestore
    # verifies it before granting access. Never authorize from decoded claims.
    try:
        payload = identity.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        email = claims.get("email", "")
    except (IndexError, ValueError, TypeError, AttributeError):
        email = response.get("email", "")
    if not isinstance(email, str) or len(email) > 320:
        return ""
    return "".join(ch for ch in email if ch.isprintable())


@dataclass(frozen=True, repr=False)
class Grant:
    credentials: Credentials
    expires_at: datetime | None
    device_limit: int = 0
    device_count: int = 0
    offline_lease: str = ""
    offline_until: datetime | None = None
    offline: bool = False
    offline_unlimited: bool = False


@dataclass(repr=False)
class RegistrationSession:
    """Short-lived in-memory state, never saved to the session vault."""
    email: str
    code: str
    uid: str
    refresh_token: str
    email_sent: bool = False
    email_verified: bool = False

    def clear(self):
        self.refresh_token = ""
        self.code = ""


class FirebaseClient:
    def __init__(self, config: FirebaseConfig, transport=_transport, machine_id=None):
        self.config = config
        self._transport = transport
        self._device_id = device_id(config.project_id) if machine_id is None else machine_id

    def _post(self, operation, payload):
        url = ("https://identitytoolkit.googleapis.com/v1/accounts:"
               + operation + "?" + urllib.parse.urlencode({"key": self.config.api_key}))
        return self._transport("POST", url, json.dumps(payload).encode("utf-8"), {
            "Content-Type": "application/json", "Accept": "application/json",
            "X-Firebase-Locale": "pl",
        })

    @staticmethod
    def _credentials(response, refresh=False):
        try:
            uid = response["user_id" if refresh else "localId"]
            identity = response["id_token" if refresh else "idToken"]
            token = response["refresh_token" if refresh else "refreshToken"]
            ttl = int(response["expires_in" if refresh else "expiresIn"])
            if (not isinstance(uid, str) or not re.fullmatch(r"[^/\x00-\x1f]{1,128}", uid)
                    or uid in (".", "..") or not 1 <= ttl <= 86400
                    or any(not isinstance(value, str) or not 1 <= len(value) <= 16384
                           for value in (identity, token))):
                raise ValueError
            return Credentials(uid, identity, token, ttl, _display_email(response, identity))
        except (KeyError, TypeError, ValueError, OverflowError):
            raise AuthDenied("Nieprawidłowa odpowiedź usługi logowania.") from None

    @staticmethod
    def _device_policy(fields):
        try:
            if "deviceLimit" not in fields:
                return 0, []
            raw = fields["deviceLimit"]["integerValue"]
            if not isinstance(raw, (str, int)) or isinstance(raw, bool):
                raise ValueError
            limit = int(raw)
            if not 0 <= limit <= 20:
                raise ValueError
            if limit == 0:
                return 0, []
            values = fields["devices"]["arrayValue"].get("values", [])
            devices = [value["stringValue"] for value in values]
            if (len(devices) != len(set(devices)) or len(devices) > limit
                    or any(not re.fullmatch(r"[a-f0-9]{64}", item) for item in devices)):
                raise ValueError
            return limit, devices
        except (KeyError, TypeError, ValueError, AttributeError):
            raise DeviceDenied("Nieprawidłowa konfiguracja limitu komputerów. Skontaktuj się z administratorem.") from None

    def _authorize(self, credentials):
        for _ in range(3):
            try:
                return self._authorize_once(credentials)
            except AuthConflict:
                continue
        raise AuthUnavailable("Nie udało się potwierdzić rejestracji komputera. Spróbuj ponownie.")

    def _authorize_once(self, credentials):
        url = ("https://firestore.googleapis.com/v1/projects/"
               + self.config.project_id + "/databases/(default)/documents/geostudio_access/"
               + urllib.parse.quote(credentials.uid, safe=""))
        data = self._transport("GET", url, None, {
            "Authorization": "Bearer " + credentials.id_token,
            "Accept": "application/json", "Cache-Control": "no-cache",
        })
        try:
            fields = data["fields"]
            if fields["active"]["booleanValue"] is not True:
                raise ValueError
            expiry = fields["expiresAt"]
            if "nullValue" in expiry and expiry["nullValue"] in (None, "NULL_VALUE"):
                expires = None
            else:
                value = expiry["timestampValue"]
                expires = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
                    raise ValueError
        except (KeyError, TypeError, ValueError, AttributeError):
            raise AuthDenied("Konto nie ma aktywnego dostępu do GeoStudio.") from None
        limit, devices = self._device_policy(fields)
        if limit:
            identifier = self._device_id
            if not re.fullmatch(r"[a-f0-9]{64}", identifier or ""):
                raise DeviceDenied("Nie udało się rozpoznać tego komputera.")
            if identifier not in devices:
                if len(devices) >= limit:
                    raise DeviceDenied(f"Limit komputerów ({len(devices)}/{limit}) został osiągnięty. Skontaktuj się z administratorem.")
                # Optimistic concurrency + rules: two simultaneous logins
                # cannot overwrite each other's registrations or exceed cap.
                update_time = data.get("updateTime")
                if not isinstance(update_time, str) or not update_time:
                    raise AuthUnavailable("Nie udało się odczytać wersji listy komputerów.")
                devices = [*devices, identifier]
                query = urllib.parse.urlencode({
                    "updateMask.fieldPaths": "devices",
                    "currentDocument.updateTime": update_time,
                })
                payload = {"fields": {"devices": {"arrayValue": {
                    "values": [{"stringValue": item} for item in devices]}}}}
                try:
                    self._transport("PATCH", url + "?" + query,
                                    json.dumps(payload).encode("utf-8"), {
                        "Authorization": "Bearer " + credentials.id_token,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    })
                except AuthDenied:
                    raise DeviceDenied("Nie można zarejestrować komputera. Sprawdź limit i reguły Firestore.") from None
        grant = Grant(credentials, expires, limit, len(devices))
        if (self.config.offline_url and re.fullmatch(r"[a-f0-9]{64}", self._device_id or "")
                and fields.get("offlineHours", {}).get("integerValue") in ("72", 72, "-1", OFFLINE_UNLIMITED)):
            grant = self._issue_offline(grant)
        return grant

    def _issue_offline(self, grant):
        # A missing signer must never disable valid ONLINE access.
        from dataclasses import replace
        try:
            response = self._transport("POST", self.config.offline_url,
                json.dumps({"deviceId": self._device_id}).encode("utf-8"), {
                    "Authorization": "Bearer " + grant.credentials.id_token,
                    "Content-Type": "application/json", "Accept": "application/json",
                    # workers.dev may reject the default Python urllib User-Agent.
                    "User-Agent": "GeoStudio-Offline/1.0",
                })
            token = response["lease"]
            permit = verify_permit(token, self.config.offline_public_key,
                                   self.config.project_id, self._device_id, time.time())
            if permit.uid != grant.credentials.uid:
                raise ValueError
            return replace(grant, offline_lease=token,
                           offline_until=datetime.fromtimestamp(permit.expires, timezone.utc)
                           if permit.expires is not None else None,
                           offline_unlimited=permit.unlimited)
        except (AuthError, ValueError, KeyError, TypeError):
            return grant

    def offline_grant(self, refresh_token, lease, last_seen=0, now=None):
        if not self.config.offline_public_key:
            raise AuthNetwork("Praca offline nie jest włączona.")
        try:
            permit = verify_permit(lease, self.config.offline_public_key,
                                   self.config.project_id, self._device_id,
                                   time.time() if now is None else now, last_seen)
        except ValueError:
            raise AuthNetwork("Brak ważnej licencji offline. Połącz się z internetem.") from None
        credentials = Credentials(permit.uid, "", refresh_token, 3600, permit.email)
        return Grant(credentials, permit.account_expires, permit.device_limit,
                     permit.device_count, lease,
                     datetime.fromtimestamp(permit.expires, timezone.utc)
                     if permit.expires is not None else None,
                     True, permit.unlimited)

    def _report_activity(self, grant, kind):
        # Best effort; telemetry can never block login or the editor.
        if not self.config.admin_url or not self._device_id or grant.offline:
            return
        from .firebase_admin_client import call_admin
        name = os.environ.get("COMPUTERNAME", "")
        name = "".join(c for c in name if c.isprintable())[:80]

        def send():
            try:
                call_admin(self.config.admin_url, grant.credentials.id_token,
                           {"action": "activity", "deviceId": self._device_id,
                            "name": name, "kind": kind})
            except AuthError:
                pass

        threading.Thread(target=send, daemon=True, name="GeoStudioActivity").start()

    def restore(self, state):
        try:
            return self.refresh(state["refreshToken"], activity_kind="start")
        except AuthNetwork:
            return self.offline_grant(state["refreshToken"], state.get("offlineLease", ""),
                                      state.get("lastSeen", 0))

    def _registration_call(self, action, *, code="", email="", identity=""):
        if not self.config.admin_url:
            raise AuthDenied("Rejestracja nie jest dostępna w tej wersji.")
        from .firebase_admin_client import call_admin
        payload = {"action": action}
        if action != "invite_status":
            payload["code"] = code
        if action == "invite_check":
            payload["email"] = email
        return call_admin(self.config.admin_url.rstrip("/") + "/registration", identity, payload)

    @staticmethod
    def _registration_input(email, password, code):
        if (not isinstance(email, str) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email.strip())
                or len(email.strip()) > 254 or not isinstance(password, str)
                or not 12 <= len(password) <= 128 or not isinstance(code, str)
                or not 1 <= len(code.strip()) <= 80):
            raise AuthDenied("Wpisz poprawny e-mail, hasło (12–128 znaków) i kod zaproszenia.")

    @staticmethod
    def _email_verified_hint(credentials):
        # Presentation only. The Worker verifies the actual Firebase account
        # and email_verified claim before writing any entitlement.
        try:
            return json.loads(b64decode(credentials.id_token.split(".")[1])).get("email_verified") is True
        except (ValueError, IndexError, AttributeError, TypeError):
            return False

    def begin_registration(self, email, password, code):
        self._registration_input(email, password, code)
        email = email.strip()
        code = code.strip()
        self._registration_call("invite_check", code=code, email=email)
        try:
            credentials = self._credentials(self._post("signUp", {
                "email": email, "password": password, "returnSecureToken": True,
            }))
        except AuthDenied:
            # One button also resumes a previously started registration.
            # Only successful Firebase sign-in can recover the session.
            try:
                credentials = self._credentials(self._post("signInWithPassword", {
                    "email": email, "password": password, "returnSecureToken": True,
                }))
            except AuthDenied:
                raise AuthDenied("Nie udało się utworzyć konta. Sprawdź dane. "
                                 "Jeśli masz już konto, zaloguj się lub zresetuj hasło.") from None
            state = self._registration_call("invite_status", identity=credentials.id_token)
            if state.get("unregistered") is not True:
                if state.get("pending"):
                    raise AuthDenied("Konto oczekuje na akceptację administratora.") from None
                raise AuthDenied("Konto już istnieje i ma przypisane uprawnienia. Wróć do logowania.") from None

        session = RegistrationSession(email, code, credentials.uid, credentials.refresh_token,
                                      email_verified=self._email_verified_hint(credentials))
        if not session.email_verified:
            try:
                self._post("sendOobCode", {"requestType": "VERIFY_EMAIL",
                                          "idToken": credentials.id_token})
                session.email_sent = True
            except AuthError:
                # The account already exists. Continue to verification with
                # a resend link instead of asking the user to enter data again.
                pass
        return session

    def _registration_credentials(self, session):
        if not isinstance(session, RegistrationSession) or not session.refresh_token or not session.code:
            raise AuthDenied("Sesja rejestracji wygasła. Wróć do formularza.")
        credentials = self._refresh_credentials(session.refresh_token)
        if credentials.uid != session.uid:
            session.clear()
            raise AuthDenied("Sesja rejestracji zmieniła konto. Rozpocznij ponownie.")
        # Keep rotated refresh tokens even when the subsequent redeem fails.
        session.refresh_token = credentials.refresh_token
        session.email_verified = self._email_verified_hint(credentials)
        return credentials

    def resend_registration(self, session):
        credentials = self._registration_credentials(session)
        if not session.email_verified:
            self._registration_call("invite_check", code=session.code, email=session.email)
            self._post("sendOobCode", {"requestType": "VERIFY_EMAIL",
                                      "idToken": credentials.id_token})
            session.email_sent = True
        return session

    def finish_registration(self, session):
        credentials = self._registration_credentials(session)
        # Verification and single-use redemption remain server-side.
        return self._registration_call("invite_redeem", code=session.code,
                                       identity=credentials.id_token)

    def login(self, email, password):
        if not isinstance(email, str) or not isinstance(password, str) or not email.strip() or not password:
            raise AuthDenied("Wpisz adres e-mail i hasło.")
        result = self._post("signInWithPassword", {
            "email": email.strip(), "password": password, "returnSecureToken": True,
        })
        credentials = self._credentials(result)
        try:
            grant = self._authorize(credentials)
            self._report_activity(grant, "login")
            return grant
        except DeviceDenied:
            raise
        except AuthDenied:
            if self.config.admin_url:
                try:
                    state = self._registration_call("invite_status", identity=credentials.id_token)
                except AuthError:
                    state = {}
                if state.get("pending"):
                    raise AuthDenied("Konto oczekuje na akceptację administratora.") from None
                if state.get("unregistered"):
                    raise AuthDenied("Brak dostępu. Jeśli rozpocząłeś rejestrację, "
                                     "potwierdź e-mail i zakończ ją kodem zaproszenia.") from None
            raise AuthDenied("Logowanie poprawne, ale konto nie ma aktywnego dostępu do GeoStudio.") from None

    def _refresh_credentials(self, refresh_token):
        url = ("https://securetoken.googleapis.com/v1/token?"
               + urllib.parse.urlencode({"key": self.config.api_key}))
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token", "refresh_token": refresh_token,
        }).encode("ascii")
        result = self._transport("POST", url, body, {
            "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
        })
        return self._credentials(result, refresh=True)

    def refresh(self, refresh_token, *, activity_kind="heartbeat"):
        grant = self._authorize(self._refresh_credentials(refresh_token))
        self._report_activity(grant, activity_kind)
        return grant

    def reset_password(self, email):
        if not isinstance(email, str) or not email.strip() or "@" not in email:
            raise AuthDenied("Wpisz adres e-mail.")
        try:
            self._post("sendOobCode", {"requestType": "PASSWORD_RESET", "email": email.strip()})
        except AuthDenied:
            # Do not expose whether an address exists in the account database.
            pass


# Exact allowlist: finish an already opened MAP, not open a new project,
# modify geometry, generate new exports, or bypass a revoked entitlement.
RECOVERY_HTTP = frozenset({
    "/api/documents", "/api/map", "/api/edit/status", "/api/viewport",
    "/api/appearance", "/api/export/map", "/api/export/package",
    "/api/cartography/status", "/api/cartography/catalog",
    "/api/cartography/outline", "/api/cartography/fills", "/api/labels/settings",
})
RECOVERY_NATIVE = frozenset({
    "save_recovery", "save_map", "save_over_source", "save_base_map", "save_baked_map",
})
RESTRICTED_MESSAGE = "Brak aktywnego dostępu. Zapisz otwarte mapy i uruchom program ponownie."


class AccessGate:
    """Process-local session; recheck every 15 min and fail into save-only mode.

    The gate is created after online authorization or a verified, signed
    offline permit. A monotonic lease never extends the signed expiry.
    """

    def __init__(self, client, grant, vault=None, remember=False, clock=time.monotonic,
                 wall_clock=time.time, last_seen=0):
        self._client = client
        self._vault = vault
        self._remember = remember
        self._clock = clock
        self._wall_clock = wall_clock
        self._last_seen = max(last_seen, wall_clock()) if grant.offline else wall_clock()
        self._lock = threading.RLock()
        self._refresh_lock = threading.Lock()
        self._generation = 0
        self._logged_out = False
        self._grant = None
        self._reason = ""
        self._storage_warning = ""
        self._deadline = 0.0
        self._next_check = float("inf")
        self._activate(grant)

    def _save(self):
        if self._vault is None:
            return
        try:
            if self._remember and self._grant is not None:
                self._vault.save(self._grant.credentials.refresh_token,
                                 offline_lease=self._grant.offline_lease,
                                 last_seen=self._last_seen)
            else:
                self._vault.clear()
            self._storage_warning = ""
        except (OSError, ValueError):
            self._storage_warning = "Nie udało się zmienić zapamiętanej sesji w Windows."

    def _activate(self, grant):
        now = self._clock()
        wall = self._wall_clock()
        if grant.offline:
            lease = (float("inf") if grant.offline_unlimited and grant.offline_until is None
                     else max(0.0, grant.offline_until.timestamp() - wall)
                     if grant.offline_until is not None else 0.0)
            if self._grant is not None and self._grant.offline:
                lease = min(lease, max(0.0, self._deadline - now))
            self._last_seen = max(self._last_seen, wall)
        else:
            lease = min(900.0, max(0.0, grant.credentials.ttl - 5.0))
            self._last_seen = wall
        if grant.expires_at is not None:
            lease = min(lease, max(0.0, grant.expires_at.timestamp() - wall))
        self._grant = grant
        self._email = grant.credentials.email
        self._expires_at = grant.expires_at
        self._device_limit = grant.device_limit
        self._device_count = grant.device_count
        self._deadline = now + lease
        self._next_check = now + (min(30.0, max(1.0, lease)) if grant.offline
                                  else max(1.0, lease - min(20.0, lease / 4)))
        self._reason = ""
        self._save()

    def _admin_hint(self):
        # Presentation only. The Worker authenticates and checks the owner UID
        # and current admin claim independently for every privileged request.
        if self._grant is None or self._grant.offline:
            return False
        config = getattr(self._client, "config", None)
        if not getattr(config, "admin_url", ""):
            return False
        try:
            claims = json.loads(b64decode(self._grant.credentials.id_token.split(".")[1]))
            return claims.get("admin") is True
        except (ValueError, IndexError, AttributeError, TypeError):
            return False

    def admin_request(self, payload):
        from .firebase_admin_client import call_admin
        with self._lock:
            if not self.status()["admin"]:
                raise AuthDenied("Panel administratora jest dostępny wyłącznie online dla administratora.")
            generation = self._generation
            identity = self._grant.credentials.id_token
            url = self._client.config.admin_url
        result = call_admin(url, identity, payload)
        with self._lock:
            if generation != self._generation or not self.status()["admin"]:
                raise AuthDenied("Sesja administratora zakończyła się.")
        return result

    def refresh_now(self):
        checked = self.tick(force=True)
        return {**self.status(), "refreshBusy": not checked}

    def status(self):
        with self._lock:
            active = (self._grant is not None and not self._reason
                      and self._clock() < self._deadline)
            offline = bool(self._grant and self._grant.offline)
            until = self._grant.offline_until if self._grant else None
            unlimited = bool(self._grant and self._grant.offline_unlimited)
            if offline and ((until is None and not unlimited)
                            or (until is not None and self._wall_clock() >= until.timestamp())
                            or self._wall_clock() < self._last_seen - CLOCK_TOLERANCE):
                active = False
            reason = "" if active else (self._reason or RESTRICTED_MESSAGE)
            return {"enabled": True, "active": active, "message": reason,
                    "storageWarning": self._storage_warning,
                    "loggedOut": self._logged_out, "updatesDisabled": True,
                    "email": self._email,
                    "expiresAt": self._expires_at.isoformat() if self._expires_at else None,
                    "deviceLimit": self._device_limit,
                    "deviceCount": self._device_count,
                    "deviceId": getattr(self._client, "_device_id", "")[:12],
                    "offline": offline and active,
                    "admin": active and not offline and self._admin_hint(),
                    "canRefresh": self._grant is not None and not self._logged_out,
                    "offlineUnlimited": active and unlimited,
                    "offlineUntil": until.isoformat() if until else None}

    def allows_http(self, method, path):
        return self.status()["active"] or (method == "GET" and path in RECOVERY_HTTP)

    def allows_native(self, operation):
        return self.status()["active"] or operation in RECOVERY_NATIVE

    def tick(self, force=False):
        if not self._refresh_lock.acquire(blocking=False):
            return False
        try:
            self._tick(force)
            return True
        finally:
            self._refresh_lock.release()

    def _tick(self, force=False):
        with self._lock:
            if self._grant is None or (not force and self._clock() < self._next_check):
                return
            previous_grant = self._grant
            previous = previous_grant.credentials
            generation = self._generation
            self._next_check = float("inf")
        try:
            grant = self._client.refresh(previous.refresh_token)
            if grant.credentials.uid != previous.uid:
                raise AuthDenied("Sesja nie należy do zalogowanego konta.")
        except AuthDenied as error:
            with self._lock:
                if generation == self._generation:
                    self._grant = None
                    self._email = ""
                    self._expires_at = None
                    self._reason = str(error) + " Zapisz otwarte mapy i uruchom program ponownie."
                    self._remember = False
                    self._save()
            return
        except AuthNetwork:
            with self._lock:
                if generation != self._generation:
                    return
                try:
                    grant = self._client.offline_grant(
                        previous.refresh_token, previous_grant.offline_lease,
                        self._last_seen, self._wall_clock())
                    if grant.credentials.uid != previous.uid:
                        raise AuthNetwork("Licencja nie należy do konta.")
                except AuthNetwork:
                    self._reason = ("Brak połączenia i ważnej licencji offline. "
                                    "Zapisz otwarte mapy; ponawiamy sprawdzenie.")
                    self._next_check = self._clock() + 30
                    return
                self._activate(grant)
            return
        except AuthUnavailable:
            with self._lock:
                if generation == self._generation:
                    self._reason = ("Nie można potwierdzić dostępu przez internet. "
                                    "Możesz zapisać otwarte mapy; ponawiamy sprawdzenie.")
                    self._next_check = self._clock() + 30
            return
        with self._lock:
            if generation == self._generation:
                self._activate(grant)

    def run(self, stop):
        while not stop.wait(1):
            self.tick()

    def logout(self):
        with self._lock:
            self._generation += 1
            self._logged_out = True
            self._email = ""
            self._expires_at = None
            self._grant = None
            self._remember = False
            self._reason = "Wylogowano. Zapisz otwarte mapy i uruchom program ponownie."
            self._save()
            return self.status()


class DiagnosticGate:
    """Only for the short-lived packaged smoke test; never grants MAP access."""

    def status(self):
        return {"enabled": True, "active": False, "message": "Test diagnostyczny.",
                "updatesDisabled": True}

    def allows_http(self, method, path):
        return False

    def allows_native(self, operation):
        return False

    def logout(self):
        return self.status()
