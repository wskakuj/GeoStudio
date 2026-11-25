"""Read-only Geoportal WMS proxy for the localhost GeoStudio 2.0 canvas.

The browser never requests remote imagery directly (CORS, credentials).
Only approved official HTTPS GUGiK endpoints are accessible; arbitrary URLs,
redirects, oversized replies and non-image responses are rejected.
No MAP data or selected geometry is sent to the provider.
"""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future
from contextlib import contextmanager
from functools import lru_cache, wraps
from pathlib import Path
import hashlib
import http.client
import os
import ssl
import tempfile
import threading
import time
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import urlsplit
from math import isfinite

from geostudio.wms_service import WMSBounds, WMSLayerInfo, capabilities_url, getmap_url, parse_capabilities

PRESETS = {
    "standard": ("Ortofotomapa standardowa", "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardResolution"),
    "high": ("Ortofotomapa wysoka rozdzielczość", "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/HighResolution"),
    "kieg": ("Działki ewidencyjne i numery — GUGiK", "https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow"),
    # Kafelkowy WMTS (szybszy dla dużych kadrów).
    "standard_wmts": ("Geoportal — ortofotomapa standardowa (WMTS)",
                      "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMTS/StandardResolution"),
    "high_wmts": ("Geoportal — ortofotomapa wysoka (WMTS)",
                  "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMTS/HighResolution"),
    # WMS z osią czasu — ortofotomapa archiwalna.
    "standard_time": ("Geoportal — ortofotomapa archiwalna standardowa",
                      "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardResolutionTime"),
    "high_time": ("Geoportal — ortofotomapa archiwalna wysoka",
                  "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/HighResolutionTime"),
    # Własny serwer: adres podaje użytkownik, więc nie ma go w tabeli.
    "custom": ("Własny serwer WMS", ""),
}

# Presety kafelkowe obsługiwane przez WMTS, nie przez WMS GetMap.
WMTS_PRESETS = frozenset({"standard_wmts", "high_wmts"})
# Presety z osią czasu: wymagają parametru TIME (albo zostawiamy domyślny).
TIME_PRESETS = frozenset({"standard_time", "high_time"})
# An explicit user choice is mandatory; no inference from MAP coordinates.
SUPPORTED_EPSG = frozenset((2180, 2176, 2177, 2178, 2179))
KIEG_IMAGE_URL = "https://integracja02.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow"
KIEG_PARCELS = "dzialki,numery_dzialek"
PARCEL_LAYERS = (KIEG_PARCELS, "dzialki", "numery_dzialek")
MAX_WMS_BYTES = 15_000_000
REQUEST_TIMEOUT_SECONDS = 35.0


class _RequestBudgetExpired(RuntimeError):
    """The whole preview exhausted its budget, including every fallback."""


class _DownloadTimeout(RuntimeError):
    """One request timed out; a smaller preview may still fit the budget."""


class _TransportError(RuntimeError):
    """Changing image format cannot repair a failed network connection."""


class _RequestBudget:
    def __init__(self):
        self.deadline = time.monotonic() + REQUEST_TIMEOUT_SECONDS

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _RequestBudgetExpired(
                "Przekroczono czas pobierania podkładu (35 s). "
                "Spróbuj ponownie lub wybierz mniejszy obszar.")
        return remaining


_REQUEST_CONTEXT = threading.local()


@contextmanager
def _request_budget(budget=None):
    previous = getattr(_REQUEST_CONTEXT, "budget", None)
    budget = budget or previous or _RequestBudget()
    _REQUEST_CONTEXT.budget = budget
    try:
        budget.remaining()
        yield budget
    finally:
        _REQUEST_CONTEXT.budget = previous


def _bounded_request(function):
    @wraps(function)
    def bounded(*args, **kwargs):
        with _request_budget():
            return function(*args, **kwargs)
    return bounded


def _run_with_budget(budget, function, *args, **kwargs):
    # Thread-local contexts do not propagate into tile worker threads.
    with _request_budget(budget):
        return function(*args, **kwargs)


_INFLIGHT = {}
_INFLIGHT_LOCK = threading.Lock()


def _single_flight(key, load):
    """Concurrent requests for one image/catalogue share a single download."""
    with _INFLIGHT_LOCK:
        future = _INFLIGHT.get(key)
        owner = future is None
        if owner:
            future = Future()
            _INFLIGHT[key] = future
    if not owner:
        with _request_budget() as budget:
            try:
                return future.result(timeout=budget.remaining())
            except TimeoutError as exc:
                raise _RequestBudgetExpired(
                    "Przekroczono czas oczekiwania na podkład.") from exc
    try:
        result = load()
        future.set_result(result)
        return result
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        with _INFLIGHT_LOCK:
            if _INFLIGHT.get(key) is future:
                del _INFLIGHT[key]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Połączenia TLS per WĄTEK. Jeden wspólny HTTPSConnection dla wszystkich wątków
# nie jest bezpieczny: przy dwóch kafelkach pobieranych równolegle wątki
# wchodziły sobie na to samo gniazdo, co kończyło się zrywaniem żądania,
# błędnie odczytaną odpowiedzią albo zamknięciem połączenia drugiego wątku.
_CONNECTIONS = threading.local()


def _thread_pool() -> dict:
    pool = getattr(_CONNECTIONS, "pool", None)
    if pool is None:
        pool = {}
        _CONNECTIONS.pool = pool
    return pool


# Geoportal renderuje ortofoto długo — 15 s to za mało i kończyło się
# komunikatem o przekroczeniu czasu. GUGiK odpowiada szybko, więc ma krótszy
# limit (szybciej widać prawdziwy błąd).
HOST_TIMEOUTS = {
    "mapy.geoportal.gov.pl": 30,
    "integracja.gugik.gov.pl": 20,
    "integracja02.gugik.gov.pl": 20,
}


def _timeout_for(host: str) -> int:
    return HOST_TIMEOUTS.get(host, 20)


