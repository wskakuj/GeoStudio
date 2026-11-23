"""Read-only Geoportal WMS proxy for the localhost GeoStudio 2.0 canvas.

The browser never requests remote imagery directly (CORS, credentials).
Only approved official HTTPS GUGiK endpoints are accessible; arbitrary URLs,
redirects, oversized replies and non-image responses are rejected.
No MAP data or selected geometry is sent to the provider.
"""
from __future__ import annotations

from collections import OrderedDict
from functools import lru_cache
import http.client
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
    "mapy.geoportal.gov.pl": 60,
    "integracja.gugik.gov.pl": 20,
    "integracja02.gugik.gov.pl": 20,
}


def _timeout_for(host: str) -> int:
    return HOST_TIMEOUTS.get(host, 20)


def _connection(host: str) -> "http.client.HTTPSConnection":
    """Połączenie TLS z utrzymaniem (keep-alive), przypisane do bieżącego wątku."""
    pool = _thread_pool()
    conn = pool.get(host)
    if conn is None:
        conn = http.client.HTTPSConnection(host, timeout=_timeout_for(host))
        pool[host] = conn
    return conn


def _drop_connection(host: str) -> None:
    conn = _thread_pool().pop(host, None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
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
    # Trzy próby z krótkim odstępem: Geoportal potrafi zerwać połączenie
    # przy serii żądań (kafelki), a natychmiastowa powtórka zwykle wystarcza.
    for attempt in range(3):
        if attempt:
            time.sleep(0.15 * attempt)
        try:
            conn = _connection(host)
            conn.request("GET", path, headers=headers)
            reply = conn.getresponse()
            if reply.status in (301, 302, 303, 307, 308):
                raise ValueError("Usługa przekierowała na niezaufany adres.")
            if reply.status >= 400:
                raise RuntimeError("Geoportal zwrócił błąd " + str(reply.status) + ".")
            content = reply.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise ValueError("Odpowiedź WMS przekracza limit rozmiaru.")
            return content
        except (http.client.HTTPException, OSError, TimeoutError) as exc:
            # Zerwane połączenie keep-alive: nowe i jedna ponowna próba.
            last = exc
            _drop_connection(host)
            if attempt == 2:
                break
    reason = type(last).__name__ if last else "nieznany błąd"
    raise RuntimeError(
        "Nie można pobrać danych WMS z Geoportalu (" + reason +
        "). Spróbuj ponownie za chwilę.") from last


_CACHE: "OrderedDict[tuple, bytes]" = OrderedDict()
_CACHE_BYTES = 0
_CACHE_LIMIT = 128 * 1024 * 1024
_CACHE_MAX_ENTRIES = 160
_CACHE_LOCK = threading.Lock()


def _cache_key(preset, layer, epsg, xmin, ymin, xmax, ymax, width, height):
    return (preset, layer, epsg,
            round(xmin, 2), round(ymin, 2), round(xmax, 2), round(ymax, 2),
            width, height)


def _cache_get(key):
    with _CACHE_LOCK:
        value = _CACHE.get(key)
        if value is not None:
            _CACHE.move_to_end(key)
        return value


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


def cache_stats() -> dict:
    with _CACHE_LOCK:
        return {"entries": len(_CACHE), "bytes": _CACHE_BYTES}


def clear_cache() -> None:
    global _CACHE_BYTES
    with _CACHE_LOCK:
        _CACHE.clear()
        _CACHE_BYTES = 0


def _preset(name: str, url: str | None = None) -> str:
    if name not in PRESETS:
        raise ValueError("Nieznane źródło ortofotomapy.")
    if name == "custom":
        return validate_service_url(url or "")
    return PRESETS[name][1]


def layers_for(preset: str, url: str | None = None) -> tuple:
    if preset in WMTS_PRESETS:
        return _wmts_layers(preset)
    if preset == "custom":
        xml = _download(capabilities_url(validate_service_url(url or "")),
                        4_000_000)
        layers = parse_capabilities(xml)
        if not layers:
            raise ValueError("Serwer nie udostępnił nazwanych warstw WMS.")
        return layers
    return _layers_for_preset(preset)


@lru_cache(maxsize=3)
def _layers_for_preset(preset: str) -> tuple:
    if preset == "kieg":
        # The published GetMap example provides these layers in PL-1992,
        # independently of availability of the capabilities catalogue.
        defaults = tuple(WMSLayerInfo(key, title, ("EPSG:2180",)) for key, title in (
            (KIEG_PARCELS, "Granice i numery działek"),
            ("dzialki", "Granice działek"), ("numery_dzialek", "Numery działek")))
        try:
            catalogue = parse_capabilities(_download(capabilities_url(_preset(preset)), 4_000_000))
        except (RuntimeError, ValueError):
            catalogue = ()
        keys = {entry.name for entry in defaults}
        return defaults + tuple(entry for entry in catalogue if entry.name not in keys)
    xml = _download(capabilities_url(_preset(preset)), 4_000_000)
    layers = parse_capabilities(xml)
    if not layers:
        raise ValueError("Geoportal nie udostępnił nazwanych warstw WMS.")
    return layers


# Zgodność ze starym API: layers_for() nie jest już bezpośrednio cache'owana
# (adres własnego serwera zmienia wynik), ale czyszczenie cache zostaje.
layers_for.cache_clear = _layers_for_preset.cache_clear


# Dla GUGiK pokazujemy tylko jedną, używaną warstwę: granice i numery działek.
KIEG_KEEP = frozenset({KIEG_PARCELS})


@lru_cache(maxsize=4)
def _wmts_capabilities(preset: str):
    from ..wmts_service import parse_capabilities as parse_wmts
    xml = _download(_wmts_capabilities_url(preset), 8_000_000)
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
    xml = _download(_wmts_capabilities_url(preset), 8_000_000)
    layers = parse_layers(xml)
    if not layers:
        raise ValueError("Serwer WMTS nie opublikował żadnej warstwy.")
    return layers


@lru_cache(maxsize=4)
def _wmts_layers(preset: str) -> tuple:
    """Warstwy WMTS: nazwy z Capabilities, obsługiwane polskie EPSG."""
    sets = _wmts_capabilities(preset)
    crs_sets = {entry.crs.upper() for entry in sets}
    supported = tuple(sorted(f"EPSG:{epsg}" for epsg in SUPPORTED_EPSG
                             if f"EPSG:{epsg}" in crs_sets))
    if not supported:
        raise ValueError("Serwer WMTS nie obsługuje polskich układów EPSG.")
    from ..wms_service import WMSLayerInfo
    published = _wmts_layer_info(preset)
    return tuple(WMSLayerInfo(layer.identifier, layer.title or layer.identifier,
                              supported)
                 for layer in published)


def _wmts_image(preset: str, layer: str, epsg: int, bounds,
                width: int, height: int) -> bytes:
    """Składa obraz z kafelków WMTS i przycina do żądanego rozmiaru."""
    from ..wmts_service import (gettile_url, mosaic_origin, pick_matrix,
                                tile_selection)
    from concurrent.futures import ThreadPoolExecutor
    from io import BytesIO
    from PIL import Image

    sets = _wmts_capabilities(preset)
    wanted = f"EPSG:{epsg}".upper()
    matrix_set = next((entry for entry in sets
                       if entry.crs.upper() == wanted), None)
    if matrix_set is None:
        raise ValueError("Serwer WMTS nie obsługuje wybranego układu EPSG.")
    pixel_size = max(1e-9, (bounds.max_x - bounds.min_x) / max(1, width))
    matrix = pick_matrix(matrix_set, pixel_size)
    col0, row0, col1, row1, swapped = tile_selection(
        matrix, bounds.min_x, bounds.min_y, bounds.max_x, bounds.max_y)
    if (col1 - col0 + 1) * (row1 - row0 + 1) > 36:
        raise ValueError("Zbyt wiele kafelków WMTS dla tego kadru.")
    base = _preset(preset)
    # Styl i format bierzemy z Capabilities — serwer odrzuca nieznane wartości.
    published = next((entry for entry in _wmts_layer_info(preset)
                      if entry.identifier == layer), None)
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
        url = gettile_url(base, layer, matrix_set.identifier, matrix.identifier,
                          row, col, style=style, image_format=image_format)
        return _download(url, MAX_WMS_BYTES)

    with ThreadPoolExecutor(max_workers=2) as pool:
        tiles = list(pool.map(lambda item: fetch(*item), urls))

    res = matrix.resolution()
    sheet = Image.new("RGB",
                      (matrix.tile_width * (col1 - col0 + 1),
                       matrix.tile_height * (row1 - row0 + 1)))
    for (row, col), raw in zip(urls, tiles):
        try:
            tile = Image.open(BytesIO(raw)).convert("RGB")
        except Exception as exc:                      # noqa: BLE001
            detail = _service_exception(raw)
            raise ValueError(
                "Kafelek WMTS nie jest obrazem — " + detail) from exc
        sheet.paste(tile, ((col - col0) * matrix.tile_width,
                           (row - row0) * matrix.tile_height))
    # Kadr w metrach -> piksele sklejonej mozaiki.
    origin_x, origin_y = mosaic_origin(matrix, col0, row0, swapped)
    box = (int(round((bounds.min_x - origin_x) / res)),
           int(round((origin_y - bounds.max_y) / res)),
           int(round((bounds.max_x - origin_x) / res)),
           int(round((origin_y - bounds.min_y) / res)))
    box = (max(0, box[0]), max(0, box[1]),
           min(sheet.width, box[2]), min(sheet.height, box[3]))
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("Kadr nie pokrywa się z kafelkami WMTS.")
    cropped = sheet.crop(box).resize((width, height), Image.LANCZOS)
    out = BytesIO()
    cropped.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()


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
ORTO_TILE_LIMIT = 1_200_000        # powyżej tylu pikseli dzielimy na kafelki


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
            left_w: int, top_h: int) -> bytes:
    from PIL import Image
    from io import BytesIO
    images = [Image.open(BytesIO(raw)).convert("RGB") for raw in tiles]
    canvas = Image.new("RGB", (width, height))
    canvas.paste(images[0], (0, 0))
    canvas.paste(images[1], (left_w, 0))
    canvas.paste(images[2], (0, top_h))
    canvas.paste(images[3], (left_w, top_h))
    out = BytesIO()
    canvas.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()


