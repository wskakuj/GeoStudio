"""In-app Google Earth does not need an API key or external browser."""
from __future__ import annotations

import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")

from PySide6.QtCore import Signal, QUrl
from PySide6.QtWidgets import QApplication, QWidget

from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from geostudio.google_preview import GoogleMapsPreviewDialog
from test_geomap import fixture_map


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


class FakeWebEngine(QWidget):
    loadFinished = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.last_url = ""

    def setUrl(self, url: QUrl):
        self.last_url = url.toString()


def test_google_earth_is_an_in_app_web_view_and_never_needs_api_key(
        qt_app, monkeypatch):
    module = types.ModuleType("PySide6.QtWebEngineWidgets")
    module.QWebEngineView = FakeWebEngine
    monkeypatch.setitem(sys.modules, "PySide6.QtWebEngineWidgets", module)
    w = GeoStudioWindow()
    w.doc = GeoMap(fixture_map())
    w.current_crs_epsg = 2180
    w.rebuild_scene(fit=False)
    try:
        d = GoogleMapsPreviewDialog(w)
        assert isinstance(d.web_view, FakeWebEngine)
        assert d.crs.currentData() == 2180
        assert d.web_view.last_url.startswith(
            "https://earth.google.com/web/search/")
        assert "key=" not in d.web_view.last_url
        assert not hasattr(d, "open_browser")
        assert not hasattr(d, "open_earth")
        d.sync_to_current_view()
        assert "earth.google.com" in d.web_view.last_url
        d.close()
    finally:
        w.close()


def test_google_earth_requires_verified_crs_and_no_network_calls(qt_app, monkeypatch):
    module = types.ModuleType("PySide6.QtWebEngineWidgets")
    module.QWebEngineView = FakeWebEngine
    monkeypatch.setitem(sys.modules, "PySide6.QtWebEngineWidgets", module)
    w = GeoStudioWindow()
    w.doc = GeoMap(fixture_map())
    w.current_crs_epsg = None
    try:
        d = GoogleMapsPreviewDialog(w)
        assert isinstance(d.web_view, FakeWebEngine)
        assert d.web_view.last_url == "https://earth.google.com/web/"
        assert d.crs.currentData() is None
        d.close()
    finally:
        w.close()
