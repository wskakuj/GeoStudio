"""Exercise real WMS request orchestration with a controlled upstream.

These regressions used to turn one failed frame into forty HTTP attempts,
fetch capabilities before every custom-server cache hit, and download an
identical frame twice when requests overlapped. No live service is needed.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import http.client
from io import BytesIO
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from PIL import Image
import pytest

from geostudio.web_app import underlay_wms as wms
from geostudio.wms_service import WMSLayerInfo


CAPABILITIES = b"""<WMS_Capabilities version="1.3.0">
  <Capability><Layer><Name>Raster</Name><Title>Test imagery</Title>
    <CRS>EPSG:2180</CRS>
  </Layer></Capability>
</WMS_Capabilities>"""
CUSTOM_URL = "https://wms-budget-test.example/wms"
LAYER = WMSLayerInfo("Raster", "Test imagery", ("EPSG:2180",))


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGBA", (256, 256), (70, 110, 150, 128)).save(output, "PNG")
    return output.getvalue()


def _frame(preset="standard", *, east=400000):
    return wms.map_image(
        preset, "Raster", 2180,
        east, -501000, east + 1000, -500000, 256, 256,
        CUSTOM_URL if preset == "custom" else None,
    )


class _Clock:
    def __init__(self):
        self.elapsed = 0.0
        self.lock = threading.Lock()

    def monotonic(self):
        with self.lock:
            return self.elapsed

    def advance(self, seconds):
        with self.lock:
            self.elapsed += seconds


class _Reply:
    status = 200

    def __init__(self, content):
        self.content = content

    def read(self, _limit):
        return self.content


@pytest.mark.parametrize("preset,capabilities_seconds", [
    ("standard", 0),
    ("custom", 7),
])
def test_frame_timeout_is_bounded_across_capabilities_and_fallbacks(
        monkeypatch, preset, capabilities_seconds):
    """A socket timeout must not restart the full budget for each fallback."""
    clock = _Clock()
    requests = []

    class Connection:
        def __init__(self, host, *, timeout=None, **_kwargs):
            self.timeout = timeout or wms._timeout_for(host)
            self.sock = self

        def settimeout(self, seconds):
            self.timeout = seconds

        def request(self, _method, path, headers=None):
            self.operation = parse_qs(urlsplit(path).query)["REQUEST"][0]
            requests.append(self.operation)

        def getresponse(self):
            if self.operation == "GetCapabilities":
                clock.advance(capabilities_seconds)
                return _Reply(CAPABILITIES)
            # Simulate a server that uses up the timeout assigned to this
            # connection. The test does not sleep or contact the internet.
            clock.advance(self.timeout)
            raise TimeoutError("simulated upstream timeout")

        def close(self):
            pass

    wms.layers_for.cache_clear()
    monkeypatch.setattr(wms, "_connection", Connection)
    monkeypatch.setattr(wms, "_drop_connection", lambda *a, **kw: None)
    monkeypatch.setattr(wms.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(wms.time, "sleep", clock.advance)

    with pytest.raises(RuntimeError):
        _frame(preset)

    assert clock.elapsed <= 35.001
    assert 1 <= requests.count("GetMap") <= 2
    assert requests.count("GetCapabilities") == 1


def test_a_stale_keepalive_is_retried_and_returns_the_frame(monkeypatch):
    """Bounding slow requests must preserve recovery from a closed socket."""
    calls = []
    image = _png()

    class Connection:
        timeout = 30
        sock = None

        def request(self, _method, path, headers=None):
            calls.append(path)

        def getresponse(self):
            if len(calls) == 1:
                raise http.client.RemoteDisconnected("stale keep-alive")
            return _Reply(image)

        def close(self):
            pass

    monkeypatch.setattr(wms, "layers_for", lambda *a, **kw: (LAYER,))
    monkeypatch.setattr(wms, "_connection", lambda *a, **kw: Connection())
    monkeypatch.setattr(wms, "_drop_connection", lambda *a, **kw: None)
    monkeypatch.setattr(wms.time, "sleep", lambda _seconds: None)

    data, media = _frame()

    assert Image.open(BytesIO(data)).size == (256, 256)
    assert media in {"image/png", "image/jpeg"}
    assert len(calls) == 2
    assert calls[0] == calls[1]


def test_slow_headers_and_body_share_the_same_budget(monkeypatch):
    """Waiting for headers must reduce the timeout available for the body."""
    clock = _Clock()

    class Connection:
        def __init__(self, *_args, timeout=30, **_kwargs):
            self.timeout = timeout
            self.sock = self

        def settimeout(self, seconds):
            self.timeout = seconds

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            clock.advance(min(20, self.timeout))
            connection = self

            class Reply:
                status = 200

                def read(self, _limit):
                    clock.advance(connection.timeout)
                    raise TimeoutError("body stalled after slow headers")

                read1 = read

            return Reply()

        def close(self):
            pass

    monkeypatch.setattr(wms, "layers_for", lambda *a, **kw: (LAYER,))
    monkeypatch.setattr(wms, "_connection", Connection)
    monkeypatch.setattr(wms, "_drop_connection", lambda *a, **kw: None)
    monkeypatch.setattr(wms.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(wms.time, "sleep", clock.advance)

    with pytest.raises(RuntimeError):
        _frame()

    assert clock.elapsed <= 35.001


def test_connection_close_response_body_keeps_the_remaining_timeout(monkeypatch):
    """HTTPConnection detaches its socket before a Connection: close body."""
    clock = _Clock()

    class Socket:
        timeout = 30

        def settimeout(self, seconds):
            self.timeout = seconds

    class Connection:
        def __init__(self, *_args, **_kwargs):
            self.sock = Socket()

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            clock.advance(20)
            socket = self.sock
            self.sock = None

            class Reply:
                status = 200
                fp = SimpleNamespace(raw=SimpleNamespace(_sock=socket))

                def read1(self, _limit):
                    clock.advance(socket.timeout)
                    raise TimeoutError("detached response body stalled")

            return Reply()

        def close(self):
            pass

    monkeypatch.setattr(wms, "layers_for", lambda *a, **kw: (LAYER,))
    monkeypatch.setattr(wms, "_connection", Connection)
    monkeypatch.setattr(wms, "_drop_connection", lambda *a, **kw: None)
    monkeypatch.setattr(wms.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(wms.time, "sleep", clock.advance)

    with pytest.raises(RuntimeError):
        _frame()

    assert clock.elapsed <= 35.001


def test_custom_capabilities_are_reused_between_different_frames(monkeypatch):
    """Panning requires GetMap, but not a new capabilities catalogue."""
    calls = []

    def download(url, _limit):
        operation = parse_qs(urlsplit(url).query)["REQUEST"][0]
        calls.append(operation)
        return CAPABILITIES if operation == "GetCapabilities" else _png()

    monkeypatch.setattr(wms, "_download", download)
    first = _frame("custom")
    _frame("custom", east=401000)
    cached = _frame("custom")

    assert cached == first
    assert calls.count("GetCapabilities") == 1
    assert calls.count("GetMap") == 2


def test_cached_custom_frame_remains_available_when_upstream_is_offline(monkeypatch):
    """An already downloaded frame must be usable without a network call."""
    def download(url, _limit):
        return CAPABILITIES if "GetCapabilities" in url else _png()

    monkeypatch.setattr(wms, "_download", download)
    original = _frame("custom")
    attempted = []

    def offline(url, _limit):
        attempted.append(url)
        raise RuntimeError("upstream offline")

    monkeypatch.setattr(wms, "_download", offline)

    assert _frame("custom") == original
    assert attempted == []


def test_overlapping_identical_frames_share_one_upstream_download(monkeypatch):
    """Two callers wait for one frame instead of rendering it twice remotely."""
    start = threading.Barrier(2)
    duplicate_started = threading.Event()
    lock = threading.Lock()
    downloads = []
    image = _png()

    def download(url, _limit):
        with lock:
            downloads.append(url)
            if len(downloads) > 1:
                duplicate_started.set()
        # Hold the first result until the other caller can enter. On the
        # fixed path it waits for this same result and performs no download.
        duplicate_started.wait(0.2)
        return image

    monkeypatch.setattr(wms, "layers_for", lambda *a, **kw: (LAYER,))
    monkeypatch.setattr(wms, "_download", download)

    def worker():
        start.wait(timeout=2)
        return _frame()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        results = [future.result(timeout=3) for future in futures]

    assert results[0] == results[1]
    assert len(downloads) == 1


def test_overlapping_custom_frames_share_capabilities(monkeypatch):
    """Different images from one custom service share its in-flight catalogue."""
    start = threading.Barrier(2)
    duplicate_started = threading.Event()
    lock = threading.Lock()
    calls = []

    def download(url, _limit):
        operation = parse_qs(urlsplit(url).query)["REQUEST"][0]
        with lock:
            calls.append(operation)
            if calls.count("GetCapabilities") > 1:
                duplicate_started.set()
        if operation == "GetCapabilities":
            duplicate_started.wait(0.2)
            return CAPABILITIES
        return _png()

    monkeypatch.setattr(wms, "_download", download)

    def worker(east):
        start.wait(timeout=2)
        return _frame("custom", east=east)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, east) for east in (400000, 401000)]
        results = [future.result(timeout=3) for future in futures]

    assert all(data for data, _media in results)
    assert calls.count("GetCapabilities") == 1
    assert calls.count("GetMap") == 2


def test_failed_shared_frame_is_released_and_can_be_retried(monkeypatch):
    """A failed owner must release all waiters and allow a fresh attempt."""
    start = threading.Barrier(2)
    duplicate_started = threading.Event()
    lock = threading.Lock()
    request_threads = []
    failing = [True]
    image = _png()

    class Connection:
        timeout = 30
        sock = None

        def request(self, *_args, **_kwargs):
            with lock:
                request_threads.append(threading.get_ident())
                if len(set(request_threads)) > 1:
                    duplicate_started.set()

        def getresponse(self):
            if failing[0]:
                duplicate_started.wait(0.1)
                reply = _Reply(b"temporarily unavailable")
                reply.status = 503
                return reply
            return _Reply(image)

        def close(self):
            pass

    monkeypatch.setattr(wms, "layers_for", lambda *a, **kw: (LAYER,))
    monkeypatch.setattr(wms, "_connection", lambda *a, **kw: Connection())
    monkeypatch.setattr(wms, "_drop_connection", lambda *a, **kw: None)
    monkeypatch.setattr(wms.time, "sleep", lambda _seconds: None)

    def worker():
        start.wait(timeout=2)
        with pytest.raises(RuntimeError, match="502/503"):
            _frame()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        for future in futures:
            future.result(timeout=3)

    assert len(request_threads) == 2  # owner plus its single gateway retry
    failing[0] = False
    data, _media = _frame()
    assert Image.open(BytesIO(data)).size == (256, 256)
    assert len(request_threads) == 3


def test_continuously_streaming_body_cannot_extend_frame_deadline(monkeypatch):
    """Small successful reads must still stop at the total frame deadline."""
    clock = _Clock()
    chunks = []

    class Connection:
        def __init__(self, *_args, timeout=30, **_kwargs):
            self.timeout = timeout
            self.sock = self

        def settimeout(self, seconds):
            self.timeout = seconds

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            connection = self

            class Reply:
                status = 200

                def read1(self, _limit):
                    if connection.timeout < 8:
                        clock.advance(connection.timeout)
                        raise TimeoutError("next chunk exceeds remaining time")
                    clock.advance(8)
                    chunks.append(b"x" * 1024)
                    return chunks[-1]

            return Reply()

        def close(self):
            pass

    monkeypatch.setattr(wms, "layers_for", lambda *a, **kw: (LAYER,))
    monkeypatch.setattr(wms, "_connection", Connection)
    monkeypatch.setattr(wms, "_drop_connection", lambda *a, **kw: None)
    monkeypatch.setattr(wms.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(wms.time, "sleep", clock.advance)

    with pytest.raises(RuntimeError):
        _frame()

    assert len(chunks) == 4
    assert clock.elapsed <= 35.001


def test_custom_tile_fallback_preserves_overlay_transparency(monkeypatch):
    """A server image-size limit must not turn a transparent overlay opaque."""
    calls = []

    def download(url, _limit):
        params = parse_qs(urlsplit(url).query)
        if params["REQUEST"] == ["GetCapabilities"]:
            return CAPABILITIES
        width, height = int(params["WIDTH"][0]), int(params["HEIGHT"][0])
        calls.append((width, height))
        if width > 128 or height > 128:
            return (b"<ServiceExceptionReport><ServiceException>Image too large"
                    b"</ServiceException></ServiceExceptionReport>")
        output = BytesIO()
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        overlay.putpixel((width // 2, height // 2), (255, 0, 0, 255))
        overlay.save(output, "PNG")
        return output.getvalue()

    monkeypatch.setattr(wms, "_download", download)
    data, media = _frame("custom")

    assert calls.count((128, 128)) == 4
    assert media == "image/png"
    with Image.open(BytesIO(data)) as result:
        assert result.size == (256, 256)
        assert result.convert("RGBA").getextrema()[3] == (0, 255)