# Kolejność prób dla ortofoto. NAJPIERW dokładnie to, co działało przed 2.0.30
# (jedno żądanie, PNG, z przezroczystością) — szybkość jest warta zachodu tylko
# wtedy, gdy obraz w ogóle się pobiera.
ORTO_ATTEMPTS = (
    ("1.1.1", "image/png", True),
    ("1.3.0", "image/png", True),
    ("1.1.1", "image/jpeg", False),
    ("1.3.0", "image/jpeg", False),
)


def _fetch_orto_smaller(base, layer, crs, bounds, width, height) -> bytes | None:
    """Ostatnia deska ratunku: mniejszy obraz, żeby serwer zdążył odpowiedzieć."""
    for factor in (0.7, 0.5):
        small_w = max(128, int(width * factor))
        small_h = max(128, int(height * factor))
        if (small_w, small_h) == (width, height):
            continue
        try:
            return _fetch_once(base, layer, crs, bounds, small_w, small_h,
                               version="1.1.1", image_format="image/png",
                               transparent=True)
        except Exception:                             # noqa: BLE001
            continue
    return None


def _fetch_orto(base, layer, crs, bounds, width, height,
                time: str | None = None) -> bytes:
    """Ortofoto z pełnym łańcuchem odwrotów.

    1. jedno żądanie PNG (zachowanie sprzed 2.0.30 — zawsze działało),
    2. to samo w WMS 1.3.0 (niektóre usługi przyjmują tylko tę wersję),
    3. JPEG (mniejszy transfer),
    4. na końcu kafelki — tylko gdy wszystko inne zawiodło.
    """
    errors = []
    for version, image_format, transparent in ORTO_ATTEMPTS:
        try:
            raw = _fetch_once(base, layer, crs, bounds, width, height,
                              version=version, image_format=image_format,
                              transparent=transparent, time=time)
        except Exception as exc:                      # noqa: BLE001
            errors.append(str(exc))
            continue
        return _to_jpeg(raw) if image_format == "image/jpeg" else raw

    if width * height > ORTO_TILE_LIMIT:
        try:
            return _fetch_orto_tiles(base, layer, crs, bounds, width, height)
        except Exception as exc:                      # noqa: BLE001
            errors.append(str(exc))

    # Ostatnia próba: mniejszy obraz (serwer Geoportalu bywa wolny).
    smaller = _fetch_orto_smaller(base, layer, crs, bounds, width, height)
    if smaller is not None:
        return smaller

    # Zgłaszamy najkonkretniejszy komunikat (np. treść ServiceException).
    detail = next((e for e in errors if "Geoportal:" in e), errors[-1] if errors else "")
    raise RuntimeError(detail or "Nie można pobrać obrazu ortofoto.")


