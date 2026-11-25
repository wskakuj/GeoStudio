"""Real HTTP/CONNECT/TLS regressions; the WMS downloader is not mocked."""
from __future__ import annotations

from base64 import b64encode
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import select
import shutil
import socket
import ssl
import subprocess
import threading
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from PIL import Image
import pytest

from geostudio.web_app import underlay_wms as wms


HOST = "geostudio-proxy-test.example"
DELEGATE_HOST = "geostudio-delegate-test.example"
BODY = b"<?xml version='1.0'?><WMS_Capabilities/>"
WMS_CAPABILITIES = (
    b"<WMS_Capabilities><Capability><Layer><Name>Raster</Name>"
    b"<CRS>EPSG:2180</CRS></Layer></Capability></WMS_Capabilities>")
WMTS_CAPABILITIES = b"""<Capabilities xmlns="http://www.opengis.net/wmts/1.0"
    xmlns:ows="http://www.opengis.net/ows/1.1"><Contents>
  <Layer><ows:Identifier>Raster</ows:Identifier>
    <Style><ows:Identifier>default</ows:Identifier></Style>
    <Format>image/png</Format>
    <TileMatrixSetLink><TileMatrixSet>EPSG:2180</TileMatrixSet></TileMatrixSetLink>
  </Layer>
  <TileMatrixSet><ows:Identifier>EPSG:2180</ows:Identifier>
    <ows:SupportedCRS>urn:ogc:def:crs:EPSG::2180</ows:SupportedCRS>
    <TileMatrix><ows:Identifier>0</ows:Identifier>
      <ScaleDenominator>10000</ScaleDenominator><TopLeftCorner>850000 100000</TopLeftCorner>
      <TileWidth>512</TileWidth><TileHeight>512</TileHeight>
      <MatrixWidth>10</MatrixWidth><MatrixHeight>10</MatrixHeight>
    </TileMatrix>
  </TileMatrixSet>
</Contents></Capabilities>"""


def _png(width, height):
    output = BytesIO()
    Image.new("RGB", (width, height), (70, 100, 150)).save(output, "PNG")
    return output.getvalue()


