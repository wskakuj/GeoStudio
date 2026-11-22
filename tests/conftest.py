"""Shared builders for synthetic GEO-MAP v8 maps used across the test suite.

Every byte produced here is generated in code: no client map, no GEO-MAP
library and no personal data ever enters the repository. Tests that need a
realistic file structure can now share one builder instead of repeating
inline fixtures in each module.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

EOL = "\r\n"

# Style string used by GEO-MAP for a freshly created object: colour word plus
# line type and width fields. Kept as a parameter so tests can vary it.
DEFAULT_STYLE = "8553090  15          0"


def point_record(x: float, y: float, kind: int = 1, label: str = "") -> str:
    """One ``P`` vertex record. ``kind=0`` terminates a component."""
    suffix = f",{label}" if label else ""
    return f"P {kind}   {x:.3f}   {y:.3f}{suffix}"


class MapBuilder:
    """Builds a complete, checksum-valid ``ver=[8.00]`` map from scratch."""

    def __init__(self, *, eol: str = EOL, ver: str = " 8.00",
                 ext: tuple[float, float, float, float, float] = (3500.0, 0.0, 0.0, 100.0, 100.0)):
        self.eol = eol
        self.ver = ver
        self.ext = ext
        self._body: list[bytes] = []

    # -- low level -------------------------------------------------------
    def raw(self, line: str) -> "MapBuilder":
        """Append one verbatim record line (no line ending)."""
        self._body.append(line.encode("cp1250") + self.eol.encode())
        return self

    def field(self, key: str, value: str) -> "MapBuilder":
        return self.raw(f":{key}[{value}]")

    # -- objects ---------------------------------------------------------
    def object(self, code: str = "5216", uid: str = "OBJ-1",
               fields: dict[str, str] | None = None,
               points: list[tuple[float, float]] | None = None,
               *, style: str = DEFAULT_STYLE, closed: bool = True,
               labels: list[str] | None = None) -> "MapBuilder":
        """Append a complete object record with ``:ID`` and ``P`` vertices."""
        if points is None:
            points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        if closed and points[0] != points[-1]:
            points = points + [points[0]]
        self.raw(f"*{code} {style}")
        self.raw(f":ID[{uid}]")
        for key, value in (fields or {}).items():
            self.field(key, value)
        for index, (x, y) in enumerate(points):
            label = labels[index] if labels and index < len(labels) else ""
            self.raw(point_record(x, y, 1, label))
        return self

    def multipart(self, code: str = "5216", uid: str = "MP-1") -> "MapBuilder":
        """Object made of two components separated by a ``P 0`` terminator."""
        self.raw(f"*{code} {DEFAULT_STYLE}")
        self.raw(f":ID[{uid}]")
        for x, y in ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)):
            self.raw(point_record(x, y, 1))
        self.raw(point_record(1.0, 1.0, 0))
        for x, y in ((5.0, 5.0), (6.0, 5.0), (6.0, 6.0)):
            self.raw(point_record(x, y, 1))
        self.raw(point_record(6.0, 6.0, 0))
        return self

    # -- output ----------------------------------------------------------
    def build(self, *, trailing_newline: bool = True) -> bytes:
        lines = [self._ext_line()] + self._body
        if not trailing_newline and lines:
            lines[-1] = lines[-1][:-len(self.eol)]
        body = b"".join(lines)
        digest = hashlib.md5(body).hexdigest()
        header = (f";# Plik danych systemu GEO-MAP ver=[{self.ver}]  "
                  f"N=[{len(lines) + 1:12d}] CHK=[{digest}]{self.eol}")
        return header.encode("cp1250") + body

    def _ext_line(self) -> bytes:
        scale, xmin, ymin, xmax, ymax = self.ext
        return (f";# EXT {scale:g} {xmin:.3f} {ymin:.3f} {xmax:.3f} {ymax:.3f} "
                f"#ST=0 CS=9 CM=21{self.eol}").encode("cp1250")


# -- pytest fixtures ------------------------------------------------------
@pytest.fixture
def map_builder() -> type[MapBuilder]:
    """Class fixture so a test can compose any map it needs."""
    return MapBuilder


@pytest.fixture
def simple_map() -> bytes:
    """One closed parcel polygon with a name, a user note and an unknown record."""
    return (MapBuilder()
            .object(uid="DEMO-01", fields={"A2": "TEST", "TX": "uwaga"},
                    points=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
            .raw(":UNKNOWN[retain this]")
            .build())


@pytest.fixture
def map_file(tmp_path: Path, simple_map: bytes) -> Path:
    """``simple_map`` written to a temporary ``.MAP`` file."""
    path = tmp_path / "PRZYKLAD.MAP"
    path.write_bytes(simple_map)
    return path


@pytest.fixture(autouse=True)
def _clear_wms_cache():
    """Cache podkładów nie może przeciekać między testami."""
    try:
        from geostudio.web_app import underlay_wms
        underlay_wms.clear_cache()
    except Exception:
        pass
    yield
