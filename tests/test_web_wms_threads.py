"""Równoległe pobieranie WMS: każdy wątek ma własne połączenie HTTPS."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from PIL import Image
from io import BytesIO

from geostudio.web_app import underlay_wms


def _png_bytes(width=128, height=128):
    buffer = BytesIO()
    Image.new("RGB", (width, height), (40, 90, 140)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeConnection:
    """Udaje HTTPSConnection i wykrywa użycie tego samego obiektu przez 2 wątki."""

    instances: list["FakeConnection"] = []
    lock = threading.Lock()
    busy: dict[int, int] = {}          # id(połączenia) -> id wątku w trakcie żądania
    shared_violation = False

    def __init__(self, host, timeout=None, context=None):
        self.host = host
        self.closed = False
        with FakeConnection.lock:
            FakeConnection.instances.append(self)

    def request(self, method, path, headers=None):
        thread_id = threading.get_ident()
        with FakeConnection.lock:
            owner = FakeConnection.busy.get(id(self))
            if owner is not None and owner != thread_id:
                # Dwa RÓŻNE wątki na jednym połączeniu — tego nie może być.
                FakeConnection.shared_violation = True
            FakeConnection.busy[id(self)] = thread_id
        time.sleep(0.05)          # symulacja realnego opóźnienia sieci

    def getresponse(self):
        with FakeConnection.lock:
            FakeConnection.busy.pop(id(self), None)

        class Reply:
            status = 200
            def read(self, limit):
                return _png_bytes()
        return Reply()

    def close(self):
        self.closed = True
        with FakeConnection.lock:
            FakeConnection.busy.pop(id(self), None)


def _reset():
    underlay_wms._drop_connection("mapy.geoportal.gov.pl")
    FakeConnection.instances.clear()
    FakeConnection.busy.clear()
    FakeConnection.shared_violation = False


def test_each_thread_gets_its_own_connection(monkeypatch):
    monkeypatch.setattr(underlay_wms, "getproxies", lambda: {})
    monkeypatch.setattr(underlay_wms.http.client, "HTTPSConnection", FakeConnection)
    _reset()
    url = ("https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/"
           "HighResolution?SERVICE=WMS&REQUEST=GetMap&FORMAT=image%2Fpng")
    errors: list[BaseException] = []
    seen: list[int] = []
    guard = threading.Lock()

    def worker():
        try:
            underlay_wms._download(url, 1024)
            with guard:
                seen.append(id(underlay_wms._connection("mapy.geoportal.gov.pl")))
        except BaseException as exc:      # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
    # Dwa wątki => dwa różne połączenia, żadnego współdzielenia.
    assert len(seen) == 2 and len(set(seen)) == 2
    assert len(FakeConnection.instances) == 2
    assert FakeConnection.shared_violation is False


def test_parallel_tiles_do_not_share_a_connection(monkeypatch):
    """Ścieżka kafelkowa: 4 żądania, 2 wątki, zero współdzielonych połączeń."""
    monkeypatch.setattr(underlay_wms, "getproxies", lambda: {})
    monkeypatch.setattr(underlay_wms.http.client, "HTTPSConnection", FakeConnection)
    _reset()
    base = "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/HighResolution"
    bounds = underlay_wms.WMSBounds(0, 0, 2000, 2000)
    data = underlay_wms._fetch_orto_tiles(base, "ortho", "EPSG:2180",
                                          bounds, 256, 256)
    assert data.startswith(b"\xff\xd8")     # sklejony JPEG
    assert FakeConnection.shared_violation is False


def test_accept_header_allows_jpeg():
    source = Path(__file__).resolve().parents[1] / "geostudio/web_app/underlay_wms.py"
    text = source.read_text(encoding="utf-8")
    assert '"Accept": "image/png, image/jpeg, application/xml, text/xml"' in text


def test_connections_are_thread_local():
    source = Path(__file__).resolve().parents[1] / "geostudio/web_app/underlay_wms.py"
    text = source.read_text(encoding="utf-8")
    assert "_CONNECTIONS = threading.local()" in text
    assert "def _thread_pool()" in text
