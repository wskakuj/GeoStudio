"""Read-only Geoportal WMS proxy for the localhost GeoStudio 2.0 canvas.

The browser never requests remote imagery directly (CORS, credentials).
Only two official HTTPS GUGiK endpoints are accessible; arbitrary URLs,
redirects, oversized replies and non-image responses are rejected.
No MAP data or selected geometry is sent to the provider.
"""
from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import urlsplit
from math import isfinite

from geostudio.wms_service import WMSBounds, capabilities_url, getmap_url, parse_capabilities

PRESETS = {
    "standard": ("Ortofotomapa standardowa", "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardResolution"),
    "high": ("Ortofotomapa wysoka rozdzielczość", "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/HighResolution"),
    "kieg": ("Działki ewidencyjne i numery — GUGiK", "https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow"),
}
# An explicit user choice is mandatory; no inference from MAP coordinates.
SUPPORTED_EPSG = frozenset((2180, 2176, 2177, 2178, 2179))
MAX_WMS_BYTES = 15_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _download(url: str, max_bytes: int) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in {"mapy.geoportal.gov.pl", "integracja.gugik.gov.pl"} or parsed.port not in (None, 443):
        raise ValueError("Dozwolone są wyłącznie oficjalne usługi Geoportalu.")
    if parsed.username or parsed.password:
        raise ValueError("Nieprawidłowy adres usługi.")
    req = Request(url, headers={"User-Agent": "GeoStudio-2-WMS/12A", "Accept": "image/png, application/xml, text/xml"})
    try:
        with build_opener(NoRedirect).open(req, timeout=15) as reply:
            if urlsplit(reply.geturl()).hostname != parsed.hostname:
                raise ValueError("Usługa przekierowała na niezaufany adres.")
            content = reply.read(max_bytes + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("Nie można pobrać danych WMS z Geoportalu.") from exc
    if len(content) > max_bytes:
        raise ValueError("Odpowiedź WMS przekracza limit rozmiaru.")
    return content


def _preset(name: str) -> str:
    if name not in PRESETS:
        raise ValueError("Nieznane źródło ortofotomapy.")
    return PRESETS[name][1]


@lru_cache(maxsize=3)
def layers_for(preset: str) -> tuple:
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
            {"id": layer.name, "title": layer.title, "epsg": sorted(
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
    if choice is None or f"EPSG:{epsg}" not in choice.crs:
        raise ValueError("Wybrana warstwa nie obsługuje tego EPSG.")
    # Canvas world (horizontal=easting, vertical=-northing) -> GEO-MAP X/Y.
    bounds = WMSBounds(min_x=-ymax, min_y=xmin, max_x=-ymin, max_y=xmax)
    url = getmap_url(base, layer, f"EPSG:{epsg}", bounds, width, height,
                     version="1.1.1")
    content = _download(url, MAX_WMS_BYTES)
    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("WMS zwrócił dane inne niż obraz PNG; sprawdź warstwę i EPSG.")
    return content
