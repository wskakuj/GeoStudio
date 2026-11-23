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


def test_jpeg_rejected_falls_back_to_png(monkeypatch):
    seen = []

    def download(url, max_bytes):
        seen.append(url)
        if "FORMAT=image%2Fjpeg" in url or "FORMAT=image/jpeg" in url:
            # Geoportal odsyła komunikat błędu zamiast obrazu.
            return b"<ServiceExceptionReport><ServiceException>Bad FORMAT</ServiceException></ServiceExceptionReport>"
        return _png()

    monkeypatch.setattr(underlay_wms, "_download", download)
    monkeypatch.setattr(underlay_wms, "layers_for", lambda preset: [Layer()])
    underlay_wms.clear_cache()
    data, media = underlay_wms.map_image("standard", "ortho", 2180, 0, 0, 100, 100, 256, 256)
    assert data.startswith(b"\xff\xd8")          # klient dostaje JPEG
    assert any("FORMAT=image%2Fpng" in url or "FORMAT=image/png" in url for url in seen)


def test_tiling_failure_falls_back_to_single_request(monkeypatch):
    calls = []

    def download(url, max_bytes):
        calls.append(url)
        # Pierwsze cztery żądania (kafelki) padają, potem pojedyncze działa.
        if len(calls) <= 4:
            raise RuntimeError("połączenie zerwane")
        return _jpeg(1600, 1600)

    monkeypatch.setattr(underlay_wms, "_download", download)
    monkeypatch.setattr(underlay_wms, "layers_for", lambda preset: [Layer()])
    underlay_wms.clear_cache()
    data, media = underlay_wms.map_image("standard", "ortho", 2180, 0, 0, 2000, 2000, 1600, 1600)
    assert media == "image/jpeg"
    assert Image.open(BytesIO(data)).size == (1600, 1600)
    assert len(calls) > 4          # po kafelkach było jeszcze jedno żądanie


def test_service_exception_message_is_readable():
    message = underlay_wms._service_exception(
        b"<ServiceExceptionReport><ServiceException>Layer not defined</ServiceException></ServiceExceptionReport>")
    assert "Layer not defined" in message
