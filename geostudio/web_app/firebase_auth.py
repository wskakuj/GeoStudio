"""Firebase end-user authentication and short-lived GeoStudio access grants.

All map processing remains local. This client never needs admin credentials.
Firebase Security Rules, not editable client fields, authorize the account.
"""
from __future__ import annotations

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


class AuthError(Exception):
    """Safe, user-facing message; never contains a token or a password."""


class AuthDenied(AuthError):
    pass


class AuthUnavailable(AuthError):
    pass


@dataclass(frozen=True, repr=False)
class FirebaseConfig:
    project_id: str
    api_key: str

    def __post_init__(self):
        if not (re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", self.project_id)
                and re.fullmatch(r"[A-Za-z0-9_-]{20,128}", self.api_key)):
            raise AuthError("Nie skonfigurowano projektu Firebase dla GeoStudio.")


def load_config() -> FirebaseConfig:
    project = firebase_settings.PROJECT_ID
    key = firebase_settings.WEB_API_KEY
    if not getattr(sys, "frozen", False):
        project = os.environ.get("GEOSTUDIO_FIREBASE_PROJECT_ID", project)
        key = os.environ.get("GEOSTUDIO_FIREBASE_WEB_API_KEY", key)
    return FirebaseConfig(project.strip(), key.strip())


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
            code = failure.get("error", {}).get("message", "").split(" : ", 1)[0]
        except (OSError, ValueError, AttributeError, TypeError):
            code = ""
        if code in {"OPERATION_NOT_ALLOWED", "API_KEY_INVALID",
                    "API_KEY_SERVICE_BLOCKED", "PROJECT_NOT_FOUND",
                    "CONFIGURATION_NOT_FOUND", "API_KEY_HTTP_REFERRER_BLOCKED"}:
            raise AuthUnavailable("Konfiguracja Firebase wymaga sprawdzenia przez administratora.") from None
        if code == "TOO_MANY_ATTEMPTS_TRY_LATER" or error.code == 429:
            raise AuthUnavailable("Za dużo prób logowania. Spróbuj ponownie później.") from None
        if error.code in (400, 401, 403, 404):
            raise AuthDenied("Nieprawidłowe dane lub brak aktywnego dostępu.") from None
        raise AuthUnavailable("Usługa logowania jest chwilowo niedostępna.") from None
    except (OSError, ValueError, UnicodeError):
        raise AuthUnavailable("Nie udało się połączyć z usługą logowania.") from None


@dataclass(frozen=True, repr=False)
class Credentials:
    uid: str
    id_token: str
    refresh_token: str
    ttl: int


@dataclass(frozen=True, repr=False)
class Grant:
    credentials: Credentials
    expires_at: datetime | None


class FirebaseClient:
    def __init__(self, config: FirebaseConfig, transport=_transport):
        self.config = config
        self._transport = transport

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
            return Credentials(uid, identity, token, ttl)
        except (KeyError, TypeError, ValueError, OverflowError):
            raise AuthDenied("Nieprawidłowa odpowiedź usługi logowania.") from None

    def _authorize(self, credentials):
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
        return Grant(credentials, expires)

    def login(self, email, password):
        if not isinstance(email, str) or not isinstance(password, str) or not email.strip() or not password:
            raise AuthDenied("Wpisz adres e-mail i hasło.")
        result = self._post("signInWithPassword", {
            "email": email.strip(), "password": password, "returnSecureToken": True,
        })
        credentials = self._credentials(result)
        try:
            return self._authorize(credentials)
        except AuthDenied:
            raise AuthDenied("Logowanie poprawne, ale konto nie ma aktywnego dostępu do GeoStudio.") from None

    def refresh(self, refresh_token):
        url = ("https://securetoken.googleapis.com/v1/token?"
               + urllib.parse.urlencode({"key": self.config.api_key}))
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token", "refresh_token": refresh_token,
        }).encode("ascii")
        result = self._transport("POST", url, body, {
            "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
        })
        return self._authorize(self._credentials(result, refresh=True))

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

    The gate is created only after an online authorization. A monotonic lease
    prevents a dead monitor from extending access indefinitely.
    """

    def __init__(self, client, grant, vault=None, remember=False, clock=time.monotonic):
        self._client = client
        self._vault = vault
        self._remember = remember
        self._clock = clock
        self._lock = threading.RLock()
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
                self._vault.save(self._grant.credentials.refresh_token)
            else:
                self._vault.clear()
            self._storage_warning = ""
        except (OSError, ValueError):
            self._storage_warning = "Nie udało się zmienić zapamiętanej sesji w Windows."

    def _activate(self, grant):
        now = self._clock()
        lease = min(900.0, max(0.0, grant.credentials.ttl - 5.0))
        if grant.expires_at is not None:
            lease = min(lease, max(0.0, (
                grant.expires_at - datetime.now(timezone.utc)).total_seconds()))
        self._grant = grant
        self._deadline = now + lease
        self._next_check = now + max(1.0, lease - min(20.0, lease / 4))
        self._reason = ""
        self._save()

    def status(self):
        with self._lock:
            active = (self._grant is not None and not self._reason
                      and self._clock() < self._deadline)
            reason = "" if active else (self._reason or RESTRICTED_MESSAGE)
            return {"enabled": True, "active": active, "message": reason,
                    "storageWarning": self._storage_warning,
                    "loggedOut": self._logged_out, "updatesDisabled": True}

    def allows_http(self, method, path):
        return self.status()["active"] or (method == "GET" and path in RECOVERY_HTTP)

    def allows_native(self, operation):
        return self.status()["active"] or operation in RECOVERY_NATIVE

    def tick(self):
        with self._lock:
            if self._grant is None or self._clock() < self._next_check:
                return
            previous = self._grant.credentials
            generation = self._generation
            self._next_check = float("inf")
        try:
            grant = self._client.refresh(previous.refresh_token)
            if grant.credentials.uid != previous.uid:
                raise AuthDenied("Sesja nie należy do zalogowanego konta.")
        except AuthDenied:
            with self._lock:
                if generation == self._generation:
                    self._grant = None
                    self._reason = RESTRICTED_MESSAGE
                    self._remember = False
                    self._save()
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
