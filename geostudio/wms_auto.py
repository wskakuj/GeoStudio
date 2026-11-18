"""Continuously track the visible GIS canvas with a debounced WMS GetMap.

No HTTP request is made during mouse movement. A short idle timeout batches
pan/wheel/resize events, cancels outdated requests, and prevents stale replies
from being applied after a different map tab is activated. WMS imagery remains
a read-only, non-selectable background; source .MAP bytes are never modified.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from .wms_service import WMSBounds, getmap_url


@dataclass(frozen=True)
class WMSMapSource:
    base_url: str
    layer: str
    crs: str
    title: str


def visible_getmap_request(view, source: WMSMapSource, *, overscan: float = 0.15):
    """GetMap URL, geographic bounds and pixel dimensions for the visible map.

    The canvas uses scene (X, -Y) where X is northing and Y is easting.
    QGraphicsView displays those scene axes exchanged. A border around the
    viewport (15% on each side) reduces blank slivers while panning.
    """
    rect = view.mapToScene(view.viewport().rect()).boundingRect()
    if rect.isEmpty() or rect.width() <= 0 or rect.height() <= 0:
        raise ValueError("Pusty widok mapy.")
    delta_x = rect.width() * overscan
    delta_y = rect.height() * overscan
    bounds = WMSBounds(
        rect.left() - delta_x, -(rect.bottom() + delta_y),
        rect.right() + delta_x, -(rect.top() - delta_y),
    )
    east = bounds.max_y - bounds.min_y
    north = bounds.max_x - bounds.min_x
    if east <= 0 or north <= 0 or not all(isfinite(v) for v in (east, north)):
        raise ValueError("Nieprawidłowy obszar WMS.")

    # The original scene swaps axes: horizontal viewport pixels correspond
    # to GEO-MAP easting. Preserve its exact geographic aspect ratio.
    scale = max(0.25, min(2.5, float(view.viewport().devicePixelRatioF())))
    width = max(256, round(view.viewport().width() * (1 + 2 * overscan) * scale))
    height = max(128, round(width * north / east))
    if max(width, height) > 2048:
        ratio = 2048 / max(width, height)
        width = max(64, round(width * ratio))
        height = max(64, round(height * ratio))
    width, height = min(2048, width), min(2048, height)
    url = getmap_url(source.base_url, source.layer, source.crs, bounds, width, height)
    return url, bounds


class WMSAutoRefresh(QObject):
    """Own a single live WMS HTTP request for the currently selected map tab."""

    def __init__(self, window, *, debounce_ms: int = 450):
        super().__init__(window)
        self.window = window
        self.network = QNetworkAccessManager(self)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(debounce_ms)
        self.timer.timeout.connect(self.refresh)
        self.pending: QNetworkReply | None = None
        self._generation = 0
        self._inflight_url: str | None = None
        self._completed_url: str | None = None
        self._last_error: tuple[str, str] | None = None

    def viewport_changed(self):
        if self.window.doc and self.window._wms_preview.source is not None:
            self.timer.start()

    def configure(self, source: WMSMapSource):
        """Select live WMS for this document, then fetch the current viewport."""
        self.cancel()
        overlay = self.window._wms_preview
        if overlay.source != source:
            overlay.clear(self.window.map_scene)
        overlay.source = source
        self.refresh(force=True)

    def cancel(self):
        """Stop a tab's old work without clearing its saved raster picture."""
        self.timer.stop()
        self._generation += 1
        reply, self.pending = self.pending, None
        self._inflight_url = None
        self._completed_url = None
        if reply is not None:
            reply.abort()

    def refresh(self, *, force=False):
        if not self.window.doc:
            return
        overlay = self.window._wms_preview
        source = overlay.source
        if source is None:
            return
        try:
            url, bounds = visible_getmap_request(self.window.view, source)
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            self._report_error(str(exc), "")
            return
        if not force and url in (self._inflight_url, self._completed_url):
            return

        # A response to a previous extent may arrive much later; cancel it
        # and use a monotonic generation token to ignore every stale callback.
        if self.pending is not None:
            self.cancel()
        self._generation += 1
        generation = self._generation
        request = QNetworkRequest(QUrl(url))
        request.setTransferTimeout(20_000)
        request.setRawHeader(b"User-Agent", b"GeoStudio WMS viewport")
        reply = self.network.get(request)
        self.pending = reply
        self._inflight_url = url

        def finished():
            is_current = (
                generation == self._generation
                and self.window._wms_preview is overlay
                and overlay.source == source
                and self.pending is reply
            )
            if self.pending is reply:
                self.pending = None
                self._inflight_url = None
            if not is_current:
                reply.deleteLater()
                return
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._report_error(reply.errorString(), url)
            else:
                try:
                    payload = bytes(reply.readAll())
                    if len(payload) > 15_000_000:
                        raise ValueError("WMS: pobrany obraz jest zbyt duży.")
                    overlay.set_image(payload, bounds, source.title)
                    overlay.attach(self.window.map_scene)
                    self.window._update_wms_attribution()
                    self._completed_url = url
                    self._last_error = None
                except (ValueError, TypeError) as exc:
                    self._report_error(str(exc), url)
            reply.deleteLater()

        reply.finished.connect(finished)

    def _report_error(self, reason: str, url: str):
        key = (url, reason)
        if key == self._last_error:
            return
        self._last_error = key
        self.window.status.showMessage(
            "WMS: nie udało się odświeżyć podkładu. " + reason[:230], 9000)
