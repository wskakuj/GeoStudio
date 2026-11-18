"""Live WMS follows pan/zoom and ignores obsolete map/network responses.

No real network calls: a stub QNetworkReply verifies cancellation, debounce,
map-tab isolation and the geographic bounds sent to OGC GetMap.
"""
from __future__ import annotations

import os
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QImage
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication

from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from geostudio.wms_auto import WMSAutoRefresh, WMSMapSource, visible_getmap_request
from geostudio.wms_qt import WMSPreviewOverlay
from test_geomap import fixture_map


class StubReply(QObject):
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.aborted = False
        self.data = b""

    def abort(self):
        self.aborted = True
        self.finished.emit()

    def error(self):
        return (QNetworkReply.NetworkError.OperationCanceledError if self.aborted
                else QNetworkReply.NetworkError.NoError)

    def errorString(self):
        return "cancelled" if self.aborted else ""

    def readAll(self):
        return self.data

    def complete(self, content):
        self.data = content
        self.finished.emit()


class StubNetwork:
    def __init__(self):
        self.requests = []
        self.replies = []

    def get(self, request):
        self.requests.append(request.url().toString())
        reply = StubReply()
        self.replies.append(reply)
        return reply


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt_app):
    w = GeoStudioWindow()
    w.doc = GeoMap(fixture_map())
    w.rebuild_scene(fit=False)
    yield w
    w._wms_auto.cancel()
    w.close()


def _source(name="ortofoto"):
    return WMSMapSource(
        "https://maps.example/wms", name, "EPSG:2180", "Ortofotomapa")


def _image_data():
    from PySide6.QtCore import QBuffer, QIODevice
    image = QImage(180, 140, QImage.Format.Format_ARGB32)
    image.fill(QColor("#8daa88"))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(buffer.data())


def test_view_bounds_cover_visible_pixels_with_overscan(window):
    url, bounds = visible_getmap_request(window.view, _source())
    scene_rect = window.view.mapToScene(
        window.view.viewport().rect()).boundingRect()
    assert bounds.min_x < scene_rect.left()
    assert bounds.max_x > scene_rect.right()
    assert bounds.min_y < -scene_rect.bottom()
    assert bounds.max_y > -scene_rect.top()
    params = parse_qs(urlparse(url).query)
    assert params["CRS"] == ["EPSG:2180"]
    assert params["LAYERS"] == ["ortofoto"]
    assert 64 <= int(params["WIDTH"][0]) <= 2048
    assert 64 <= int(params["HEIGHT"][0]) <= 2048
    assert float(params["BBOX"][0].split(",")[0]) == pytest.approx(bounds.min_x)


def test_no_live_source_no_network_even_after_scroll(window):
    stub = StubNetwork()
    controller = window._wms_auto
    controller.network = stub
    window.view.scrollContentsBy(12, 10)
    controller.timer.stop()
    controller.refresh()
    assert stub.requests == []


def test_configure_fetches_map_then_view_change_is_debounced(window):
    controller = window._wms_auto
    stub = StubNetwork()
    controller.network = stub
    controller.configure(_source())
    assert len(stub.requests) == 1
    first = stub.replies[0]
    first.complete(_image_data())
    assert window._wms_preview.image is not None
    assert window._wms_preview.item is not None

    controller.timer.setInterval(20)
    window.view.viewport_changed.emit()
    assert controller.timer.isActive()
    assert len(stub.requests) == 1  # Mouse event must not trigger HTTP.
    controller.timer.stop()
    controller.refresh()  # Same viewport image must be reused.
    assert len(stub.requests) == 1


def test_old_response_is_cancelled_and_cannot_replace_new_view(window):
    controller = window._wms_auto
    stub = StubNetwork()
    controller.network = stub
    controller.configure(_source())
    old = stub.replies[0]

    # Simulate scrolling/zoom by changing the extent seen by the controller.
    window.view.centerOn(600, -700)
    controller.refresh(force=True)
    assert old.aborted
    assert len(stub.requests) == 2
    new = stub.replies[1]
    assert stub.requests[0] != stub.requests[1]

    # A late response from the old request must be completely ignored.
    old.complete(_image_data())
    assert window._wms_preview.image is None
    new.complete(_image_data())
    assert window._wms_preview.item is not None
    assert controller.pending is None


def test_switch_to_other_map_session_disables_old_network_reply(window):
    controller = window._wms_auto
    stub = StubNetwork()
    controller.network = stub
    controller.configure(_source())
    old = stub.replies[-1]
    previous = window._wms_preview
    controller.cancel()
    window._wms_preview = WMSPreviewOverlay()
    old.complete(_image_data())
    assert old.aborted
    assert previous.image is None
    assert window._wms_preview.image is None
    window._wms_preview = previous


def test_user_removes_wms_stops_automatic_downloads(window):
    controller = window._wms_auto
    stub = StubNetwork()
    controller.network = stub
    controller.configure(_source())
    first = stub.replies[-1]
    controller.cancel()
    window._wms_preview.clear(window.map_scene)
    assert first.aborted
    window.view.viewport_changed.emit()
    assert not controller.timer.isActive()
    controller.refresh(force=True)
    assert len(stub.requests) == 1
