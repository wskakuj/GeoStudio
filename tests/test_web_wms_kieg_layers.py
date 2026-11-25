"""GUGiK: tylko warstwa granic i numerów działek."""
from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

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


def test_kieg_lists_fixed_parcel_layer_without_downloading_catalogue(monkeypatch):
    def no_catalogue(*_args, **_kwargs):
        pytest.fail("The fixed KIEG parcel layer must not wait for GetCapabilities")

    monkeypatch.setattr(underlay_wms, "_download", no_catalogue)

    listed = underlay_wms.list_layers("kieg")

    assert listed["layers"] == [{
        "id": underlay_wms.KIEG_PARCELS,
        "title": "Granice i numery działek",
        "epsg": [2176, 2177, 2178, 2179, 2180],
    }]


@pytest.mark.parametrize("epsg,east,north", [
    (2180, 637231.09, 486786.39),
    (2178, 7500683.201840085, 5788489.838791029),
])
def test_kieg_preview_fetches_parcels_without_catalogue(
        monkeypatch, epsg, east, north):
    """A cold preview goes straight to GetMap, including PL-2000 views."""
    monkeypatch.setenv("GEOSTUDIO_WMS_DISK_CACHE", "0")

    def no_catalogue(*_args, **_kwargs):
        pytest.fail("KIEG preview must not download a catalogue before its image")

    output = BytesIO()
    Image.new("RGBA", (512, 512), (30, 80, 150, 255)).save(output, "PNG")
    png = output.getvalue()
    calls = []

    def parcels(layer, requested_epsg, bounds, width, height):
        calls.append((layer, requested_epsg, bounds, width, height))
        return png

    monkeypatch.setattr(underlay_wms, "_download", no_catalogue)
    monkeypatch.setattr(underlay_wms, "_parcel_image", parcels)

    content, media = underlay_wms.map_image(
        "kieg", underlay_wms.KIEG_PARCELS, epsg,
        east-100, -north-100, east+100, -north+100, 512, 512)

    assert (content, media) == (png, "image/png")
    assert calls == [(
        underlay_wms.KIEG_PARCELS, epsg,
        underlay_wms.WMSBounds(north-100, east-100, north+100, east+100),
        512, 512,
    )]
