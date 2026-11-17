"""Conservative Polish projected-coordinate conversion using PROJ / pyproj.

GEO-MAP records use X=northing, Y=easting. PROJ's always_xy expects
(easting, northing), so swap both input and output axes.
"""
from __future__ import annotations

from functools import lru_cache
from math import isfinite
from pathlib import Path

from .geomap import GeoMap, POINT_RE, EXT_RE

# Only codes with authoritative projected EPSG definitions are offered.
# Warsaw-25/75, local Poznań and ambiguous 1942 variants intentionally absent.
CRS_CHOICES = (
    ("Układ 1992 / 19° — EPSG:2180", 2180),
    ("Układ 2000, strefa 5 — EPSG:2176", 2176),
    ("Układ 2000, strefa 6 — EPSG:2177", 2177),
    ("Układ 2000, strefa 7 — EPSG:2178", 2178),
    ("Układ 2000, strefa 8 — EPSG:2179", 2179),
    ("Układ 1965, strefa I — EPSG:2171 (historyczny)", 2171),
    ("Układ 1965, strefa II — EPSG:2172 (historyczny)", 2172),
    ("Układ 1965, strefa III — EPSG:2173 (historyczny)", 2173),
    ("Układ 1965, strefa IV — EPSG:2174 (historyczny)", 2174),
    ("Układ 1965, strefa V — EPSG:2175 (historyczny)", 2175),
)
KNOWN_EPSG = frozenset(code for _,code in CRS_CHOICES)
MODERN_EPSG = frozenset((2180,2176,2177,2178,2179))


@lru_cache(maxsize=48)
def _transformer(source_epsg: int, target_epsg: int):
    """Cache projection objects, never silently permit ballpark operations."""
    if source_epsg not in KNOWN_EPSG or target_epsg not in KNOWN_EPSG:
        raise ValueError("Nieobsługiwany układ EPSG. Układy lokalne wymagają zweryfikowanych parametrów.")
    try:
        from pyproj import Transformer
        return Transformer.from_crs(
            f"EPSG:{source_epsg}", f"EPSG:{target_epsg}",
            always_xy=True, allow_ballpark=False)
    except Exception as exc:
        raise ValueError("Brak pewnej operacji PROJ dla tych układów; sprawdź siatki transformacyjne.") from exc


def transform_xy(x: float, y: float,
                 source_epsg: int, target_epsg: int) -> tuple[float,float]:
    """Transform GEO-MAP (X northing, Y easting) to a different EPSG system."""
    if not (isfinite(x) and isfinite(y)):
        raise ValueError("Współrzędne muszą być skończonymi liczbami.")
    if source_epsg == target_epsg:
        return float(x),float(y)
    east,north = _transformer(source_epsg,target_epsg).transform(y,x,errcheck=True)
    if not (isfinite(east) and isfinite(north)):
        raise ValueError("Transformacja dała niepoprawne współrzędne.")
    return north,east


def transform_map_copy(document: GeoMap, source_epsg: int, target_epsg: int) -> GeoMap:
    """In-memory conversion of all P records; not a certified cartographic reprojection.

    GEO-MAP page ornaments and symbols use coordinates too. Reprojecting
    every point can change page layout and measurements; caller must
    explicitly warn user and write ONLY a new file, never source data.
    Restrict whole-map conversion to the modern verified EPSG CRS family.
    """
    if source_epsg not in MODERN_EPSG or target_epsg not in MODERN_EPSG:
        raise ValueError("Eksport całej MAP obsługuje na razie tylko PL-1992 i PL-2000 (strefy 5–8).")
    if source_epsg == target_epsg:
        raise ValueError("Wybierz dwa różne układy współrzędnych.")
    if not document.checksum_valid:
        raise ValueError("Nieprawidłowa suma MD5 źródłowej MAP — transformacja przerwana.")

    lines=list(document.lines)
    all_x=[]
    all_y=[]
    changed=0
    memo={}
    for index,original in enumerate(lines):
        line=original.rstrip(b"\r\n")
        if not line.startswith(b"P "):
            continue
        point=POINT_RE.match(line)
        if point is None:
            raise ValueError(f"Nieznany rekord P w linii {index+1}; odmowa konwersji.")
        x,y=float(point.group(2)),float(point.group(3))
        key=x,y
        if key not in memo:
            memo[key]=transform_xy(x,y,source_epsg,target_epsg)
        newx,newy=memo[key]
        if not (-1e9<newx<1e9 and -1e9<newy<1e9):
            raise ValueError("Wynik poza rozsądnym zakresem metrycznym.")
        all_x.append(newx); all_y.append(newy)
        # Preserve P 0/P 1 indicators, descriptions and original EOL bytes.
        a,b=point.span(2),point.span(3)
        converted=(original[:a[0]] + f"{newx:.3f}".encode('ascii')
                   + original[a[1]:b[0]] + f"{newy:.3f}".encode('ascii')
                   + original[b[1]:])
        lines[index]=converted
        changed+=1
    if changed==0:
        raise ValueError("MAP nie zawiera punktów P do transformacji.")
    if len(lines)>1:
        m=EXT_RE.match(lines[1])
        if m:
            xmin,xmax=min(all_x),max(all_x)
            ymin,ymax=min(all_y),max(all_y)
            # Convert the EXT bounding box to the target CRS. Keep its
            # unknown leading parameter and tail exactly as they were.
            values=(xmin,ymin,xmax,ymax)
            for group in (4,3,2,1):
                start,end=m.span(group)
                lines[1]=lines[1][:start]+f"{values[group-1]:.3f}".encode('ascii')+lines[1][end:]

    doc=GeoMap(b''.join(lines),filename="")
    # Newly converted records need a refreshed checksum / line count.
    doc=GeoMap(doc.to_bytes(),filename="")
    if len(doc.objects)!=len(document.objects):
        raise ValueError("Liczba rekordów obiektów zmieniła się — konwersja przerwana.")
    if sum(len(o.points) for o in doc.objects) != sum(len(o.points) for o in document.objects):
        raise ValueError("Liczba współrzędnych zmieniła się — konwersja przerwana.")
    if not doc.checksum_valid:
        raise ValueError("Błąd sumy kontrolnej przeliczonej mapy.")
    return doc


def output_prj_text(target_epsg: int) -> str:
    """WKT sidecar for the exported MAP; GEO-MAP may ignore this file."""
    if target_epsg not in MODERN_EPSG:
        raise ValueError("Niezweryfikowany docelowy układ CRS.")
    from pyproj import CRS
    return CRS.from_epsg(target_epsg).to_wkt()


def transform_label_positions(positions: dict, source_epsg: int, target_epsg: int) -> dict:
    """Copy and transform GeoStudio sidecar label coordinates, if any."""
    transformed={}
    for uid, labels in positions.items():
        transformed[uid]={}
        for field, pair in labels.items():
            x,y=transform_xy(float(pair[0]),float(pair[1]),source_epsg,target_epsg)
            transformed[uid][field]=[round(x,3),round(y,3)]
    return transformed


def detected_crs_from_prj(map_path: str | Path) -> int | None:
    """Only trust a valid accompanying WKT PRJ, never infer from coordinates."""
    prj=Path(map_path).with_suffix('.prj')
    if not prj.is_file():
        return None
    try:
        from pyproj import CRS
        code=CRS.from_wkt(prj.read_text(encoding='utf-8')).to_epsg()
        return code if code in KNOWN_EPSG else None
    except Exception:
        return None
