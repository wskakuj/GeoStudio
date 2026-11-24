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

    def resolution(self) -> float:
        """Rozmiar piksela w metrach (0,28 mm na jednostkę skali)."""
        return self.scale_denominator * 0.00028


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
    """Poziom, którego piksel jest najbliższy żądanemu (nie gorszy niż 2x)."""
    best = None
    for matrix in matrix_set.matrices:
        if matrix.resolution() <= 0:
            continue
        if best is None or abs(matrix.resolution() - pixel_size) < abs(
                best.resolution() - pixel_size):
            best = matrix
    if best is None:
        raise ValueError("Zestaw matryc WMTS nie zawiera prawidłowych poziomów.")
    return best


def _range_for(matrix: TileMatrix, x0: float, y0: float, x1: float, y1: float,
               *, swapped: bool) -> tuple[int, int, int, int]:
    """Zakres kafelków dla jednej konwencji osi TopLeftCorner.

    x = północ, y = wschód (układ GEO-MAP). `swapped` mówi, jak zapisano
    TopLeftCorner w Capabilities:
      * False: (północ, wschód) — kolumna biegnie po północy,
      * True:  (wschód, północ) — kolumna biegnie po wschodzie.
    W obu przypadkach wiersz rośnie w stronę MALEJĄCEJ drugiej osi.
    """
    res = matrix.resolution()
    first, second = matrix.top_left
    span_x = res * matrix.tile_width
    span_y = res * matrix.tile_height
    if swapped:
        # Kolumna po wschodzie (y), wiersz po malejącej północy (x).
        col0 = math.floor((y0 - first) / span_x)
        col1 = math.floor((y1 - first) / span_x)
        row0 = math.floor((second - x1) / span_y)
        row1 = math.floor((second - x0) / span_y)
    else:
        # Kolumna po północy (x), wiersz po malejącym wschodzie (y).
        col0 = math.floor((x0 - first) / span_x)
        col1 = math.floor((x1 - first) / span_x)
        row0 = math.floor((second - y1) / span_y)
        row1 = math.floor((second - y0) / span_y)
    return col0, row0, col1, row1


def _range_for_mirror(matrix: TileMatrix, x0: float, y0: float,
                      x1: float, y1: float, *, swapped: bool):
    """Wariant „odbity”: TopLeftCorner podaje MINIMUM osi, a nie maksimum.

    Niektóre usługi WMTS zapisują w TopLeftCorner (północ_min, wschód_min)
    albo (wschód_min, północ_min). Wtedy oba podstawowe warianty dają ujemne
    indeksy, kod przycinał je do kafelka (0, 0) i wracał czarny obraz.
    """
    res = matrix.resolution()
    first, second = matrix.top_left
    span_x = res * matrix.tile_width
    span_y = res * matrix.tile_height
    if swapped:
        col0 = math.floor((y0 - first) / span_x)
        col1 = math.floor((y1 - first) / span_x)
        row0 = math.floor((x0 - second) / span_y)
        row1 = math.floor((x1 - second) / span_y)
    else:
        col0 = math.floor((x0 - first) / span_x)
        col1 = math.floor((x1 - first) / span_x)
        row0 = math.floor((y0 - second) / span_y)
        row1 = math.floor((y1 - second) / span_y)
    return col0, row0, col1, row1


def _range_valid(matrix: TileMatrix, box: tuple[int, int, int, int]) -> bool:
    col0, row0, col1, row1 = box
    return (0 <= col0 <= col1 < matrix.matrix_width and
            0 <= row0 <= row1 < matrix.matrix_height)


def tile_selection(matrix: TileMatrix, min_x: float, min_y: float,
                   max_x: float, max_y: float):
    """(col0, row0, col1, row1, swapped) — zakres i wykryta konwencja osi."""
    candidates = []
    # Cztery konwencje: (północ, wschód) i (wschód, północ), każda w wariancie
    # „TopLeftCorner = maksimum” oraz „= minimum”. Wybieramy pierwszą, która
    # mieści się w macierzy — zamiast przycinać ujemne indeksy do (0, 0).
    for swapped in (False, True):
        box = _range_for(matrix, min_x, min_y, max_x, max_y, swapped=swapped)
        if _range_valid(matrix, box):
            candidates.append((*box, swapped))
    if candidates:
        return candidates[0]
    for swapped in (False, True):
        box = _range_for_mirror(matrix, min_x, min_y, max_x, max_y,
                                swapped=swapped)
        if _range_valid(matrix, box):
            return (*box, swapped)
    box = _range_for(matrix, min_x, min_y, max_x, max_y, swapped=False)
    col0, row0, col1, row1 = box
    col0 = max(0, min(col0, matrix.matrix_width - 1))
    row0 = max(0, min(row0, matrix.matrix_height - 1))
    col1 = max(col0, min(col1, matrix.matrix_width - 1))
    row1 = max(row0, min(row1, matrix.matrix_height - 1))
    return col0, row0, col1, row1, False


def tile_range(matrix: TileMatrix, min_x: float, min_y: float,
               max_x: float, max_y: float) -> tuple[int, int, int, int]:
    """Zakres kolumn i wierszy kafelków pokrywających obszar.

    Kolejność osi w TopLeftCorner bywa różna (północ-wschód albo
    wschód-północ), więc sprawdzamy obie konwencje i wybieramy tę, która
    mieści się w macierzy. Inaczej serwer odpowiada „Row is out of range”.
    """
    col0, row0, col1, row1, _ = tile_selection(matrix, min_x, min_y,
                                               max_x, max_y)
    return col0, row0, col1, row1


def mosaic_origin(matrix: TileMatrix, col0: int, row0: int,
                  swapped: bool) -> tuple[float, float]:
    """Lewy górny narożnik mozaiki jako (oś kolumn, oś wierszy).

    Oś kolumn to północ, oś wierszy to wschód — niezależnie od tego, w jakiej
    kolejności serwer podał TopLeftCorner.
    """
    res = matrix.resolution()
    first, second = matrix.top_left
    span_x = res * matrix.tile_width
    span_y = res * matrix.tile_height
    if swapped:
        return (second + col0 * span_x, first - row0 * span_y)
    return (first + col0 * span_x, second - row0 * span_y)


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
