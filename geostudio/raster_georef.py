"""Raster ground-control-point georeferencing; independent of the Qt user interface.

Pixel (u, v) represents the image coordinate, with v increasing downwards.
World (X, Y) uses the original GEO-MAP coordinates, not Qt scene coordinates.
The fitted six-parameter affine transformation is:
    X = a*u + b*v + c
    Y = d*u + e*v + f
At least three non-collinear GCP pairs are required; additional pairs form a
least-squares fit and report per-point residuals plus RMSE in map units.

The engine deliberately never edits source .MAP data.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite, sqrt
from pathlib import Path


@dataclass(frozen=True)
class GroundControlPoint:
    u: float
    v: float
    x: float
    y: float


@dataclass(frozen=True)
class AffineFit:
    coefficients: tuple[float, float, float, float, float, float]
    residuals: tuple[float, ...]
    rmse: float

    def world_at(self, u: float, v: float) -> tuple[float, float]:
        a, b, c, d, e, f = self.coefficients
        return a * u + b * v + c, d * u + e * v + f


def _solve_3x3(matrix: list[list[float]], vector: list[float]) -> tuple[float, float, float]:
    """Partial-pivot elimination, with explicit singularity detection."""
    a = [list(row) + [value] for row, value in zip(matrix, vector)]
    reference = max(abs(x) for row in a for x in row[:3])
    if reference == 0 or not isfinite(reference):
        raise ValueError("Punkty kalibracyjne są współliniowe lub powtarzają się.")
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(a[row][column]))
        if abs(a[pivot][column]) < reference * 1e-10:
            raise ValueError("Punkty rastra są współliniowe; wybierz punkty w różnych częściach obrazu.")
        a[column], a[pivot] = a[pivot], a[column]
        divisor = a[column][column]
        for k in range(column, 4):
            a[column][k] /= divisor
        for row in range(3):
            if row == column:
                continue
            factor = a[row][column]
            for k in range(column, 4):
                a[row][k] -= factor * a[column][k]
    return a[0][3], a[1][3], a[2][3]


def fit_affine(points: list[GroundControlPoint] | tuple[GroundControlPoint, ...]) -> AffineFit:
    """Fit an affine mapping raster pixels → GEO-MAP X/Y with 3+ point pairs.

    This is a global affine fit (translation, rotation, scale and shear). It
    cannot perfectly rectify a warped scan; inspect residuals before tracing.
    """
    points = tuple(points)
    if len(points) < 3:
        raise ValueError("Wybierz co najmniej trzy pary punktów kalibracyjnych.")
    if len(points) > 500:
        raise ValueError("Zbyt wiele punktów kontrolnych (maksymalnie 500).")
    if any(not all(isfinite(z) for z in (p.u, p.v, p.x, p.y)) for p in points):
        raise ValueError("Współrzędne punktów muszą być skończonymi liczbami.")
    n = len(points)
    mu = sum(p.u for p in points) / n
    mv = sum(p.v for p in points) / n
    mx = sum(p.x for p in points) / n
    my = sum(p.y for p in points) / n
    su = max(abs(p.u - mu) for p in points)
    sv = max(abs(p.v - mv) for p in points)
    if su <= 1e-12 or sv <= 1e-12:
        raise ValueError("Wybierz punkty rozłożone po całym rastrze.")
    rows = [(1.0, (p.u - mu) / su, (p.v - mv) / sv) for p in points]
    normal = [[sum(row[i] * row[j] for row in rows) for j in range(3)]
              for i in range(3)]
    targets_x = [p.x - mx for p in points]
    targets_y = [p.y - my for p in points]
    px = _solve_3x3(normal, [sum(row[i] * z for row, z in zip(rows, targets_x))
                             for i in range(3)])
    py = _solve_3x3(normal, [sum(row[i] * z for row, z in zip(rows, targets_y))
                             for i in range(3)])
    a, b = px[1] / su, px[2] / sv
    d, e = py[1] / su, py[2] / sv
    c = mx + px[0] - a * mu - b * mv
    f = my + py[0] - d * mu - e * mv
    coefficients = (a, b, c, d, e, f)
    if not all(isfinite(value) for value in coefficients):
        raise ValueError("Kalibracja dała nieprawidłowe współczynniki.")
    if abs(a * e - b * d) <= 1e-14 * max(1.0, abs(a * e), abs(b * d)):
        raise ValueError("Kalibracja spłaszczyłaby raster; sprawdź punkty na mapie.")
    errors = tuple(hypot(a * p.u + b * p.v + c - p.x,
                         d * p.u + e * p.v + f - p.y) for p in points)
    return AffineFit(coefficients, errors,
                     sqrt(sum(error * error for error in errors) / n))


def parse_world_file(path: str | Path) -> tuple[float, float, float, float, float, float]:
    """Read ESRI world file coefficients, correcting pixel-centre to corner.

    World order: A,D,B,E,C,F; output order: a,b,c,d,e,f.
    """
    rows = Path(path).read_text(encoding="utf-8-sig").splitlines()
    if len(rows) < 6:
        raise ValueError("Plik world musi mieć sześć współczynników.")
    try:
        a, d, b, e, c, f = (float(value.strip()) for value in rows[:6])
    except ValueError as exc:
        raise ValueError("Plik world zawiera nieprawidłowe liczby.") from exc
    if not all(isfinite(z) for z in (a, b, c, d, e, f)):
        raise ValueError("Plik world zawiera nieprawidłowe liczby.")
    return a, b, c - (a + b) / 2, d, e, f - (d + e) / 2


def find_world_file(image_path: str | Path) -> Path | None:
    """Check common ESRI sidecars (case-insensitively), not arbitrary folders."""
    path = Path(image_path)
    suffix = path.suffix.lower().lstrip(".")
    variants = [suffix[:1] + suffix[-1:] + "w", suffix[:1] + "w", "wld"]
    if suffix in {"tif", "tiff"}:
        variants.insert(0, "tfw")
    if suffix in {"jpg", "jpeg"}:
        variants.insert(0, "jgw")
    if suffix == "png":
        variants.insert(0, "pgw")
    known = set(variants)
    try:
        entries = {p.suffix.lower().lstrip("."): p for p in path.parent.iterdir()
                   if p.is_file() and p.stem.casefold() == path.stem.casefold()}
    except OSError:
        return None
    for ext in variants:
        if ext in known and ext in entries:
            return entries[ext]
    return None