# Kontekst TLS: najpierw pełna weryfikacja z pakietem certifi (w Windows
# brakuje często CA dla Geoportalu), a przy błędzie certyfikatu — jedno
# ponowienie bez weryfikacji. Geoportal to publiczna usługa tylko do czytania,
# nie wysyłamy tam żadnych danych ani poświadczeń, a bez tego obejścia na
# niektórych komputerach podkłady w ogóle się nie wczytują.
_TLS_STRICT = None
_TLS_RELAXED = None
_TLS_WARNED = [False]


def _tls_contexts():
    global _TLS_STRICT, _TLS_RELAXED
    if _TLS_STRICT is None:
        import ssl
        context = ssl.create_default_context()
        try:                                    # certifi bywa w paczce
            import certifi
            context.load_verify_locations(certifi.where())
        except Exception:                       # noqa: BLE001
            pass
        _TLS_STRICT = context
    if _TLS_RELAXED is None:
        import ssl
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        _TLS_RELAXED = context
    return _TLS_STRICT, _TLS_RELAXED


def _connection(host: str, *, relaxed: bool = False) -> "http.client.HTTPSConnection":
    """Połączenie TLS przypisane do bieżącego wątku (keep-alive)."""
    pool = _thread_pool()
    key = (host, relaxed)
    conn = pool.get(key)
    if conn is None:
        strict, loose = _tls_contexts()
        conn = http.client.HTTPSConnection(host, timeout=_timeout_for(host),
                                           context=loose if relaxed else strict)
        pool[key] = conn
    return conn


def _drop_connection(host: str, *, relaxed: bool = False) -> None:
    pool = _thread_pool()
    for key in ((host, relaxed), host):
        conn = pool.pop(key, None)
        if conn is not None:
            try:
                conn.close()
            except Exception:                   # noqa: BLE001
                pass


OFFICIAL_HOSTS = frozenset({"mapy.geoportal.gov.pl",
                            "integracja.gugik.gov.pl",
                            "integracja02.gugik.gov.pl"})
# Adresy, pod które NIE wolno wysyłać żądań (ochrona przed SSRF).
_BLOCKED_HOSTS = frozenset({"localhost", "localhost.localdomain",
                            "metadata.google.internal", "instance-data"})
_PRIVATE_PREFIXES = ("10.", "127.", "169.254.", "192.168.", "0.", "100.64.",
                     "172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
                     "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
                     "172.26.", "172.27.", "172.28.", "172.29.", "172.30.",
                     "172.31.")


