"""Safe HTTPS bridge to the administrator Worker. No privileged keys in EXE."""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

from .firebase_auth import AuthError, _NoRedirect

MESSAGES = {
    "auth": "Sesja wygasła. Odśwież uprawnienia lub zaloguj się ponownie.",
    "invite_invalid": "Kod zaproszenia jest nieprawidłowy, wykorzystany, wygasł lub nie pasuje do adresu e-mail.",
    "registration_closed": "Rejestracja z zaproszeniem jest obecnie wyłączona.",
    "email_unverified": "Potwierdź adres e-mail przez link z wiadomości, a następnie zakończ rejestrację.",
    "already_registered": "Konto ma już przypisane uprawnienia. Zaproszenie nie zmienia istniejącego dostępu.",
    "denied": "Brak uprawnień administratora lub aktywnego dostępu.",
    "admin_config": "Sprawdź konfigurację administracyjnego Workera i IAM.",
    "invalid_input": "Nieprawidłowe dane. Sprawdź formularz.",
    "invalid_action": "Nieobsługiwana operacja.",
    "invalid_policy": "Nieprawidłowy dokument uprawnień. Sprawdź go w Firestore.",
    "device_limit": "Usuń nadmiarowe rejestracje przed obniżeniem limitu.",
    "owner_protected": "Nie można zablokować, usunąć ani wycofać urządzeń jedynego administratora.",
    "confirm_delete": "Wpisz dokładny adres e-mail konta.",
    "email_exists": "Konto z takim adresem już istnieje.",
    "not_found": "Nie znaleziono konta lub urządzenia.",
    "conflict": "Dane zmieniły się w międzyczasie. Odśwież panel i spróbuj ponownie.",
    "quota": "Osiągnięto limit usługi. Spróbuj później.",
    "invalid_google_request": "Firebase odrzucił operację. Sprawdź dane, konfigurację i limity.",
    "upstream": "Usługa Firebase lub IAM nie odpowiada poprawnie.",
    "unavailable": "Usługa administracyjna jest chwilowo niedostępna.",
}


class AdminAPIError(AuthError):
    def __init__(self, code="unavailable", status=503):
        self.code = code
        self.status = status if status in {400, 401, 403, 404, 409, 413, 429, 503} else 503
        super().__init__(MESSAGES.get(code, MESSAGES["unavailable"]))


def call_admin(url, id_token, payload):
    """Only fixed endpoint, no redirects, no secrets in errors or local logs."""
    try:
        try:
            import certifi
            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            context = ssl.create_default_context()
        opener = urllib.request.build_opener(
            _NoRedirect(), urllib.request.HTTPSHandler(context=context))
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if len(body) > 16384:
            raise AdminAPIError("invalid_input", 413)
        request = urllib.request.Request(url, data=body, method="POST", headers={
            **({"Authorization": "Bearer " + id_token} if id_token else {}),
            "Content-Type": "application/json", "Accept": "application/json",
            "User-Agent": "GeoStudio-Admin/1.0",
        })
        with opener.open(request, timeout=20) as response:
            raw = response.read(2*1024*1024 + 1)
        if len(raw) > 2*1024*1024:
            raise ValueError
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
        return data
    except urllib.error.HTTPError as error:
        code = "unavailable"
        try:
            candidate = json.loads(error.read(4096)).get("error")
            if isinstance(candidate, str) and candidate in MESSAGES:
                code = candidate
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        raise AdminAPIError(code, error.code) from None
    except AdminAPIError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError):
        raise AdminAPIError() from None
