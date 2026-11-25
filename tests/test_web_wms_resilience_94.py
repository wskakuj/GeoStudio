"""Odporność WMS: zerwane keep-alive, bramka 502, błąd certyfikatu TLS."""
from __future__ import annotations

import http.client
import ssl
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from geostudio.web_app import underlay_wms  # noqa: E402

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


class _Reply:
    def __init__(self, status=200, body=b"obraz"):
        self.status = status
        self._body = body

    def read(self, _limit=None):
        return self._body


class _Conn:
    def __init__(self, script):
        self.script = script

    def request(self, *args, **kwargs):
        pass

    def getresponse(self):
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def close(self):
        pass


def _patch(monkeypatch, script):
    calls = []
    shared = list(script)          # jedna kolejka dla wszystkich prób

    def connection(host, *, relaxed=False):
        calls.append(relaxed)
        return _Conn(shared)

    monkeypatch.setattr(underlay_wms, "_connection", connection)
    monkeypatch.setattr(underlay_wms, "_drop_connection",
                        lambda host, relaxed=False: None)
    monkeypatch.setattr(underlay_wms.time, "sleep", lambda _s: None)
    return calls


URL = "https://mapy.geoportal.gov.pl/wss/service/test"


def test_remote_disconnected_is_retried(monkeypatch):
    _patch(monkeypatch, [http.client.RemoteDisconnected("closed"), _Reply()])
    assert underlay_wms._download(URL, 10_000) == b"obraz"


def test_gateway_error_is_retried(monkeypatch):
    _patch(monkeypatch, [_Reply(502), _Reply()])
    assert underlay_wms._download(URL, 10_000) == b"obraz"


def test_gateway_error_has_a_clear_message(monkeypatch):
    _patch(monkeypatch, [_Reply(502), _Reply(503), _Reply(504), _Reply(502)])
    with pytest.raises(RuntimeError) as info:
        underlay_wms._download(URL, 10_000)
    assert "502" in str(info.value)


def test_certificate_error_falls_back_to_relaxed_tls(monkeypatch):
    calls = _patch(monkeypatch, [ssl.SSLCertVerificationError("brak CA"),
                                 _Reply()])
    assert underlay_wms._download(URL, 10_000) == b"obraz"
    assert calls == [False, True]        # druga próba bez weryfikacji


def test_certificate_error_reports_when_even_relaxed_fails(monkeypatch):
    _patch(monkeypatch, [ssl.SSLCertVerificationError("x")] * 4)
    with pytest.raises(RuntimeError) as info:
        underlay_wms._download(URL, 10_000)
    assert "SSLCertVerificationError" in str(info.value)


def test_tls_contexts_exist():
    strict, relaxed = underlay_wms._tls_contexts()
    assert strict.verify_mode == ssl.CERT_REQUIRED
    assert relaxed.verify_mode == ssl.CERT_NONE
    assert relaxed.check_hostname is False


def test_gcp_magnet_and_crosshair_in_client():
    assert "function gcpSnapPoint(world,altKey){" in JS
    assert "const GCP_SNAP_PX=26;" in JS
    assert "function paintCrosshair(){" in JS
    assert 'for(const [color,width] of [["#0b1a26",3],["#ffffff",1.4]])' in JS
    assert "paintCrosshair();" in JS