def validate_service_url(url: str) -> str:
    """Sprawdza adres własnego serwera WMS i zwraca go bez zmian.

    Dozwolony jest dowolny publiczny serwer HTTPS; blokujemy adresy lokalne
    i prywatne, żeby aplikacja nie mogła zostać użyta do skanowania sieci.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Podaj adres serwera WMS.")
    parsed = urlsplit(url.strip())
    if parsed.scheme != "https":
        raise ValueError("Adres serwera WMS musi zaczynać się od https://")
    if not parsed.hostname:
        raise ValueError("Adres serwera WMS jest nieprawidłowy.")
    if parsed.username or parsed.password:
        raise ValueError("Adres nie może zawierać loginu ani hasła.")
    host = parsed.hostname.lower()
    if host in _BLOCKED_HOSTS or host.startswith(_PRIVATE_PREFIXES):
        raise ValueError("Adresy lokalne i prywatne nie są dozwolone.")
    if host in {"::1", "[::1]"} or host.startswith("fd") or host.startswith("fe80"):
        raise ValueError("Adresy lokalne i prywatne nie są dozwolone.")
    return url.strip()


class _GatewayError(RuntimeError):
    """502/503/504 z bramki Geoportalu — warto ponowić po chwili."""


def _set_io_timeout(conn, host, budget, reply=None):
    timeout = min(_timeout_for(host), budget.remaining())
    conn.timeout = timeout
    sock = getattr(conn, "sock", None)
    if sock is None and reply is not None:
        # HTTPConnection detaches the socket when a response announces
        # Connection: close. Its body still owns that socket through fp.
        sock = getattr(getattr(getattr(reply, "fp", None), "raw", None),
                       "_sock", None)
    if sock is not None:
        sock.settimeout(timeout)


def _read_response(reply, conn, host, budget, max_bytes):
    # Refresh the remaining timeout between chunks, so a slowly streaming
    # response cannot restart a fresh 30-second budget for every chunk.
    read_chunk = getattr(reply, "read1", None)
    if read_chunk is None:
        _set_io_timeout(conn, host, budget, reply)
        content = reply.read(max_bytes + 1)
    else:
        chunks = []
        size = 0
        while size <= max_bytes:
            _set_io_timeout(conn, host, budget, reply)
            chunk = read_chunk(min(65536, max_bytes + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        content = b"".join(chunks)
    budget.remaining()
    if len(content) > max_bytes:
        raise ValueError("Odpowiedź WMS przekracza limit rozmiaru.")
    return content


@_bounded_request
def _download(url: str, max_bytes: int) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError("Adres usługi musi używać https://.")
    if parsed.port not in (None, 443):
        raise ValueError("Dozwolony jest wyłącznie port 443.")
    if parsed.hostname in OFFICIAL_HOSTS:
        pass
    else:
        validate_service_url(url)
    if parsed.username or parsed.password:
        raise ValueError("Nieprawidłowy adres usługi.")
    host = parsed.hostname
    path = parsed.path + ("?" + parsed.query if parsed.query else "")
    headers = {"User-Agent": "GeoStudio-2-WMS/12A",
               "Accept": "image/png, image/jpeg, application/xml, text/xml",
               "Connection": "keep-alive"}
    last: Exception | None = None
    budget = _REQUEST_CONTEXT.budget
    # One retry repairs a stale keep-alive connection or a transient gateway
    # error. A timeout must not repeat this URL four times before trying
    # four formats, four tiles, and two smaller images.
    relaxed = False
    for attempt in range(2):
        if attempt:
            time.sleep(min(0.25, budget.remaining()))
        budget.remaining()
        try:
            conn = _connection(host, relaxed=relaxed)
            _set_io_timeout(conn, host, budget)
            conn.request("GET", path, headers=headers)
            _set_io_timeout(conn, host, budget)
            reply = conn.getresponse()
            budget.remaining()
            if reply.status in (301, 302, 303, 307, 308):
                _drop_connection(host, relaxed=relaxed)
                raise ValueError("Usługa przekierowała na niezaufany adres.")
            if reply.status in (502, 503, 504):
                raise _GatewayError("Geoportal zwrócił błąd " + str(reply.status))
            if reply.status >= 400:
                _drop_connection(host, relaxed=relaxed)
                raise _TransportError("Serwer WMS zwrócił błąd " + str(reply.status) + ".")
            return _read_response(reply, conn, host, budget, max_bytes)
        except _RequestBudgetExpired:
            _drop_connection(host, relaxed=relaxed)
            raise
        except TimeoutError as exc:
            _drop_connection(host, relaxed=relaxed)
            budget.remaining()
            raise _DownloadTimeout(
                "Serwer nie zdążył przygotować obrazu podkładu.") from exc
        except ssl.SSLCertVerificationError as exc:
            # Na części komputerów brakuje CA dla Geoportalu. Jedno ponowienie
            # bez weryfikacji — usługa jest publiczna i tylko do czytania.
            last = exc
            _drop_connection(host, relaxed=relaxed)
            if relaxed:
                break
            relaxed = True
            _TLS_WARNED[0] = True
            continue
        except _GatewayError as exc:
            last = exc
            _drop_connection(host, relaxed=relaxed)
            continue
        except (http.client.HTTPException, OSError) as exc:
            # Zerwane połączenie keep-alive: nowe i ponowna próba.
            last = exc
            _drop_connection(host, relaxed=relaxed)
            continue
        except ValueError:
            _drop_connection(host, relaxed=relaxed)
            raise
    reason = type(last).__name__ if last else "nieznany błąd"
    if isinstance(last, _GatewayError):
        raise _TransportError(
            "Bramka Geoportalu odrzuciła żądanie (502/503). Spróbuj ponownie "
            "za chwilę — serwer bywa chwilowo niedostępny.") from last
    if isinstance(last, ssl.SSLCertVerificationError):
        raise _TransportError(
            "Nie udało się zweryfikować certyfikatu Geoportalu "
            "(SSLCertVerificationError). Sprawdź datę i godzinę w systemie "
            "oraz ustawienia antywirusa/proxy — program próbował też "
            "połączenia bez weryfikacji.") from last
    raise _TransportError(
        "Nie można pobrać danych WMS z Geoportalu (" + reason +
        "). Spróbuj ponownie za chwilę.") from last


_CACHE: "OrderedDict[tuple, bytes]" = OrderedDict()
_CACHE_BYTES = 0
_CACHE_LIMIT = 128 * 1024 * 1024
_CACHE_MAX_ENTRIES = 160
_CACHE_LOCK = threading.Lock()
_disk_puts_since_trim = [0]


def _cache_key(preset, layer, epsg, xmin, ymin, xmax, ymax, width, height):
    """Klucz cache z zapasem: przesunięcie o kilka pikseli trafia w ten sam wpis.

    Wcześniej klucz zawierał dokładny BBOX (co do centymetra), więc każde
    drgnięcie mapy dawało pudło. Teraz BBOX jest przycinany do siatki
    odpowiadającej ~2 pikselom obrazu, a rozmiar pozostaje w kluczu.
    """
    span_x = max(abs(xmax - xmin), 1e-9)
    span_y = max(abs(ymax - ymin), 1e-9)
    step_x = span_x / max(1, width) * 2.0
    step_y = span_y / max(1, height) * 2.0

    def snap(value, step):
        return round(round(value / step) * step, 6)

    # New namespace avoids reusing old, incorrectly assembled WMTS images.
    return ("wms-preview-v2", preset, layer, epsg,
            snap(xmin, step_x), snap(ymin, step_y),
            snap(xmax, step_x), snap(ymax, step_y),
            width, height)


def _disk_cache_dir() -> Path | None:
    """Katalog cache obrazów (poza repozytorium), albo None gdy brak dostępu."""
    if os.environ.get("GEOSTUDIO_WMS_DISK_CACHE") == "0":
        return None                     # testy: bez cache na dysku
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    base = Path(root) if root else Path.home() / ".cache"
    directory = base / "GeoStudio2" / "wms-cache"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return directory


def _disk_path(key) -> Path | None:
    directory = _disk_cache_dir()
    if directory is None:
        return None
    digest = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()
    return directory / (digest + ".img")


def _disk_get(key):
    path = _disk_path(key)
    if path is None:
        return None
    try:
        return path.read_bytes()
    except OSError:
        return None


def _disk_put(key, value: bytes) -> None:
    path = _disk_path(key)
    if path is None:
        return
    try:
        fd, temp = tempfile.mkstemp(prefix=".wms-", suffix=".tmp",
                                    dir=str(path.parent))
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except OSError:
        pass


def _cache_get(key):
    with _CACHE_LOCK:
        value = _CACHE.get(key)
        if value is not None:
            _CACHE.move_to_end(key)
            return value
    # Pamięć podręczna na dysku: te same kadry po restarcie programu.
    disk = _disk_get(key)
    if disk is not None:
        _cache_put(key, disk)
    return disk


def _cache_put(key, value: bytes) -> None:
    global _CACHE_BYTES
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE_BYTES -= len(_CACHE[key])
        _CACHE[key] = value
        _CACHE_BYTES += len(value)
        _CACHE.move_to_end(key)
        while (_CACHE and (_CACHE_BYTES > _CACHE_LIMIT or
                           len(_CACHE) > _CACHE_MAX_ENTRIES)):
            _, dropped = _CACHE.popitem(last=False)
            _CACHE_BYTES -= len(dropped)
    _disk_put(key, value)
    _disk_puts_since_trim[0] += 1
    if _disk_puts_since_trim[0] >= 50:
        _disk_puts_since_trim[0] = 0
        _disk_cache_trim()


def _disk_cache_trim(limit_bytes: int = 400 * 1024 * 1024) -> None:
    """Utrzymuje cache dyskowy w ryzach: najstarsze pliki lecą pierwsze."""
    directory = _disk_cache_dir()
    if directory is None:
        return
    try:
        files = sorted(((entry.stat().st_mtime, entry)
                        for entry in directory.glob("*.img")),
                       key=lambda item: item[0])
    except OSError:
        return
    total = sum(entry.stat().st_size for _mtime, entry in files
                if entry.exists())
    for _mtime, entry in files:
        if total <= limit_bytes:
            break
        try:
            total -= entry.stat().st_size
            entry.unlink()
        except OSError:
            continue


def cache_stats() -> dict:
    with _CACHE_LOCK:
        return {"entries": len(_CACHE), "bytes": _CACHE_BYTES}


def clear_cache() -> None:
    global _CACHE_BYTES
    with _CACHE_LOCK:
        _CACHE.clear()
        _CACHE_BYTES = 0
    # Capabilities to też cache — bez tego testy i zmiana serwera widziałyby
    # stary dokument XML.
    _clear_layer_cache()
    _wmts_capabilities_xml.cache_clear()
    _wmts_capabilities.cache_clear()
    _wmts_layer_info.cache_clear()
    _wmts_layers.cache_clear()
    _tile_cache_clear()


def _preset(name: str, url: str | None = None) -> str:
    if name not in PRESETS:
        raise ValueError("Nieznane źródło ortofotomapy.")
    if name == "custom":
        return validate_service_url(url or "")
    return PRESETS[name][1]


@_bounded_request
def layers_for(preset: str, url: str | None = None) -> tuple:
    if preset in WMTS_PRESETS:
        return _wmts_layers(preset)
    if preset == "custom":
        service_url = validate_service_url(url or "")
        return _single_flight(("capabilities", preset, service_url),
                              lambda: _custom_layers_for(service_url))
    return _single_flight(("capabilities", preset),
                          lambda: _layers_for_preset(preset))


@lru_cache(maxsize=32)
def _custom_layers_for(service_url: str) -> tuple:
    xml = _download(capabilities_url(service_url), 4_000_000)
    layers = parse_capabilities(xml)
    if not layers:
        raise ValueError("Serwer nie udostępnił nazwanych warstw WMS.")
    return layers


@lru_cache(maxsize=16)
def _layers_for_preset(preset: str) -> tuple:
    if preset == "kieg":
        # The published GetMap example provides these layers in PL-1992,
        # independently of availability of the capabilities catalogue.
        defaults = tuple(WMSLayerInfo(key, title, ("EPSG:2180",)) for key, title in (
            (KIEG_PARCELS, "Granice i numery działek"),
            ("dzialki", "Granice działek"), ("numery_dzialek", "Numery działek")))
        try:
            catalogue = parse_capabilities(_download(capabilities_url(_preset(preset)), 4_000_000))
        except _RequestBudgetExpired:
            raise
        except (RuntimeError, ValueError):
            catalogue = ()
        keys = {entry.name for entry in defaults}
        return defaults + tuple(entry for entry in catalogue if entry.name not in keys)
    xml = _download(capabilities_url(_preset(preset)), 4_000_000)
    layers = parse_capabilities(xml)
    if not layers:
        raise ValueError("Geoportal nie udostępnił nazwanych warstw WMS.")
    return layers


def _clear_layer_cache():
    _layers_for_preset.cache_clear()
    _custom_layers_for.cache_clear()


layers_for.cache_clear = _clear_layer_cache


# Dla GUGiK pokazujemy tylko jedną, używaną warstwę: granice i numery działek.
KIEG_KEEP = frozenset({KIEG_PARCELS})


def _wmts_capabilities_xml(preset: str) -> bytes:
    """Jeden dokument GetCapabilities dla WMTS, wspólny dla obu parserów.

    Wcześniej `_wmts_capabilities()` i `_wmts_layer_info()` pobierały ten sam
    plik XML (do 8 MB) osobno — czyli podwójny transfer i podwójne czekanie.
    """
    return _single_flight(("wmts-capabilities", preset),
                          lambda: _cached_wmts_capabilities_xml(preset))


@lru_cache(maxsize=8)
def _cached_wmts_capabilities_xml(preset: str) -> bytes:
    return _download(_wmts_capabilities_url(preset), 8_000_000)


_wmts_capabilities_xml.cache_clear = _cached_wmts_capabilities_xml.cache_clear


@lru_cache(maxsize=4)
def _wmts_capabilities(preset: str):
    from ..wmts_service import parse_capabilities as parse_wmts
    xml = _wmts_capabilities_xml(preset)
    sets = parse_wmts(xml)
    if not sets:
        raise ValueError("Serwer WMTS nie udostępnił zestawów matryc kafelków.")
    return sets


def _wmts_capabilities_url(preset: str) -> str:
    from ..wmts_service import capabilities_url as wmts_capabilities_url
    return wmts_capabilities_url(_preset(preset))


@lru_cache(maxsize=4)
def _wmts_layer_info(preset: str) -> tuple:
    """Warstwy WMTS z Capabilities: nazwa, style, formaty, zestawy matryc."""
    from ..wmts_service import parse_layers
    xml = _wmts_capabilities_xml(preset)
    layers = parse_layers(xml)
    if not layers:
        raise ValueError("Serwer WMTS nie opublikował żadnej warstwy.")
    return layers


@lru_cache(maxsize=4)
def _wmts_layers(preset: str) -> tuple:
    """Warstwy WMTS: nazwy z Capabilities, obsługiwane polskie EPSG."""
    sets = _wmts_capabilities(preset)
    crs_sets = {entry.crs.upper() for entry in sets}
    if not any(f"EPSG:{epsg}" in crs_sets for epsg in SUPPORTED_EPSG):
        raise ValueError("Serwer WMTS nie obsługuje polskich układów EPSG.")
    # Kafelki istnieją zwykle tylko dla EPSG:2180, ale dla pozostałych układów
    # schodzimy na równoważny WMS — dlatego zgłaszamy wszystkie obsługiwane.
    supported = tuple(sorted(f"EPSG:{epsg}" for epsg in SUPPORTED_EPSG))
    from ..wms_service import WMSLayerInfo
    published = _wmts_layer_info(preset)
    return tuple(WMSLayerInfo(layer.identifier, layer.title or layer.identifier,
                              supported)
                 for layer in published)


# Cache pojedynczych kafelków WMTS. Kafelki są niezmienne (ta sama matryca,
# wiersz i kolumna), więc trzymamy je w pamięci i ograniczamy rozmiar.
_TILE_CACHE: dict = {}
_TILE_CACHE_ORDER: list = []
_TILE_CACHE_LIMIT = 512          # ok. 512 kafelków ~ kilkadziesiąt MB
_TILE_CACHE_LOCK = threading.Lock()
_disk_puts_since_trim = [0]


def _tile_cache_get(key):
    with _TILE_CACHE_LOCK:
        return _TILE_CACHE.get(key)


def _tile_cache_put(key, raw: bytes) -> None:
    with _TILE_CACHE_LOCK:
        if key not in _TILE_CACHE:
            _TILE_CACHE_ORDER.append(key)
        _TILE_CACHE[key] = raw
        while len(_TILE_CACHE_ORDER) > _TILE_CACHE_LIMIT:
            oldest = _TILE_CACHE_ORDER.pop(0)
            _TILE_CACHE.pop(oldest, None)


def _tile_cache_clear() -> None:
    with _TILE_CACHE_LOCK:
        _TILE_CACHE.clear()
        _TILE_CACHE_ORDER.clear()


@_bounded_request
def _wmts_image(preset: str, layer: str, epsg: int, bounds,
                width: int, height: int) -> bytes:
    """Składa obraz z kafelków WMTS i przycina do żądanego rozmiaru."""
    from ..wmts_service import (gettile_url, pick_matrix, tile_selection,
                               top_left_east_north)
    from concurrent.futures import ThreadPoolExecutor
    from io import BytesIO
    from PIL import Image

    sets = _wmts_capabilities(preset)
    published = next((entry for entry in _wmts_layer_info(preset)
                      if entry.identifier == layer), None)
    if published is None:
        raise ValueError("Serwer WMTS nie udostępnia wybranej warstwy.")
    wanted = f"EPSG:{epsg}".upper()
    matrix_set = next((entry for entry in sets
                       if entry.crs.upper() == wanted and
                       entry.identifier in published.matrix_sets), None)
    if matrix_set is None:
        raise ValueError("Serwer WMTS nie obsługuje wybranego układu EPSG.")
    if width <= 0 or height <= 0:
        raise ValueError("Nieprawidłowy rozmiar obrazu WMTS.")
    east_span = bounds.max_y - bounds.min_y
    north_span = bounds.max_x - bounds.min_x
    pixel_size = max(east_span / width, north_span / height)
    matrix = pick_matrix(matrix_set, pixel_size)
    # Use a coarser WMTS level when necessary instead of abandoning the tile
    # cache for a slow WMS render. Width is easting; height is northing.
    candidates = [matrix] + sorted(
        (entry for entry in matrix_set.matrices
         if entry.resolution(matrix_set.crs) > matrix.resolution(matrix_set.crs)),
        key=lambda entry: entry.resolution(matrix_set.crs))
    for candidate in candidates:
        col0, row0, col1, row1, _ = tile_selection(
            candidate, bounds.min_x, bounds.min_y, bounds.max_x, bounds.max_y,
            crs=matrix_set.crs)
        if (col1 - col0 + 1) * (row1 - row0 + 1) <= 36:
            matrix = candidate
            break
    else:
        raise ValueError("Zbyt wiele kafelków WMTS dla tego kadru.")
    base = _preset(preset)
    # Styl i format bierzemy z Capabilities — serwer odrzuca nieznane wartości.
    style = published.styles[0] if published and published.styles else "default"
    image_format = "image/jpeg"
    if published and published.formats:
        for candidate in ("image/jpeg", "image/png"):
            if candidate in published.formats:
                image_format = candidate
                break
        else:
            image_format = published.formats[0]
    urls = [(row, col) for row in range(row0, row1 + 1)
            for col in range(col0, col1 + 1)]

    def fetch(row, col):
        # Cache kafelków: klucz (preset, layer, matryca, wiersz, kolumna).
        # Po pierwszym pobraniu przesuwanie mapy nie dotyka Geoportalu.
        key = (preset, layer, matrix_set.identifier, matrix.identifier,
               row, col)
        def load():
            cached = _tile_cache_get(key)
            if cached is not None:
                return cached
            url = gettile_url(base, layer, matrix_set.identifier, matrix.identifier,
                              row, col, style=style, image_format=image_format)
            raw = _download(url, MAX_WMS_BYTES)
            try:
                with Image.open(BytesIO(raw)) as image:
                    if image.size != (matrix.tile_width, matrix.tile_height):
                        raise ValueError("Nieprawidłowy rozmiar kafelka WMTS.")
                    image.verify()
            except (OSError, ValueError) as exc:
                raise ValueError("Kafelek WMTS nie jest poprawnym obrazem — " +
                                 _service_exception(raw)) from exc
            # ExceptionReport with HTTP 200 must never poison the tile cache.
            _tile_cache_put(key, raw)
            return raw
        return _single_flight(("wmts-tile", key), load)

    budget = _REQUEST_CONTEXT.budget
    with ThreadPoolExecutor(max_workers=2) as pool:
        tiles = list(pool.map(lambda item: _run_with_budget(budget, fetch, *item),
                              urls))

    res = matrix.resolution(matrix_set.crs)
    span_x = res * matrix.tile_width
    span_y = res * matrix.tile_height
    origin_east, origin_north = top_left_east_north(matrix, matrix_set.crs)
    # Assemble at tile resolution, then sample just the requested extent.
    # Resizing a full tile at deep zoom can allocate an enormous bitmap.
    mosaic = Image.new("RGB", ((col1-col0+1)*matrix.tile_width,
                               (row1-row0+1)*matrix.tile_height))
    for (row, col), raw in zip(urls, tiles):
        with Image.open(BytesIO(raw)) as tile:
            mosaic.paste(tile.convert("RGB"),
                         ((col-col0)*matrix.tile_width,
                          (row-row0)*matrix.tile_height))
    mosaic_east = origin_east + col0*span_x
    mosaic_north = origin_north - row0*span_y
    extent = ((bounds.min_y-mosaic_east)/res,
              (mosaic_north-bounds.max_x)/res,
              (bounds.max_y-mosaic_east)/res,
              (mosaic_north-bounds.min_x)/res)
    out = mosaic.transform((width, height), Image.Transform.EXTENT, extent,
                           Image.Resampling.BICUBIC)
    buffer = BytesIO()
    out.save(buffer, format="JPEG", quality=88, optimize=True)
    data = buffer.getvalue()
    if _looks_blank(out):
        raise ValueError("Serwer WMTS zwrócił puste (czarne) kafelki.")
    return data


def _looks_blank(image) -> bool:
    """Czy obraz jest praktycznie jednolity i ciemny (brak danych)."""
    try:
        from PIL import ImageStat
        small = image.convert("L").resize((32, 32))
        stat = ImageStat.Stat(small)
        mean, stddev = stat.mean[0], stat.stddev[0]
    except Exception:                                 # noqa: BLE001
        return False
    return mean < 26 and stddev < 12


def list_layers(preset: str, url: str | None = None) -> dict:
    layers = layers_for(preset, url)
    if preset == "kieg":
        layers = tuple(layer for layer in layers if layer.name in KIEG_KEEP)
    return {
        "preset": preset,
        "name": PRESETS[preset][0] or validate_service_url(url or ""),
        "layers": [
            {"id": layer.name, "title": layer.title, "epsg": sorted(SUPPORTED_EPSG) if preset == "kieg" and layer.name in PARCEL_LAYERS else sorted(
                int(x.split(":")[1]) for x in layer.crs
                if x.startswith("EPSG:") and x.split(":")[1].isdigit()
                and int(x.split(":")[1]) in SUPPORTED_EPSG)}
            for layer in layers
            if any(x in layer.crs for x in (f"EPSG:{e}" for e in SUPPORTED_EPSG))
        ],
    }


ORTO_FORMAT = "image/jpeg"
ORTO_TILE_LIMIT = 2_400_000      # kafelki dopiero powyżej 2,4 mln px


def _fetch_once(base, layer, crs, bounds, width, height, *, version,
                image_format, transparent, time: str | None = None):
    """Jedno żądanie GetMap. Zwraca bajty obrazu albo podnosi wyjątek."""
    url = getmap_url(base, layer, crs, bounds, width, height,
                     version=version, image_format=image_format,
                     transparent=transparent)
    if time:
        url = url + "&TIME=" + str(time)
    content = _download(url, MAX_WMS_BYTES)
    if _is_image(content):
        return content
    raise ValueError(_service_exception(content))


def _is_image(content: bytes) -> bool:
    return (content.startswith(b"\xff\xd8") or
            content.startswith(b"\x89PNG\r\n\x1a\n") or
            content.startswith(b"GIF8"))


def _service_exception(content: bytes) -> str:
    """Wyciąga czytelny komunikat z ServiceExceptionReport WMS."""
    import re
    text = content[:2000].decode("utf-8", "replace")
    # WMS: ServiceException, WMTS/OGC: ExceptionText w ExceptionReport.
    match = (re.search(r"<ServiceException[^>]*>(.*?)</ServiceException>", text, re.S)
             or re.search(r"<ExceptionText[^>]*>(.*?)</ExceptionText>", text, re.S)
             or re.search(r"<ows:ExceptionText[^>]*>(.*?)</ows:ExceptionText>",
                          text, re.S))
    if match:
        message = re.sub(r"<[^>]+>", " ", match.group(1)).strip()
        if message:
            return "Geoportal: " + " ".join(message.split())[:200]
    return "WMS zwrócił dane inne niż obraz (sprawdź warstwę i EPSG)."


def _to_jpeg(raw: bytes) -> bytes:
    if raw.startswith(b"\xff\xd8"):
        return raw
    try:
        from PIL import Image
        from io import BytesIO
        out = BytesIO()
        Image.open(BytesIO(raw)).convert("RGB").save(
            out, format="JPEG", quality=88, optimize=True)
        return out.getvalue()
    except Exception:                                 # noqa: BLE001
        return raw


def _stitch(tiles: list[bytes], width: int, height: int,
            left_w: int, top_h: int, *, preserve_alpha: bool = False) -> bytes:
    from PIL import Image
    from io import BytesIO
    mode = "RGBA" if preserve_alpha else "RGB"
    images = [Image.open(BytesIO(raw)).convert(mode) for raw in tiles]
    canvas = Image.new(mode, (width, height))
    # Kafelki dzielimy po (północ, wschód):
    #   0 = północ mała, wschód mały   -> LEWY DOLNY
    #   1 = północ duża, wschód mały   -> LEWY GÓRNY
    #   2 = północ mała, wschód duży   -> PRAWY DOLNY
    #   3 = północ duża, wschód duży   -> PRAWY GÓRNY
    # Oś Y obrazu rośnie w dół, więc większa północ ląduje WYŻEJ.
    canvas.paste(images[1], (0, 0))
    canvas.paste(images[3], (left_w, 0))
    canvas.paste(images[0], (0, top_h))
    canvas.paste(images[2], (left_w, top_h))
    out = BytesIO()
    if preserve_alpha:
        canvas.save(out, format="PNG")
    else:
        canvas.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()


# Kolejność prób dla ortofoto. NAJPIERW dokładnie to, co działało przed 2.0.30
# (jedno żądanie, PNG, z przezroczystością) — szybkość jest warta zachodu tylko
# wtedy, gdy obraz w ogóle się pobiera.
# Ortofoto to zdjęcie lotnicze — przezroczystość jest zbędna, a PNG z kanałem
# alfa waży kilkanaście razy więcej niż JPEG i Geoportal renderuje go dłużej.
# Dlatego JPEG bez przezroczystości jest PIERWSZĄ próbą, a PNG dopiero odwrotem
# (przydaje się np. dla usług zwracających paletę lub braki danych).
ORTO_ATTEMPTS = (
    ("1.1.1", "image/jpeg", False),
    ("1.3.0", "image/jpeg", False),
    ("1.1.1", "image/png", True),
    ("1.3.0", "image/png", True),
)


def _fetch_orto_smaller(base, layer, crs, bounds, width, height,
                        time: str | None = None) -> bytes | None:
    """One smaller preview, using only the original request's time budget."""
    for factor in (0.7,):
        small_w = max(128, int(width * factor))
        small_h = max(128, int(height * factor))
        if (small_w, small_h) == (width, height):
            continue
        try:
            return _fetch_once(base, layer, crs, bounds, small_w, small_h,
                               version="1.1.1", image_format="image/png",
                               transparent=True, time=time)
        except _RequestBudgetExpired:
            raise
        except Exception:                             # noqa: BLE001
            continue
    return None


