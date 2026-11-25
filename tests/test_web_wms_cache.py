"""Cache i keep-alive dla podkładów WMS."""
from __future__ import annotations

from pathlib import Path

import pytest

from geostudio.web_app import underlay_wms


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def test_cache_returns_the_same_bytes(monkeypatch):
    underlay_wms.clear_cache()
    calls = []

    def fake_download(url, max_bytes):
        calls.append(url)
        return PNG

    monkeypatch.setattr(underlay_wms, "_download", fake_download)
    monkeypatch.setattr(underlay_wms, "layers_for",
                        lambda preset, url=None: (type("L", (), {"name": "orto",
                                                      "crs": ["EPSG:2180"]})(),))
    first = underlay_wms.map_png("standard", "orto", 2180, 0, 0, 100, 100, 256, 256)
    second = underlay_wms.map_png("standard", "orto", 2180, 0, 0, 100, 100, 256, 256)
    assert first == second == PNG
    assert len(calls) == 1          # drugie wywołanie z pamięci
    assert underlay_wms.cache_stats()["entries"] == 1


def test_cache_is_bounded(monkeypatch):
    underlay_wms.clear_cache()
    monkeypatch.setattr(underlay_wms, "_download", lambda url, size: PNG)
    monkeypatch.setattr(underlay_wms, "layers_for",
                        lambda preset, url=None: (type("L", (), {"name": "orto",
                                                      "crs": ["EPSG:2180"]})(),))
    monkeypatch.setattr(underlay_wms, "_CACHE_MAX_ENTRIES", 3)
    for step in range(6):
        underlay_wms.map_png("standard", "orto", 2180, step * 10, 0,
                             step * 10 + 10, 10, 128, 128)
    assert underlay_wms.cache_stats()["entries"] <= 3


def test_download_reuses_connection(monkeypatch):
    """Keep-alive: drugie żądanie nie tworzy nowego połączenia."""
    created = []

    class FakeResponse:
        status = 200

        def read(self, size):
            return PNG

    class FakeConnection:
        def __init__(self, host, timeout=15, context=None):
            created.append(host)

        def request(self, method, path, headers=None):
            self.path = path

        def getresponse(self):
            return FakeResponse()

        def close(self):
            pass

    monkeypatch.setattr(underlay_wms.http.client, "HTTPSConnection", FakeConnection)
    underlay_wms._drop_connection("mapy.geoportal.gov.pl")
    url = "https://mapy.geoportal.gov.pl/wss/service/WMS/Orto?SERVICE=WMS"
    underlay_wms._download(url, 1_000_000)
    underlay_wms._download(url, 1_000_000)
    assert len(created) == 1


def test_download_rejects_private_and_insecure_hosts():
    # Od 2.0.48 własny serwer jest dozwolony, ale tylko publiczny i po https.
    with pytest.raises(ValueError):
        underlay_wms._download("https://127.0.0.1/wms", 1000)
    with pytest.raises(ValueError):
        underlay_wms._download("http://example.com/wms", 1000)
    with pytest.raises(ValueError):
        underlay_wms._download("https://192.168.0.10/wms", 1000)
