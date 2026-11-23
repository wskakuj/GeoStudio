"""Ortofoto: odwrót JPEG->PNG i kafelki->jedno żądanie zamiast błędu."""
from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from geostudio.web_app import underlay_wms


def _png(width=64, height=64):
    buffer = BytesIO()
    Image.new("RGB", (width, height), (30, 90, 160)).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg(width=64, height=64):
    buffer = BytesIO()
    Image.new("RGB", (width, height), (30, 90, 160)).save(buffer, format="JPEG")
    return buffer.getvalue()


class Layer:
    name = "ortho"
    crs = ["EPSG:2180"]


def test_png_is_tried_first_and_jpeg_later(monkeypatch):
    """Kolejność prób: PNG (zachowanie sprzed 2.0.30), potem JPEG."""
    seen = []

    def download(url, max_bytes):
        seen.append(url)
        return _png()

    monkeypatch.setattr(underlay_wms, "_download", download)
    monkeypatch.setattr(underlay_wms, "layers_for", lambda preset, url=None: [Layer()])
    underlay_wms.clear_cache()
    data, media = underlay_wms.map_image("standard", "ortho", 2180, 0, 0, 100, 100, 256, 256)
    assert media == "image/png"
    assert "FORMAT=image%2Fpng" in seen[0] or "FORMAT=image/png" in seen[0]


def test_tiling_failure_falls_back_to_single_request(monkeypatch):
    calls = []

    def download(url, max_bytes):
        calls.append(url)
        return _png(1600, 1600)

    monkeypatch.setattr(underlay_wms, "_download", download)
    monkeypatch.setattr(underlay_wms, "layers_for", lambda preset, url=None: [Layer()])
    underlay_wms.clear_cache()
    data, media = underlay_wms.map_image("standard", "ortho", 2180, 0, 0, 2000, 2000, 1600, 1600)
    assert media == "image/png"
    assert Image.open(BytesIO(data)).size == (1600, 1600)
    assert len(calls) == 1        # jedno żądanie, bez kafelków


def test_service_exception_message_is_readable():
    message = underlay_wms._service_exception(
        b"<ServiceExceptionReport><ServiceException>Layer not defined</ServiceException></ServiceExceptionReport>")
    assert "Layer not defined" in message


def test_orto_tries_versions_and_formats_in_order(monkeypatch):
    """PNG 1.1.1 -> PNG 1.3.0 -> JPEG 1.1.1 -> JPEG 1.3.0, potem kafelki."""
    assert [a[0] for a in underlay_wms.ORTO_ATTEMPTS] == ["1.1.1", "1.3.0",
                                                          "1.1.1", "1.3.0"]
    assert [a[1] for a in underlay_wms.ORTO_ATTEMPTS] == [
        "image/png", "image/png", "image/jpeg", "image/jpeg"]


def test_last_error_message_is_the_service_exception(monkeypatch):
    def download(url, max_bytes):
        return (b"<ServiceExceptionReport><ServiceException>Layer not defined"
                b"</ServiceException></ServiceExceptionReport>")

    monkeypatch.setattr(underlay_wms, "_download", download)
    monkeypatch.setattr(underlay_wms, "layers_for", lambda preset, url=None: [Layer()])
    underlay_wms.clear_cache()
    with pytest.raises(RuntimeError, match="Layer not defined"):
        underlay_wms.map_image("standard", "ortho", 2180, 0, 0, 100, 100, 256, 256)