def _attempts_for(preset: str):
    """Kolejność formatów: ortofoto lubi JPEG, warstwy wektorowe potrzebują PNG."""
    if preset in {"kieg", "custom"}:
        return tuple((version, "image/png", True)
                     for version, _fmt, _transparent in ORTO_ATTEMPTS[:2])
    return ORTO_ATTEMPTS


@_bounded_request
def _fetch_orto(base, layer, crs, bounds, width, height,
                time: str | None = None, preset: str = "standard") -> bytes:
    """Ortofoto: jedno lekkie żądanie, kafelki tylko awaryjnie.

    1. JPEG bez przezroczystości (1.1.1, potem 1.3.0) — kilkanaście razy
       mniejszy transfer niż PNG z kanałem alfa,
    2. PNG z przezroczystością (usługi bez JPEG),
    3. kafelki — tylko dla bardzo dużego kadru albo po nieudanych próbach,
    4. mniejszy obraz, gdy serwer Geoportalu nie wyrabia.
    """
    errors = []
    # Jedno żądanie jest szybsze od czterech: kafelki dopiero wtedy, gdy kadr
    # jest naprawdę duży albo pojedyncze próby zawiodły.
    for version, image_format, transparent in _attempts_for(preset):
        try:
            raw = _fetch_once(base, layer, crs, bounds, width, height,
                              version=version, image_format=image_format,
                              transparent=transparent, time=time)
        except _RequestBudgetExpired:
            raise
        except (_DownloadTimeout, TimeoutError) as exc:
            # Changing WMS version/format does not fix a slow large render.
            # Try one smaller frame now, rather than after 16 timed-out GETs.
            smaller = _fetch_orto_smaller(base, layer, crs, bounds,
                                          width, height, time=time)
            if smaller is not None:
                return smaller
            raise RuntimeError(str(exc) or "Przekroczono czas pobierania podkładu.") from exc
        except _TransportError:
            raise
        except Exception as exc:                      # noqa: BLE001
            errors.append(str(exc))
            continue
        return _to_jpeg(raw) if image_format == "image/jpeg" else raw

    # Kafelki: dla bardzo dużego kadru albo gdy pojedyncze żądania zawiodły.
    if width * height > ORTO_TILE_LIMIT or errors:
        try:
            return _fetch_orto_tiles(base, layer, crs, bounds, width, height,
                                     time=time, preserve_alpha=preset == "custom")
        except _RequestBudgetExpired:
            raise
        except Exception as exc:                      # noqa: BLE001
            errors.append(str(exc))

    # Ostatnia próba: mniejszy obraz (serwer Geoportalu bywa wolny).
    smaller = _fetch_orto_smaller(base, layer, crs, bounds, width, height,
                                  time=time)
    if smaller is not None:
        return smaller

    # Zgłaszamy najkonkretniejszy komunikat (np. treść ServiceException).
    detail = next((e for e in errors if "Geoportal:" in e), errors[-1] if errors else "")
    raise RuntimeError(detail or "Nie można pobrać obrazu ortofoto.")


