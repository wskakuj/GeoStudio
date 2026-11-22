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
}
# An explicit user choice is mandatory; no inference from MAP coordinates.
SUPPORTED_EPSG = frozenset((2180, 2176, 2177, 2178, 2179))
KIEG_IMAGE_URL = "https://integracja02.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow"
KIEG_PARCELS = "dzialki,numery_dzialek"
PARCEL_LAYERS = (KIEG_PARCELS, "dzialki", "numery_dzialek")
MAX_WMS_BYTES = 15_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_CONNECTIONS: dict[str, "http.client.HTTPSConnection"] = {}
_CONNECTION_LOCK = threading.Lock()


def _connection(host: str) -> "http.client.HTTPSConnection":
    """Połączenie TLS z utrzymaniem (keep-alive) — bez nowego handshake
    przy każdym przesunięciu mapy."""
    with _CONNECTION_LOCK:
        conn = _CONNECTIONS.get(host)
        if conn is None:
            conn = http.client.HTTPSConnection(host, timeout=15)
            _CONNECTIONS[host] = conn
        return conn


def _drop_connection(host: str) -> None:
    with _CONNECTION_LOCK:
        conn = _CONNECTIONS.pop(host, None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def _download(url: str, max_bytes: int) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"mapy.geoportal.gov.pl", "integracja.gugik.gov.pl", "integracja02.gugik.gov.pl"} or parsed.port not in (None, 443):
        raise ValueError("Dozwolone są wyłącznie oficjalne usługi Geoportalu.")
    if parsed.username or parsed.password:
        raise ValueError("Nieprawidłowy adres usługi.")
    host = parsed.hostname
    path = parsed.path + ("?" + parsed.query if parsed.query else "")
    headers = {"User-Agent": "GeoStudio-2-WMS/12A",
               "Accept": "image/png, application/xml, text/xml",
               "Connection": "keep-alive"}
    last: Exception | None = None
    for attempt in range(2):
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
            if attempt:
                break
    raise RuntimeError("Nie można pobrać danych WMS z Geoportalu.") from last


_CACHE: "OrderedDict[tuple, bytes]" = OrderedDict()
_CACHE_BYTES = 0
_CACHE_LIMIT = 48 * 1024 * 1024
_CACHE_MAX_ENTRIES = 96
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


def _preset(name: str) -> str:
    if name not in PRESETS:
        raise ValueError("Nieznane źródło ortofotomapy.")
    return PRESETS[name][1]


@lru_cache(maxsize=3)
def layers_for(preset: str) -> tuple:
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


def list_layers(preset: str) -> dict:
    layers = layers_for(preset)
    return {
        "preset": preset,
        "name": PRESETS[preset][0],
        "layers": [
            {"id": layer.name, "title": layer.title, "epsg": sorted(SUPPORTED_EPSG) if preset == "kieg" and layer.name in PARCEL_LAYERS else sorted(
                int(x.split(":")[1]) for x in layer.crs
                if x.startswith("EPSG:") and x.split(":")[1].isdigit()
                and int(x.split(":")[1]) in SUPPORTED_EPSG)}
            for layer in layers
            if any(x in layer.crs for x in (f"EPSG:{e}" for e in SUPPORTED_EPSG))
        ],
    }


def map_png(preset: str, layer: str, epsg: int,
            xmin: float, ymin: float, xmax: float, ymax: float,
            width: int, height: int) -> bytes:
    base = _preset(preset)
    if epsg not in SUPPORTED_EPSG:
        raise ValueError("Wybierz poprawny układ EPSG mapy (2180 lub 2176–2179).")
    if (type(width) is not int or type(height) is not int or
            not 128 <= width <= 2048 or not 128 <= height <= 2048 or
            width * height > 3_000_000):
        raise ValueError("Nieprawidłowa rozdzielczość podkładu.")
    if not all(isfinite(v) for v in (xmin, ymin, xmax, ymax)) or xmin >= xmax or ymin >= ymax:
        raise ValueError("Nieprawidłowy zasięg obrazu WMS.")
    candidates = layers_for(preset)
    choice = next((entry for entry in candidates if entry.name == layer), None)
    parcel = preset == "kieg" and layer in PARCEL_LAYERS
    if choice is None or (not parcel and f"EPSG:{epsg}" not in choice.crs):
        raise ValueError("Wybrana warstwa nie obsługuje tego EPSG.")
    # Canvas world (horizontal=easting, vertical=-northing) -> GEO-MAP X/Y.
    bounds = WMSBounds(min_x=-ymax, min_y=xmin, max_x=-ymin, max_y=xmax)
    key = _cache_key(preset, layer, epsg, xmin, ymin, xmax, ymax, width, height)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    if parcel:
        content = _parcel_image(layer, epsg, bounds, width, height)
    else:
        url = getmap_url(base, layer, f"EPSG:{epsg}", bounds, width, height,
                         version="1.1.1")
        content = _download(url, MAX_WMS_BYTES)
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("WMS zwrócił dane inne niż obraz PNG; sprawdź warstwę i EPSG.")
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
