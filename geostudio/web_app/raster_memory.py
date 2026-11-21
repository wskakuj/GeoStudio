"""Per-user raster calibration store and geometry for grouped tracing."""
from contextlib import closing
from hashlib import sha256
import json
import sqlite3

from shapely.geometry import Polygon
from shapely.ops import unary_union

from .native_picker import preference_file
from .underlay_raster import fit_gcp_payload


def database():
    path = preference_file().with_name("raster-calibrations.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=15)
    con.execute("CREATE TABLE IF NOT EXISTS rasters (digest TEXT PRIMARY KEY, data BLOB NOT NULL)")
    con.execute("""CREATE TABLE IF NOT EXISTS placements
        (map_key TEXT, digest TEXT, settings TEXT NOT NULL, PRIMARY KEY(map_key,digest))""")
    return con


def remember(map_key, settings, data):
    digest = settings["digest"]
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("Nieprawidłowy identyfikator rastra.")
    points = settings["gcps"]
    fit = fit_gcp_payload(points)
    record = dict(name=str(settings["name"])[:255], gcps=points, affine=fit["coefficients"],
                  digest=digest, opacity=min(1, max(0, float(settings.get("opacity", .72)))))
    if data and sha256(data).hexdigest() != digest:
        raise ValueError("Plik rastra nie odpowiada kalibracji.")
    with closing(database()) as con, con:
        if data:
            con.execute("INSERT OR IGNORE INTO rasters VALUES (?,?)", (digest, data))
        elif not con.execute("SELECT 1 FROM rasters WHERE digest=?", (digest,)).fetchone():
            return {"needsImage": True}
        con.execute("INSERT OR REPLACE INTO placements VALUES (?,?,?)",
                    (map_key, digest, json.dumps(record)))
    return {"saved": True}


def placements(map_key):
    with closing(database()) as con:
        return [json.loads(row[0]) for row in con.execute(
            "SELECT settings FROM placements WHERE map_key=? ORDER BY rowid", (map_key,))]


def raster_bytes(map_key, digest):
    with closing(database()) as con:
        row = con.execute("""SELECT data FROM rasters JOIN placements USING(digest)
                             WHERE map_key=? AND digest=?""", (map_key, digest)).fetchone()
        return row[0] if row else None


def merged_ring(rings):
    if not isinstance(rings, list) or not 1 <= len(rings) <= 500:
        raise ValueError("Wskaż od 1 do 500 fragmentów.")
    polygons = []
    for ring in rings:
        if not isinstance(ring, list) or not 3 <= len(ring) <= 500:
            raise ValueError("Nieprawidłowy obrys fragmentu.")
        polygon = Polygon(ring)
        if not polygon.is_valid or polygon.area <= 0:
            raise ValueError("Popraw obrys zaznaczonego fragmentu.")
        polygons.append(polygon)
    merged = unary_union(polygons)
    if merged.geom_type != "Polygon":
        raise ValueError("Zaznaczone fragmenty muszą stykać się bokiem. Uzupełnij zaznaczenie lub odznacz oddzielny fragment.")
    if merged.interiors:
        raise ValueError("Zaznaczenie otacza pominięte pole. Wypełnij otwór lub zmień wybór.")
    points = list(merged.simplify(0).exterior.coords)[:-1]
    if len(points) > 500:
        raise ValueError("Wspólny obrys przekracza limit 500 węzłów.")
    return {"points": points}