@_bounded_request
def _fetch_orto_tiles(base, layer, crs, bounds, width, height,
                      time: str | None = None,
                      preserve_alpha: bool = False) -> bytes:
    mid_x = (bounds.min_x + bounds.max_x) / 2
    mid_y = (bounds.min_y + bounds.max_y) / 2
    left_w = width // 2
    right_w = width - left_w
    top_h = height // 2
    bottom_h = height - top_h
    parts = [
        (WMSBounds(bounds.min_x, bounds.min_y, mid_x, mid_y), left_w, bottom_h),
        (WMSBounds(mid_x, bounds.min_y, bounds.max_x, mid_y), left_w, top_h),
        (WMSBounds(bounds.min_x, mid_y, mid_x, bounds.max_y), right_w, bottom_h),
        (WMSBounds(mid_x, mid_y, bounds.max_x, bounds.max_y), right_w, bottom_h),
    ]
    from concurrent.futures import ThreadPoolExecutor
    budget = _REQUEST_CONTEXT.budget
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_run_with_budget, budget, _fetch_once,
                               base, layer, crs, part, part_w,
                               part_h, version="1.1.1",
                               image_format="image/png", transparent=True,
                               time=time)
                   for part, part_w, part_h in parts]
        images = [future.result() for future in futures]
    return _stitch(images, width, height, left_w, top_h,
                   preserve_alpha=preserve_alpha)


