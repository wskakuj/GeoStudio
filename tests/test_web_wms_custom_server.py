"""Własny serwer WMS: walidacja adresu, warstwy i obraz."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from geostudio.web_app import underlay_wms

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
HTML = Path("geostudio/web_app/static/index.html").read_text(encoding="utf-8")

CAPABILITIES = b"""<?xml version="1.0"?>
<WMS_Capabilities version="1.3.0"><Capability><Layer><Layer>
  <Name>ortofoto</Name><Title>Ortofoto wlasna</Title>
  <CRS>EPSG:2180</CRS>
</Layer></Layer></Capability></WMS_Capabilities>"""


def _png(width=64, height=64):
    buffer = BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_custom_url_must_be_https():
    with pytest.raises(ValueError, match="https"):
        underlay_wms.validate_service_url("http://serwer.pl/wms")


@pytest.mark.parametrize("url", [
    "https://localhost/wms",
    "https://127.0.0.1/wms",
    "https://10.0.0.5/wms",
    "https://192.168.1.10/wms",
    "https://169.254.169.254/latest",
])
def test_private_addresses_are_blocked(url):
    with pytest.raises(ValueError, match="lokalne"):
        underlay_wms.validate_service_url(url)


def test_public_address_is_accepted():
    url = "https://wms.example.org/geoserver/wms"
    assert underlay_wms.validate_service_url(url) == url


def test_layers_come_from_the_custom_server(monkeypatch):
    monkeypatch.setattr(underlay_wms, "_download",
                        lambda url, size: CAPABILITIES)
    result = underlay_wms.list_layers("custom", "https://wms.example.org/wms")
    assert result["layers"][0]["id"] == "ortofoto"
    assert result["preset"] == "custom"


def test_image_is_fetched_from_the_custom_server(monkeypatch):
    seen = []

    def download(url, size):
        seen.append(url)
        if "GetCapabilities" in url or "request=GetCapabilities" in url.lower():
            return CAPABILITIES
        return _png()

    monkeypatch.setattr(underlay_wms, "_download", download)
    underlay_wms.clear_cache()
    data, media = underlay_wms.map_image(
        "custom", "ortofoto", 2180, 0, 0, 100, 100, 256, 256,
        "https://wms.example.org/wms")
    assert media == "image/png"
    assert any("wms.example.org" in url for url in seen)


def test_ui_exposes_custom_server_option():
    assert '<option value="custom">Własny serwer WMS…</option>' in HTML
    assert 'id="underlay-url" type="text"' in HTML
    assert "function currentWmsUrl()" in JS
    assert 'params.set("url",currentWmsUrl());' in JS
