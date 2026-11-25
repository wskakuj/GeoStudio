"""Minimalny klient WMTS (KVP) dla Geoportalu.

WMTS zwraca KAFELKI, a nie dowolny wycinek mapy, więc trzeba:
- odczytać z GetCapabilities zestaw matryc (TileMatrixSet) i same matryce,
- wybrać poziom, którego rozdzielczość odpowiada żądanym pikselom,
- policzyć numery kafelków pokrywających żądany obszar,
- pobrać je, skleić i przyciąć do żądanego rozmiaru.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache

# Domyślna rozdzielczość kafelka WMTS (Geoportal używa 512).
DEFAULT_TILE = 512


def _tag(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


@dataclass(frozen=True)
class TileMatrix:
    identifier: str
    scale_denominator: float
    top_left: tuple[float, float]
    tile_width: int
    tile_height: int
    matrix_width: int
    matrix_height: int

    def resolution(self, crs: str | None = None) -> float:
        """Rozmiar piksela w jednostkach CRS (domyślnie w metrach)."""
        metres_per_unit = _crs_axes(crs)[1] if crs else 1.0
        return self.scale_denominator * 0.00028 / metres_per_unit


@dataclass(frozen=True)
class WmtsLayer:
    identifier: str
    title: str
    styles: tuple[str, ...]
    formats: tuple[str, ...]
    matrix_sets: tuple[str, ...]


@dataclass(frozen=True)
class TileMatrixSet:
    identifier: str
    crs: str
    matrices: tuple[TileMatrix, ...]


def parse_layers(xml: bytes) -> tuple[WmtsLayer, ...]:
    """Warstwy WMTS: nazwa, style, formaty i zestawy matryc z Capabilities."""
    if len(xml) > 8_000_000:
        raise ValueError("Odpowiedź WMTS GetCapabilities jest zbyt duża.")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError("Serwer nie zwrócił poprawnego dokumentu WMTS.") from exc
    layers: list[WmtsLayer] = []
    for node in root.iter():
        if _tag(node) != "Layer":
            continue
        identifier = title = ""
        styles: list[str] = []
        formats: list[str] = []
        sets: list[str] = []
        for child in node:
            name = _tag(child)
            if name == "Identifier" and child.text and not identifier:
                identifier = child.text.strip()
            elif name == "Title" and child.text and not title:
                title = child.text.strip()
            elif name == "Style":
                for item in child:
                    if _tag(item) == "Identifier" and item.text:
                        styles.append(item.text.strip())
                        break
            elif name == "Format" and child.text:
                formats.append(child.text.strip())
            elif name == "TileMatrixSetLink":
                for item in child:
                    if _tag(item) == "TileMatrixSet" and item.text:
                        sets.append(item.text.strip())
        if identifier:
            layers.append(WmtsLayer(identifier, title or identifier,
                                    tuple(styles), tuple(formats), tuple(sets)))
    return tuple(layers)


def normalise_crs(value: str) -> str:
    """URN/URL -> EPSG:xxxx (Geoportal publikuje urn:ogc:def:crs:EPSG::2180)."""
    text = (value or "").strip()
    if not text:
        return ""
    upper = text.upper()
    if upper.startswith("URN:OGC:DEF:CRS:EPSG::"):
        return "EPSG:" + upper.split("::")[-1]
    if "EPSG:" in upper:
        tail = upper.rsplit("EPSG:", 1)[-1].strip(":/ ")
        return "EPSG:" + tail
    return upper


def _floats(text: str) -> tuple[float, ...]:
    return tuple(float(part) for part in (text or "").replace(",", " ").split())


def parse_capabilities(xml: bytes) -> tuple[TileMatrixSet, ...]:
    """Zwraca zestawy matryc kafelków z dokumentu WMTS GetCapabilities."""
    if len(xml) > 8_000_000:
        raise ValueError("Odpowiedź WMTS GetCapabilities jest zbyt duża.")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError("Serwer nie zwrócił poprawnego dokumentu WMTS.") from exc
    for element in root.iter():
        if _tag(element) in {"ServiceException", "ExceptionText"}:
            detail = (element.text or "").strip()
            raise ValueError("Serwer WMTS zgłosił błąd: " +
                             (detail[:300] or "nieznany błąd usługi."))
    sets: list[TileMatrixSet] = []
    for node in root.iter():
        if _tag(node) != "TileMatrixSet":
            continue
        identifier = ""
        crs = ""
        matrices: list[TileMatrix] = []
        for child in node:
            name = _tag(child)
            if name == "Identifier" and child.text:
                identifier = child.text.strip()
            elif name in ("SupportedCRS", "CRS") and child.text:
                crs = child.text.strip()
            elif name == "TileMatrix":
                values: dict[str, str] = {}
                for item in child:
                    values[_tag(item)] = (item.text or "").strip()
                top_left = _floats(values.get("TopLeftCorner", "0 0"))
                try:
                    matrices.append(TileMatrix(
                        identifier=values.get("Identifier", ""),
                        scale_denominator=float(values.get("ScaleDenominator", "0")),
                        top_left=(top_left[0], top_left[1]) if len(top_left) >= 2 else (0.0, 0.0),
                        tile_width=int(values.get("TileWidth", DEFAULT_TILE)),
                        tile_height=int(values.get("TileHeight", DEFAULT_TILE)),
                        matrix_width=int(values.get("MatrixWidth", "1")),
                        matrix_height=int(values.get("MatrixHeight", "1")),
                    ))
                except ValueError:
                    continue
        if identifier and matrices:
            sets.append(TileMatrixSet(identifier, normalise_crs(crs),
                                     tuple(matrices)))
    return tuple(sets)


def pick_matrix(matrix_set: TileMatrixSet, pixel_size: float) -> TileMatrix:
    """Poziom najbliższy rozdzielczości ekranu w jednostkach CRS."""
    if not math.isfinite(pixel_size) or pixel_size <= 0:
        raise ValueError("Nieprawidłowa rozdzielczość widoku WMTS.")
    best = None
    for matrix in matrix_set.matrices:
        resolution = matrix.resolution(matrix_set.crs)
        if not math.isfinite(resolution) or resolution <= 0:
            continue
        if best is None or abs(resolution - pixel_size) < abs(
                best.resolution(matrix_set.crs) - pixel_size):
            best = matrix
    if best is None:
        raise ValueError("Zestaw matryc WMTS nie zawiera prawidłowych poziomów.")
    return best


@lru_cache(maxsize=32)
def _crs_axes(crs: str) -> tuple[bool, float]:
    """Czy CRS ma kolejność E,N oraz ile metrów ma jednostka współrzędnych."""
    from pyproj import CRS
    try:
        definition = CRS.from_user_input(crs)
        axes = definition.axis_info
    except Exception as exc:
        raise ValueError("Nie można odczytać osi układu WMTS.") from exc
    directions = tuple(axis.direction.lower() for axis in axes[:2])
    if directions not in {("north", "east"), ("east", "north")}:
        raise ValueError("Nieobsługiwane kierunki osi układu WMTS.")
    factors = tuple(axis.unit_conversion_factor for axis in axes[:2])
    if (not all(math.isfinite(f) and f > 0 for f in factors)
            or not math.isclose(factors[0], factors[1])):
        raise ValueError("Nieobsługiwane jednostki układu WMTS.")
    # OGC: dla kątów używamy długości łuku na równiku elipsoidy.
    metres_per_unit = factors[0]
    if definition.is_geographic:
        metres_per_unit *= definition.ellipsoid.semi_major_metre
    return directions[0] == "east", metres_per_unit


def top_left_east_north(matrix: TileMatrix,
                        crs: str = "EPSG:2180") -> tuple[float, float]:
    """Normalizuje TopLeftCorner zapisany w kolejności osi SupportedCRS.

    Kolejność współrzędnych narożnika nie zmienia kierunków kafelkowania:
    kolumny rosną na wschód, a wiersze na południe. EPSG:2180 zapisuje
    narożnik jako (północ, wschód), np. (850000, 100000).
    """
    first, second = matrix.top_left
    if not all(math.isfinite(v) for v in (first, second)):
        raise ValueError("Nieprawidłowy narożnik matrycy WMTS.")
    east_first, _ = _crs_axes(crs)
    return (first, second) if east_first else (second, first)


def tile_selection(matrix: TileMatrix, min_x: float, min_y: float,
                   max_x: float, max_y: float, *, crs: str = "EPSG:2180"):
    """Kafelki przecinające kadr GEO-MAP (X=północ, Y=wschód).

    Zwraca (col0, row0, col1, row1, swapped). Ostatnia wartość zachowuje
    kształt dotychczasowego API i oznacza tylko zapis narożnika E,N.
    Składanie obrazu powinno używać top_left_east_north(), bez zgadywania
    kierunków na podstawie tej flagi. Brak przecięcia nie wybiera kafla 0,0.
    """
    values = (min_x, min_y, max_x, max_y)
    if (not all(math.isfinite(v) for v in values)
            or min_x >= max_x or min_y >= max_y):
        raise ValueError("Nieprawidłowy zasięg obrazu WMTS.")
    res = matrix.resolution(crs)
    if (not math.isfinite(res) or res <= 0
            or min(matrix.tile_width, matrix.tile_height,
                   matrix.matrix_width, matrix.matrix_height) <= 0):
        raise ValueError("Nieprawidłowa matryca kafelków WMTS.")
    east, north = top_left_east_north(matrix, crs)
    span_east = res * matrix.tile_width
    span_north = res * matrix.tile_height

    def boundary(value):
        # Odejmowanie dużych współrzędnych może przesunąć dokładną granicę
        # o ułamek błędu float (np. 0.99999999999998 zamiast 1).
        nearest = round(value)
        return nearest if abs(value - nearest) <= 1e-9 else value

    # Dolna/prawa granica jest wyłączna: styk krawędzi nie wymaga kafelka
    # z sąsiedniej kolumny lub wiersza.
    col0 = max(0, math.floor(boundary((min_y - east) / span_east)))
    col1 = min(matrix.matrix_width - 1,
               math.ceil(boundary((max_y - east) / span_east)) - 1)
    row0 = max(0, math.floor(boundary((north - max_x) / span_north)))
    row1 = min(matrix.matrix_height - 1,
               math.ceil(boundary((north - min_x) / span_north)) - 1)
    if col0 > col1 or row0 > row1:
        raise ValueError("Obszar widoku znajduje się poza zasięgiem matrycy WMTS.")
    east_first, _ = _crs_axes(crs)
    return col0, row0, col1, row1, east_first


def tile_range(matrix: TileMatrix, min_x: float, min_y: float,
               max_x: float, max_y: float, *,
               crs: str = "EPSG:2180") -> tuple[int, int, int, int]:
    """Zakres kolumn i wierszy przecinających obszar (X=północ, Y=wschód)."""
    col0, row0, col1, row1, _ = tile_selection(matrix, min_x, min_y,
                                               max_x, max_y, crs=crs)
    return col0, row0, col1, row1


def mosaic_origin(matrix: TileMatrix, col0: int, row0: int,
                  swapped: bool | None = None, *,
                  crs: str = "EPSG:2180") -> tuple[float, float]:
    """Lewy górny narożnik mozaiki w kolejności (wschód, północ).

    Argument swapped pozostaje dla zgodności wywołań; kolejność narożnika
    określa wyłącznie SupportedCRS, a nie heurystyka ani kierunek indeksów.
    """
    east, north = top_left_east_north(matrix, crs)
    res = matrix.resolution(crs)
    return (east + col0 * res * matrix.tile_width,
            north - row0 * res * matrix.tile_height)


def gettile_url(base_url: str, layer: str, matrix_set: str, matrix: str,
                row: int, col: int, *, style: str = "default",
                image_format: str = "image/jpeg") -> str:
    params = {
        "SERVICE": "WMTS", "REQUEST": "GetTile", "VERSION": "1.0.0",
        "LAYER": layer, "STYLE": style, "TILEMATRIXSET": matrix_set,
        "TILEMATRIX": matrix, "TILEROW": str(row), "TILECOL": str(col),
        "FORMAT": image_format,
    }
    separator = "&" if "?" in base_url else "?"
    query = "&".join(f"{key}={value}" for key, value in params.items())
    return base_url + separator + query


def capabilities_url(base_url: str) -> str:
    separator = "&" if "?" in base_url else "?"
    return (base_url + separator +
            "SERVICE=WMTS&REQUEST=GetCapabilities&VERSION=1.0.0")