def map_image(preset: str, layer: str, epsg: int,
              xmin: float, ymin: float, xmax: float, ymax: float,
              width: int, height: int, url: str | None = None,
              time: str | None = None) -> tuple[bytes, str]:
    """Obraz podkładu wraz z typem MIME (JPEG dla ortofoto, PNG dla GUGiK)."""
    data = map_png(preset, layer, epsg, xmin, ymin, xmax, ymax, width, height,
                   url, time)
    # Typ MIME wynika z faktycznej zawartości, nie z założenia.
    if data.startswith(b"\xff\xd8"):
        media = "image/jpeg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        media = "image/png"
    else:
        media = "application/octet-stream"
    return data, media


@_bounded_request
def map_png(preset: str, layer: str, epsg: int,
            xmin: float, ymin: float, xmax: float, ymax: float,
            width: int, height: int, url: str | None = None,
            time: str | None = None) -> bytes:
    base = _preset(preset, url)
    if epsg not in SUPPORTED_EPSG:
        raise ValueError("Wybierz poprawny układ EPSG mapy (2180 lub 2176–2179).")
    if (type(width) is not int or type(height) is not int or
            not 128 <= width <= 2048 or not 128 <= height <= 2048 or
            width * height > 3_000_000):
        raise ValueError("Nieprawidłowa rozdzielczość podkładu.")
    if not all(isfinite(v) for v in (xmin, ymin, xmax, ymax)) or xmin >= xmax or ymin >= ymax:
        raise ValueError("Nieprawidłowy zasięg obrazu WMS.")
    if preset == "kieg" and layer not in KIEG_KEEP:
        raise ValueError("Dla GUGiK dostępna jest tylko warstwa granic i numerów działek.")
    # Canvas world (horizontal=easting, vertical=-northing) -> GEO-MAP X/Y.
    bounds = WMSBounds(min_x=-ymax, min_y=xmin, max_x=-ymin, max_y=xmax)
    key = _cache_key(preset + "|" + (url or "") + "|" + (time or ""), layer,
                     epsg, xmin, ymin, xmax, ymax, width, height)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    def load():
        # Another request may have populated the cache before we acquired
        # ownership of this frame. Check again before any catalogue/network IO.
        cached = _cache_get(key)
        if cached is not None:
            return cached
        candidates = layers_for(preset, url)
        choice = next((entry for entry in candidates if entry.name == layer), None)
        parcel = preset == "kieg" and layer in PARCEL_LAYERS
        if choice is None or (not parcel and f"EPSG:{epsg}" not in choice.crs):
            raise ValueError("Wybrana warstwa nie obsługuje tego EPSG.")
        content = _render_map(preset, base, layer, epsg, bounds, width, height,
                              parcel=parcel, time=time)
        _cache_put(key, content)
        return content

    return _single_flight(("map", key), load)


