"""OGC WMS request construction and GeoStudio coordinate conventions.

GEO-MAP uses X=northing / Y=easting, while WMS BBOX uses easting /
northing for projected CRS. For EPSG:4326 in WMS 1.3.0 it uses latitude
before longitude. No assumption is made about a map's source CRS.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class WMSLayerInfo:
    name: str
    title: str
    crs: tuple[str, ...]
    attribution: str = ""


@dataclass(frozen=True)
class WMSBounds:
    """Visible GEO-MAP extents, in X=northing, Y=easting order."""
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def __post_init__(self):
        values = (self.min_x, self.min_y, self.max_x, self.max_y)
        if not all(isfinite(v) for v in values) or self.min_x >= self.max_x or self.min_y >= self.max_y:
            raise ValueError("Nieprawidłowy obszar mapy dla WMS.")

    def getmap_bbox(self, crs: str, version: str = "1.3.0") -> tuple[float, ...]:
        # Projected coordinates: (easting min, northing min, easting max, northing max).
        # EPSG:4326 in WMS 1.3.0 has official latitude/longitude axis ordering.
        if crs.upper() == "EPSG:4326" and version == "1.3.0":
            return self.min_x, self.min_y, self.max_x, self.max_y
        return self.min_y, self.min_x, self.max_y, self.max_x


def _tag(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _direct_text(element, name: str) -> str:
    for child in element:
        if _tag(child) == name:
            return (child.text or "").strip()
    return ""


def parse_capabilities(xml: bytes) -> tuple[WMSLayerInfo, ...]:
    if len(xml) > 4_000_000:
        raise ValueError("Odpowiedź WMS GetCapabilities jest zbyt duża.")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError("Serwer nie zwrócił poprawnego dokumentu GetCapabilities.") from exc
    result: list[WMSLayerInfo] = []
    seen: set[str] = set()

    def visit(node, parent_crs=(), parent_attribution=""):
        local_crs = {v.upper() for v in parent_crs}
        for child in node:
            if _tag(child) in ("CRS", "SRS") and child.text:
                for value in child.text.strip().split():
                    local_crs.add(value.upper())
        attribution = parent_attribution
        for child in node:
            if _tag(child) == "Attribution":
                for urlnode in child.iter():
                    if _tag(urlnode) == "Title" and urlnode.text:
                        attribution = urlnode.text.strip()
                        break
        name = _direct_text(node, "Name")
        title = _direct_text(node, "Title") or name
        if name and name not in seen:
            result.append(WMSLayerInfo(name, title, tuple(sorted(local_crs)), attribution))
            seen.add(name)
        for child in node:
            if _tag(child) == "Layer":
                visit(child, local_crs, attribution)

    for capability in root.iter():
        if _tag(capability) == "Capability":
            for layer in capability:
                if _tag(layer) == "Layer":
                    visit(layer)
    return tuple(result)


def _service_url(base_url: str) -> tuple[str, str, str, list[tuple[str, str]], str]:
    if len(base_url) > 2048:
        raise ValueError("Zbyt długi adres WMS.")
    parsed = urlsplit(base_url.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Adres WMS musi rozpoczynać się od http:// lub https://")
    if parsed.username or parsed.password:
        raise ValueError("Nie podawaj loginów lub haseł w adresie WMS.")
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if k.upper() not in {"REQUEST", "SERVICE", "VERSION", "LAYERS",
                                   "BBOX", "CRS", "SRS", "WIDTH", "HEIGHT",
                                   "FORMAT", "STYLES", "TRANSPARENT"}]
    return parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment


def _merge(base_url: str, params: dict[str, str]) -> str:
    scheme, netloc, path, query, fragment = _service_url(base_url)
    return urlunsplit((scheme, netloc, path,
                       urlencode(query + list(params.items())), fragment))


def capabilities_url(base_url: str) -> str:
    return _merge(base_url, {"SERVICE": "WMS", "REQUEST": "GetCapabilities"})


def getmap_url(base_url: str, layer: str, crs: str, bounds: WMSBounds,
               width: int, height: int, *, version="1.3.0") -> str:
    if version not in {"1.3.0", "1.1.1"}:
        raise ValueError("Obsługiwane wersje WMS: 1.3.0 i 1.1.1.")
    if not layer.strip():
        raise ValueError("Wybierz warstwę WMS.")
    if not re.fullmatch(r"EPSG:[0-9]{4,6}", crs.upper()):
        raise ValueError("Wybierz prawidłowy EPSG dla mapy i usługi WMS.")
    if not 64 <= width <= 4096 or not 64 <= height <= 4096:
        raise ValueError("Nieprawidłowy rozmiar obrazu WMS.")
    bbox = bounds.getmap_bbox(crs, version)
    bbox_str = ",".join(f"{value:.10f}".rstrip("0").rstrip(".") for value in bbox)
    params = {
        "SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": version,
        "LAYERS": layer, "STYLES": "", "FORMAT": "image/png",
        "TRANSPARENT": "TRUE",
        "WIDTH": str(width), "HEIGHT": str(height),
        "BBOX": bbox_str,
        ("CRS" if version == "1.3.0" else "SRS"): crs.upper(),
    }
    return _merge(base_url, params)


def google_maps_reference_url(map_x: float, map_y: float, source_epsg: int,
                              zoom: int = 17) -> str:
    """Official browser Google Maps reference near a GEO-MAP map coordinate.

    Google imagery must not be scraped or republished as custom tiles.
    map_x is northing and map_y easting, unlike pyproj's (east,north).
    """
    from .coordinates import KNOWN_EPSG
    if source_epsg not in KNOWN_EPSG:
        raise ValueError("Wybierz obsługiwany i zweryfikowany układ mapy.")
    if not all(isfinite(v) for v in (map_x, map_y)):
        raise ValueError("Nieprawidłowe współrzędne.")
    if not 1 <= zoom <= 21:
        raise ValueError("Nieprawidłowy zoom Google Maps.")
    from pyproj import Transformer
    transform = Transformer.from_crs(
        f"EPSG:{source_epsg}", "EPSG:4326", always_xy=True)
    longitude, latitude = transform.transform(map_y, map_x, errcheck=True)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Punkt znajduje się poza zakresem współrzędnych geograficznych.")
    return f"https://www.google.com/maps/@{latitude:.7f},{longitude:.7f},{zoom}z"