@pytest.fixture
def https_through_proxy(monkeypatch, tmp_path):
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("OpenSSL executable is needed to create a temporary TLS test certificate")
    cert = tmp_path / "certificate.pem"
    key = tmp_path / "private-key.pem"
    subprocess.run([
        openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key), "-out", str(cert), "-days", "1",
        "-subj", "/CN=" + HOST, "-addext",
        "subjectAltName=DNS:" + HOST + ",DNS:" + DELEGATE_HOST,
    ], check=True, capture_output=True)
    requests = []
    tunnels = []
    server_names = []
    script = {}

    class Origin(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def do_GET(self):
            requests.append((self.path, dict(self.headers)))
            respond = script.get("respond", lambda _path: (200, BODY))
            response = respond(self.path)
            status, body = response[:2]
            self.send_response(status)
            self.send_header("Content-Type", "application/xml")
            self.send_header("Content-Length", str(len(body)))
            if len(response) > 2:
                for key, value in response[2].items():
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

    origin = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert, key)
    server_context.set_servername_callback(
        lambda _socket, server_name, _context: server_names.append(server_name))
    origin.socket = server_context.wrap_socket(origin.socket, server_side=True)

    class Proxy(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def do_CONNECT(self):
            tunnels.append((self.path, dict(self.headers)))
            upstream = socket.create_connection(origin.server_address, timeout=2)
            self.send_response(200, "Connection established")
            self.end_headers()
            self.wfile.flush()
            self.close_connection = True
            try:
                while True:
                    readable, _, _ = select.select(
                        [self.connection, upstream], [], [], 3)
                    if not readable:
                        break
                    for source in readable:
                        content = source.recv(65536)
                        if not content:
                            return
                        target = upstream if source is self.connection else self.connection
                        target.sendall(content)
            except (ConnectionError, OSError):
                pass
            finally:
                upstream.close()

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    threads = [threading.Thread(target=server.serve_forever,
                                 kwargs={"poll_interval": 0.01}, daemon=True)
               for server in (origin, proxy)]
    for thread in threads:
        thread.start()
    client_context = ssl.create_default_context(cafile=str(cert))
    monkeypatch.setattr(wms, "_TLS_STRICT", client_context)
    monkeypatch.setattr(wms, "proxy_bypass", lambda _host: False)
    monkeypatch.setattr(wms._CONNECTIONS, "pool", {}, raising=False)
    proxy_url = "http://127.0.0.1:" + str(proxy.server_port)
    monkeypatch.setattr(wms, "getproxies", lambda: {"https": proxy_url})
    try:
        yield SimpleNamespace(
            proxy_url=proxy_url, requests=requests, tunnels=tunnels,
            server_names=server_names, context=client_context, script=script)
    finally:
        for connection in wms._thread_pool().values():
            connection.close()
        wms._thread_pool().clear()
        for server in (proxy, origin):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


def test_downloader_uses_configured_proxy_and_reuses_verified_tls(https_through_proxy):
    service = https_through_proxy
    assert wms._download("https://" + HOST + "/capabilities", 1000) == BODY
    assert wms._download("https://" + HOST + "/second", 1000) == BODY

    assert [path for path, _headers in service.requests] == ["/capabilities", "/second"]
    assert [target for target, _headers in service.tunnels] == [HOST + ":443"]
    assert service.server_names == [HOST]
    assert service.context.check_hostname is True
    assert service.context.verify_mode == ssl.CERT_REQUIRED


def test_proxy_credentials_are_sent_only_to_connect(https_through_proxy, monkeypatch):
    service = https_through_proxy
    proxy_url = service.proxy_url.replace("http://", "http://test-user:test%3Apassword@")
    monkeypatch.setattr(wms, "getproxies", lambda: {"https": proxy_url})

    assert wms._download("https://" + HOST + "/capabilities", 1000) == BODY

    headers = service.tunnels[0][1]
    expected = "Basic " + b64encode(b"test-user:test:password").decode("ascii")
    assert headers["Proxy-Authorization"] == expected
    assert "Proxy-Authorization" not in service.requests[0][1]


def test_proxy_does_not_disable_destination_hostname_verification(https_through_proxy):
    connection = wms._connection("different-certificate-name.example")
    with pytest.raises(ssl.SSLCertVerificationError):
        connection.request("GET", "/")
    assert https_through_proxy.server_names == ["different-certificate-name.example"]
    assert https_through_proxy.requests == []


def test_no_proxy_bypasses_connect(monkeypatch):
    monkeypatch.setattr(wms._CONNECTIONS, "pool", {}, raising=False)
    monkeypatch.setattr(wms, "getproxies", lambda: {"https": "http://proxy.example:8080"})
    monkeypatch.setattr(wms, "proxy_bypass", lambda host: host == HOST)
    connection = wms._connection(HOST)
    try:
        assert connection.host == HOST
        assert connection.port == 443
        assert connection._tunnel_host is None
    finally:
        wms._drop_connection(HOST)


@pytest.mark.parametrize("proxy_url", [
    "https://private-user:secret-password@proxy.example:8080",
    "socks5://private-user:secret-password@proxy.example:1080",
    "http://private-user:secret-password@proxy.example:bad-port",
])
def test_invalid_proxy_is_explicit_and_does_not_expose_credentials(monkeypatch, proxy_url):
    monkeypatch.setattr(wms._CONNECTIONS, "pool", {}, raising=False)
    monkeypatch.setattr(wms, "getproxies", lambda: {"https": proxy_url})
    monkeypatch.setattr(wms, "proxy_bypass", lambda _host: False)
    with pytest.raises(RuntimeError, match="proxy HTTPS") as error:
        wms._connection(HOST)
    assert "private-user" not in str(error.value)
    assert "secret-password" not in str(error.value)
    assert wms._thread_pool() == {}


def test_http_400_ogc_exception_allows_wms_version_negotiation(https_through_proxy):
    capabilities = (b"<WMS_Capabilities><Capability><Layer><Name>Raster</Name>"
                    b"<CRS>EPSG:2180</CRS></Layer></Capability></WMS_Capabilities>")
    output = BytesIO()
    Image.new("RGB", (256, 256), (70, 100, 150)).save(output, "PNG")
    image = output.getvalue()
    versions = []

    def respond(path):
        query = parse_qs(urlsplit(path).query)
        if query["REQUEST"] == ["GetCapabilities"]:
            return 200, capabilities
        version = query["VERSION"][0]
        versions.append(version)
        if version == "1.1.1":
            return 400, (b"<ServiceExceptionReport><ServiceException code='InvalidVersion'>"
                         b"Only WMS 1.3.0 is supported"
                         b"</ServiceException></ServiceExceptionReport>")
        return 200, image

    https_through_proxy.script["respond"] = respond
    data, media = wms.map_image(
        "custom", "Raster", 2180, 400000, -501000, 401000, -500000,
        256, 256, "https://" + HOST + "/wms")

    assert data == image
    assert media == "image/png"
    assert versions == ["1.1.1", "1.3.0"]


@pytest.mark.parametrize("status,body", [
    (400, b"<html>Bad request</html>"),
    (400, b"x" * 65_000),
    (403, b"<ServiceException>Forbidden</ServiceException>"),
    (407, b"<ServiceException>Proxy authentication required</ServiceException>"),
])
def test_other_http_errors_do_not_trigger_format_retries(https_through_proxy, status, body):
    https_through_proxy.script["respond"] = lambda _path: (status, body)
    with pytest.raises(RuntimeError, match="błąd " + str(status)):
        wms._download("https://" + HOST + "/wms", 100_000)
    assert len(https_through_proxy.requests) == 1


def test_https_redirect_to_county_wms_returns_png(https_through_proxy):
    service = https_through_proxy
    image = _png(512, 512)

    def respond(path):
        if path == "/kieg":
            return 302, b"", {"Location": "https://" + DELEGATE_HOST + "/county/wms"}
        assert path == "/county/wms"
        return 200, image

    service.script["respond"] = respond
    assert wms._download("https://" + HOST + "/kieg", 100_000) == image
    assert [target for target, _headers in service.tunnels] == [
        HOST + ":443", DELEGATE_HOST + ":443"]
    assert service.server_names == [HOST, DELEGATE_HOST]


@pytest.mark.parametrize("redirects", [3, 4])
def test_relative_redirects_have_a_finite_hop_limit(https_through_proxy, redirects):
    service = https_through_proxy

    def respond(path):
        index = int(path.rsplit("/", 1)[-1])
        if index == redirects:
            return 200, BODY
        return 302, b"", {"Location": str(index + 1)}

    service.script["respond"] = respond
    if redirects == 3:
        assert wms._download("https://" + HOST + "/redirect/0", 1000) == BODY
    else:
        with pytest.raises(ValueError, match="limit przekierowań"):
            wms._download("https://" + HOST + "/redirect/0", 1000)
    assert len(service.requests) == 4


@pytest.mark.parametrize("location", [
    "http://public-wms.example/wms", "//127.0.0.1/wms",
    "https://localhost./wms", "https://service.localhost/wms",
    "https://service.localdomain/wms", "https://service.local/wms",
    "https://127.1/wms", "https://2130706433/wms", "https://0x7f000001/wms",
    "https://[::1]/wms", "https://[::ffff:127.0.0.1]/wms",
    "https://169.254.169.254/latest", "https://10.0.0.1/wms",
    "https://１２７.０.０.１/wms", "https://224.0.0.1/wms",
    "https://public-wms.example:8443/wms",
    "https://user:password@public-wms.example/wms", "https://@public-wms.example/wms",
    "", None,
])
def test_redirect_targets_use_public_https_service_validation(location):
    with pytest.raises(ValueError):
        wms._redirect_url("https://" + HOST + "/wms", location)


@pytest.mark.parametrize("url", [
    "https://8.8.8.8/wms",
    "https://[2001:4860:4860::8888]/wms",
])
def test_global_ip_services_remain_valid_without_network_requests(url):
    assert wms.validate_service_url(url) == url
    assert wms._redirect_url("https://" + HOST + "/wms", url) == url


def test_later_redirect_is_validated_before_connecting(https_through_proxy):
    service = https_through_proxy

    def respond(path):
        location = "/middle" if path == "/start" else "https://127.0.0.1/wms"
        return 302, b"", {"Location": location}

    service.script["respond"] = respond
    with pytest.raises(ValueError, match="lokalne"):
        wms._download("https://" + HOST + "/start", 1000)
    assert [path for path, _headers in service.requests] == ["/start", "/middle"]
    assert all(target == HOST + ":443" for target, _headers in service.tunnels)


def test_redirect_chain_shares_the_original_deadline(https_through_proxy, monkeypatch):
    service = https_through_proxy
    clock = [0.0]
    monkeypatch.setattr(wms.time, "monotonic", lambda: clock[0])

    def respond(path):
        clock[0] += 12
        index = int(path.rsplit("/", 1)[-1])
        return 302, b"", {"Location": str(index + 1)}

    service.script["respond"] = respond
    with pytest.raises(RuntimeError, match="Przekroczono czas"):
        wms._download("https://" + HOST + "/redirect/0", 1000)
    # The third response crosses the original 35-second deadline. A fresh
    # budget per redirect would continue all the way to the hop limit.
    assert len(service.requests) == 3


def test_new_redirect_host_starts_with_strict_tls(monkeypatch):
    calls = []

    def connection(host, *, relaxed=False):
        calls.append((host, relaxed))

        class Connection:
            def request(self, *_args, **_kwargs):
                pass

            def getresponse(self):
                if host == HOST:
                    if not relaxed:
                        raise ssl.SSLCertVerificationError("test source certificate")
                    return SimpleNamespace(
                        status=302,
                        getheader=lambda _name: "https://" + DELEGATE_HOST + "/wms")
                return SimpleNamespace(status=200, read=lambda _limit: BODY)

        return Connection()

    monkeypatch.setattr(wms, "_connection", connection)
    monkeypatch.setattr(wms, "_drop_connection", lambda *_a, **_kw: None)
    monkeypatch.setattr(wms.time, "sleep", lambda _seconds: None)
    assert wms._download("https://" + HOST + "/wms", 1000) == BODY
    assert calls == [(HOST, False), (HOST, True), (DELEGATE_HOST, False)]


@pytest.fixture
def local_tile_service(monkeypatch):
    """Use real HTTPResponse/socket IO while routing the HTTPS factory locally."""
    requests = []
    connections = []
    workers = set()
    guard = threading.Lock()
    release_tiles = threading.Event()
    blocked_tile_started = threading.Event()
    script = {}
    original_worker = wms._run_with_budget

    def observe_worker(*args, **kwargs):
        with guard:
            workers.add(threading.current_thread())
        return original_worker(*args, **kwargs)

    class Origin(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query)
            with guard:
                requests.append(query)
            try:
                status, body = script["respond"](query)
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                # A regression may consume the deadline before cleanup
                # releases a deliberately blocked server response.
                pass

    origin = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
    server_thread = threading.Thread(target=origin.serve_forever,
                                     kwargs={"poll_interval": 0.01}, daemon=True)
    server_thread.start()

    def connection_factory(_host, *, timeout=None, context=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", origin.server_port, timeout=timeout)
        with guard:
            connections.append(connection)
        return connection

    def finish_workers():
        release_tiles.set()
        with guard:
            started = list(workers)
        for worker in started:
            worker.join(timeout=3)
        assert all(not worker.is_alive() for worker in started)

    monkeypatch.setattr(wms.http.client, "HTTPSConnection", connection_factory)
    monkeypatch.setattr(wms, "getproxies", lambda: {})
    monkeypatch.setattr(wms._CONNECTIONS, "pool", {}, raising=False)
    monkeypatch.setattr(wms, "_run_with_budget", observe_worker)
    monkeypatch.setattr(wms, "REQUEST_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setattr(wms, "HOST_TIMEOUTS", {"mapy.geoportal.gov.pl": 5})
    try:
        yield SimpleNamespace(
            requests=requests, script=script, release_tiles=release_tiles,
            blocked_tile_started=blocked_tile_started, finish_workers=finish_workers)
    finally:
        # All tile work finishes before monkeypatch/cache teardown, including
        # workers whose owner already returned a fallback image to the caller.
        finish_workers()
        for connection in connections:
            connection.close()
        origin.shutdown()
        origin.server_close()
        server_thread.join(timeout=2)


def test_failed_wmts_tile_starts_wms_before_other_tiles_finish(local_tile_service):
    service = local_tile_service
    fallback_before_release = []

    def respond(query):
        operation = query["REQUEST"][0]
        if operation == "GetCapabilities":
            return 200, (WMTS_CAPABILITIES if query["SERVICE"] == ["WMTS"]
                         else WMS_CAPABILITIES)
        if operation == "GetMap":
            fallback_before_release.append(not service.release_tiles.is_set())
            return 200, _png(int(query["WIDTH"][0]), int(query["HEIGHT"][0]))
        if (query["TILEROW"], query["TILECOL"]) == (["0"], ["1"]):
            assert service.blocked_tile_started.wait(1)
            return 200, (b"<ExceptionReport><Exception><ExceptionText>TileOutOfRange"
                         b"</ExceptionText></Exception></ExceptionReport>")
        service.blocked_tile_started.set()
        service.release_tiles.wait(3)
        return 200, _png(512, 512)

    service.script["respond"] = respond
    try:
        data, media = wms.map_image(
            "standard_wmts", "Raster", 2180,
            101000, -849000, 104000, -847000, 300, 200)
        assert Image.open(BytesIO(data)).size == (300, 200)
        assert media == "image/jpeg"
        assert fallback_before_release == [True]
        assert not service.release_tiles.is_set()
    finally:
        service.finish_workers()
    # Nine tiles cover this frame; queued requests must not run after failure.
    assert sum(query["REQUEST"] == ["GetTile"] for query in service.requests) < 9


def test_failed_wms_tile_starts_smaller_image_before_other_tiles_finish(local_tile_service):
    service = local_tile_service
    smaller_before_release = []
    error = (b"<ServiceExceptionReport><ServiceException>Image too large"
             b"</ServiceException></ServiceExceptionReport>")

    def respond(query):
        if query["REQUEST"] == ["GetCapabilities"]:
            return 200, WMS_CAPABILITIES
        width = int(query["WIDTH"][0])
        height = int(query["HEIGHT"][0])
        if width == 256:
            return 200, error
        if width == 128:
            if query["BBOX"] == ["400000,500500,400500,501000"]:
                assert service.blocked_tile_started.wait(1)
                return 200, error
            service.blocked_tile_started.set()
            service.release_tiles.wait(3)
            return 200, _png(width, height)
        smaller_before_release.append(not service.release_tiles.is_set())
        return 200, _png(width, height)

    service.script["respond"] = respond
    try:
        data, media = wms.map_image(
            "standard", "Raster", 2180,
            400000, -501000, 401000, -500000, 256, 256)
        assert Image.open(BytesIO(data)).size == (179, 179)
        assert media == "image/png"
        assert smaller_before_release == [True]
        assert not service.release_tiles.is_set()
    finally:
        service.finish_workers()
    assert sum(query.get("WIDTH") == ["128"] for query in service.requests) < 4