def _render_map(preset, base, layer, epsg, bounds, width, height,
                *, parcel, time):
    if parcel:
        content = _parcel_image(layer, epsg, bounds, width, height)
    elif preset in WMTS_PRESETS:
        # WMTS ma kafelki tylko w układach, które opublikował serwer (zwykle
        # EPSG:2180). Dla innych układów — albo gdy kafelki są puste — wracamy
        # do równoważnego podkładu WMS, który obsługuje wszystkie polskie EPSG.
        fallback = "standard" if preset == "standard_wmts" else "high"
        try:
            content = _wmts_image(preset, layer, epsg, bounds, width, height)
        except _RequestBudgetExpired:
            raise
        except (ValueError, RuntimeError):
            # Nazwa warstwy z WMTS nie musi istnieć w usłudze WMS
            # (Geoportal: „Parameter 'layers' contains unacceptable layer
            # names”). Dlatego nazwę bierzemy z capabilities WMS.
            content = _fetch_orto(_preset(fallback),
                                  _wms_layer_for(fallback, epsg, layer),
                                  f"EPSG:{epsg}", bounds, width, height,
                                  preset=fallback)
    else:
        content = _fetch_orto(base, layer, f"EPSG:{epsg}", bounds, width, height,
                              time=time, preset=preset)
    return content


