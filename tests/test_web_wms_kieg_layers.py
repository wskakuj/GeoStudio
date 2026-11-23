"""GUGiK: tylko warstwa granic i numerów działek."""
from __future__ import annotations

import pytest

from geostudio.web_app import underlay_wms


class _Layer:
    def __init__(self, name, title="", crs=("EPSG:2180",)):
        self.name = name
        self.title = title
        self.crs = list(crs)


def test_kieg_lists_only_parcels(monkeypatch):
    monkeypatch.setattr(underlay_wms, "layers_for", lambda preset, url=None: (
        _Layer("dzialki,numery_dzialek", "Granice i numery działek"),
        _Layer("budynki", "Budynki"),
        _Layer("uzytki", "Użytki"),
    ))
    listed = underlay_wms.list_layers("kieg")
    assert [layer["id"] for layer in listed["layers"]] == ["dzialki,numery_dzialek"]
    assert listed["layers"][0]["epsg"]


def test_other_presets_keep_every_layer(monkeypatch):
    monkeypatch.setattr(underlay_wms, "layers_for", lambda preset, url=None: (
        _Layer("orto_standard", "Ortofoto"),
        _Layer("orto_high", "Ortofoto HD"),
    ))
    listed = underlay_wms.list_layers("standard")
    assert len(listed["layers"]) == 2


def test_kieg_rejects_other_layers():
    with pytest.raises(ValueError):
        underlay_wms.map_png("kieg", "budynki", 2180, 0, 0, 100, 100, 128, 128)