def _fetch_orto_tiles(base, layer, crs, bounds, width, height) -> bytes:
    mid_x = (bounds.min_x + bounds.max_x) / 2
    mid_y = (bounds.min_y + bounds.max_y) / 2
    left_w = width // 2
    right_w = width - left_w
    top_h = height // 2
    bottom_h = height - top_h
    parts = [
        (WMSBounds(bounds.min_x, bounds.min_y, mid_x, mid_y), left_w, top_h),
        (WMSBounds(mid_x, bounds.min_y, bounds.max_x, mid_y), right_w, top_h),
        (WMSBounds(bounds.min_x, mid_y, mid_x, bounds.max_y), left_w, bottom_h),
        (WMSBounds(mid_x, mid_y, bounds.max_x, bounds.max_y), right_w, bottom_h),
    ]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_fetch_once, base, layer, crs, part, part_w,
                               part_h, version="1.1.1",
                               image_format="image/png", transparent=True)
                   for part, part_w, part_h in parts]
        images = [future.result() for future in futures]
    return _stitch(images, width, height, left_w, top_h)


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
    candidates = layers_for(preset, url)
    if preset == "kieg" and layer not in KIEG_KEEP:
        raise ValueError("Dla GUGiK dostępna jest tylko warstwa granic i numerów działek.")
    choice = next((entry for entry in candidates if entry.name == layer), None)
    parcel = preset == "kieg" and layer in PARCEL_LAYERS
    if choice is None or (not parcel and f"EPSG:{epsg}" not in choice.crs):
        raise ValueError("Wybrana warstwa nie obsługuje tego EPSG.")
    # Canvas world (horizontal=easting, vertical=-northing) -> GEO-MAP X/Y.
    bounds = WMSBounds(min_x=-ymax, min_y=xmin, max_x=-ymin, max_y=xmax)
    key = _cache_key(preset + "|" + (url or "") + "|" + (time or ""), layer,
                     epsg, xmin, ymin, xmax, ymax, width, height)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    if parcel:
        content = _parcel_image(layer, epsg, bounds, width, height)
    elif preset in WMTS_PRESETS:
        content = _wmts_image(preset, layer, epsg, bounds, width, height)
    else:
        content = _fetch_orto(base, layer, f"EPSG:{epsg}", bounds, width, height,
                              time=time)
    _cache_put(key, content)
    return content


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