def _wms_layer_for(preset: str, epsg: int, preferred: str = "") -> str:
    """Nazwa warstwy WMS: ta sama, jeśli istnieje, inaczej pierwsza dla EPSG."""
    try:
        candidates = _layers_for_preset(preset)
    except _RequestBudgetExpired:
        raise
    except (ValueError, RuntimeError):
        return preferred
    names = [entry.name for entry in candidates
             if f"EPSG:{epsg}" in entry.crs]
    if preferred in names:
        return preferred
    if names:
        return names[0]
    if preferred:
        return preferred
    raise ValueError("Usługa WMS nie udostępniła warstwy dla tego układu.")


def _parcel_image(layer, epsg, bounds, width, height):
    """Fetch the official 1992 overlay and warp its alpha channel with the lines."""
    from PIL import Image
    from pyproj import Transformer
    west, south, east, north = bounds.getmap_bbox(f"EPSG:{epsg}", "1.1.1")
    source = bounds
    if epsg != 2180:
        transform = Transformer.from_crs(epsg, 2180, always_xy=True)
        left, bottom, right, top = transform.transform_bounds(west, south, east, north, densify_pts=21)
        source = WMSBounds(bottom, left, top, right)
    error = None
    for endpoint in (KIEG_IMAGE_URL, PRESETS["kieg"][1]):
        url = getmap_url(endpoint, layer, "EPSG:2180", source, width, height, version="1.1.1")
        try:
            content = _download(url, MAX_WMS_BYTES)
            if not content.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Usługa działek GUGiK zwróciła odpowiedź bez obrazu PNG.")
            with Image.open(BytesIO(content)) as image:
                if image.size != (width, height):
                    raise ValueError("Usługa działek GUGiK zwróciła obraz o innym rozmiarze.")
                if epsg == 2180:
                    image.verify()
                    return content
                overlay = image.convert("RGBA")
            break
        except _RequestBudgetExpired:
            raise
        except (RuntimeError, OSError, ValueError) as exc:
            error = exc
    else:
        raise RuntimeError("Nie udało się pobrać obrazu działek z obu adresów usługi GUGiK.") from error

    def source_pixel(x, y):
        e, n = transform.transform(west + x*(east-west)/width, north - y*(north-south)/height)
        return ((e-left)*width/(right-left), (top-n)*height/(top-bottom))

    mesh = []
    for y in range(0, height, 64):
        for x in range(0, width, 64):
            x1, y1 = min(width, x+64), min(height, y+64)
            quad = source_pixel(x,y) + source_pixel(x,y1) + source_pixel(x1,y1) + source_pixel(x1,y)
            mesh.append(((x,y,x1,y1), quad))
    result = overlay.transform((width,height), Image.Transform.MESH, mesh, Image.Resampling.BILINEAR)
    output = BytesIO()
    result.save(output, "PNG")
    return output.getvalue()
