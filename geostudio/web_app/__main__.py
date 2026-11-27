"""Run the opt-in GeoStudio 2.0 window, independently of PySide6."""
from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Keep the local OCR runtime offline from its first native import, including
# the frozen application's no-console self-test and future plugin imports.
os.environ["ORT_DISABLE_TELEMETRY"] = "1"

import uvicorn

from . import updater
from .data import PreviewWorkspace
from .server import create_app


def _say(message: str) -> None:
    """Console-safe print for a frozen --windowed build.

    PyInstaller's windowed bootloader leaves sys.stdout as None when the app is
    started from Explorer; print() would raise AttributeError and abort startup.
    """
    stream = sys.stdout
    if stream is None:
        return
    try:
        print(message, file=stream, flush=True)
    except (AttributeError, OSError, ValueError):
        pass


def _log_file_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        return base / "GeoStudio2" / "geostudio.log"
    base = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    return base / "geostudio" / "geostudio.log"


def _uvicorn_log_config():
    """Log to a file instead of stdout.

    uvicorn's default formatter calls sys.stdout.isatty(); with no console that
    is None and the whole app dies with
    "ValueError: Unable to configure formatter 'default'".
    """
    try:
        path = _log_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8"):
            pass
    except OSError:
        return None
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
        },
        "handlers": {
            "file": {
                "class": "logging.FileHandler",
                "filename": str(path),
                "encoding": "utf-8",
                "formatter": "plain",
            },
        },
        "root": {"handlers": ["file"], "level": "WARNING"},
        "loggers": {
            "uvicorn": {"handlers": [], "level": "WARNING", "propagate": True},
            "uvicorn.error": {"handlers": [], "level": "WARNING", "propagate": True},
            "uvicorn.access": {"handlers": [], "level": "WARNING", "propagate": True},
        },
    }


def _check_windows_runtime():
    """Load the same .NET bridge as pywebview, without creating a window."""
    if os.name == "nt":
        import clr
        clr.AddReference("System.Windows.Forms")


def _is_pythonnet_loader_error(error):
    return "Failed to resolve Python.Runtime.Loader.Initialize" in str(error)


def _show_windows_runtime_error():
    # Do not silently remove Internet-zone markings from downloaded files.
    # Let the owner verify their archive and decide whether to unblock it.
    import ctypes
    ctypes.windll.user32.MessageBoxW(
        None,
        "Nie udało się uruchomić głównego okna GeoStudio (Python.NET).\n\n"
        "Jeżeli korzystasz z zaufanego ZIP pobranego z własnego GitHub Actions, "
        "sprawdź Właściwości archiwum: Odblokuj, następnie wypakuj je ponownie "
        "do nowego katalogu. Zachowaj cały folder _internal.\n\n"
        "Jeżeli problem nadal występuje, sprawdź kompletność archiwum "
        "oraz instalację .NET Framework. Nie wyłączaj zabezpieczeń Windows.",
        "GeoStudio — nie udało się wczytać biblioteki .NET", 0x10,
    )


def _selftest(workspace) -> int:
    """Start the server with no console streams, exactly like a windowed EXE.

    PyInstaller --windowed leaves sys.stdout/sys.stderr as None. That used to
    abort uvicorn's logging setup before the window could appear, so this check
    reproduces it instead of hiding it behind a redirected --help.
    """
    import urllib.request

    saved = (sys.stdout, sys.stderr)
    sys.stdout = None
    sys.stderr = None
    server = None
    worker = None
    sock = None
    try:
        # The HTTP/OCR smoke test alone does not exercise Python.NET.
        # Fail CI if the packaged managed assembly cannot initialize.
        _check_windows_runtime()
        # Exercise the bundled PDFium DLL, not just Python imports.  A build
        # can launch its UI successfully while missing the native PDF decoder.
        # The complete fixture and PNG stay in memory; no user file is read.
        from io import BytesIO
        from reportlab.pdfgen.canvas import Canvas
        from .underlay_raster import prepare_raster

        fixture = BytesIO()
        sheet = Canvas(fixture, pagesize=(24, 24))
        sheet.setFillColorRGB(.2, .5, .1)
        sheet.rect(2, 2, 20, 20, fill=1, stroke=0)
        sheet.save()
        preview, metadata = prepare_raster(fixture.getvalue())
        if (not preview.startswith(b"\x89PNG\r\n\x1a\n") or
                (metadata["width"], metadata["height"]) != (100, 100) or
                (metadata["sourceWidth"], metadata["sourceHeight"]) != (100, 100)):
            return 1
        # Verify the bundled ONNX DLLs, both local models and real OCR, using
        # a generated number/circle fixture. No user raster or network is used.
        from .raster_a1 import selftest_raster_a1
        if not selftest_raster_a1():
            return 1
        from .firebase_auth import DiagnosticGate
        # Exercise the actual DPAPI binding on Windows, with synthetic data
        # in a temporary directory, never a user session.
        if os.name == "nt":
            from tempfile import TemporaryDirectory
            from .firebase_vault import WindowsSessionVault
            with TemporaryDirectory() as directory:
                vault = WindowsSessionVault("diagnostic", Path(directory) / "session.bin")
                vault.save("test-token-not-a-real-credential")
                if vault.load() != "test-token-not-a-real-credential":
                    return 1
                if b"test-token-not-a-real-credential" in vault.path.read_bytes():
                    return 1
                vault.clear()
                if vault.path.exists():
                    return 1
        app = create_app(workspace, multi_document=True, access_gate=DiagnosticGate())
        config = uvicorn.Config(
            app=app, log_level="warning", access_log=False, server_header=False,
            log_config=_uvicorn_log_config())
        server = uvicorn.Server(config)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        sock.listen(8)
        port = sock.getsockname()[1]
        worker = threading.Thread(
            target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        worker.start()
        for _ in range(200):
            if server.started:
                break
            if not worker.is_alive():
                return 1
            time.sleep(0.03)
        if not server.started:
            return 1
        # Worker-only imports are not listed in index.html. Verify that a
        # packaged installer carries the stroke analyser and A1 assignment
        # helper as well as the floating windows and primary tracing script.
        assets = {
            "/": b"<!DOCTYPE html>",
            "/raster_trace.js": b"function traceLandUses",
            "/raster_parcel_snap.js": b"GeoStudioRasterParcelSnap",
            "/raster_trace_metrics.js": b"GeoStudioRasterTraceMetrics",
            "/raster_a1.js": b"GeoStudioRasterA1",
            "/floating_dialog.js": b"GeoStudioFloatingDialog",
            "/admin.js": b"GeoStudioAdmin",
            "/admin.css": b"#admin-dialog",
        }
        for path, marker in assets.items():
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}{path}", timeout=10) as response:
                body = response.read()
                if response.status != 200 or marker not in body:
                    return 1
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/documents",
            headers={"X-GeoStudio-Token": app.state.api_token})
        try:
            with urllib.request.urlopen(request, timeout=10):
                return 1  # diagnostic process must never serve editor APIs
        except urllib.error.HTTPError as error:
            if error.code != 403:
                return 1
        return 0
    except BaseException:
        return 1
    finally:
        if server is not None:
            server.should_exit = True
        if worker is not None:
            worker.join(timeout=5)
        if sock is not None:
            sock.close()
        sys.stdout, sys.stderr = saved


def check_updates_on_start(interactive: bool = True) -> None:
    """Sprawdza GitHub i zapamiętuje wynik dla interfejsu.

    Żadnego okna Tk: informację o aktualizacji pokazuje karta w aplikacji
    (ta sama, którą widać po kliknięciu numeru wersji). Tylko w spakowanym
    programie — wersja deweloperska nie podmienia plików.
    """
    if not updater.is_frozen():
        return
    try:
        info = updater.check_for_update()
    except Exception:
        return
    if not info or not info.get("assetUrl"):
        updater.set_pending_update(None)
        return
    updater.set_pending_update(info)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="GeoStudio 2.0 — testowy interfejs GIS (edycja kopii w pamięci)"
    )
    parser.add_argument("--browser", action="store_true",
                        help="Otwórz interfejs w przeglądarce zamiast pywebview")
    parser.add_argument("--map", type=Path,
                        help="Opcjonalny lokalny plik MAP do wczytania przy starcie")
    parser.add_argument("--selftest", action="store_true",
                        help="Sprawdź start bez konsoli (używane przez pakowanie)")
    parser.add_argument("--no-update-check", action="store_true",
                        help="Nie sprawdzaj aktualizacji przy starcie")
    parser.add_argument("--login", action="store_true",
                        help="Pomiń zapamiętaną sesję i pokaż okno logowania")
    args = parser.parse_args(argv)

    if args.selftest:
        # Diagnostic only: no user files, no native bridge or persistent server.
        return _selftest(PreviewWorkspace())

    from .firebase_login import run_login
    gate = run_login(force_prompt=args.login)
    if gate is None:
        return 0
    workspace = PreviewWorkspace()
    if args.map is not None:
        workspace.load_map(args.map.read_bytes(), args.map.name)

    # The existing public updater must not install an unprotected release.
    app = create_app(workspace, multi_document=True, access_gate=gate)
    stop_auth = threading.Event()
    auth_worker = threading.Thread(target=gate.run, args=(stop_auth,),
                                   daemon=True, name="GeoStudioFirebase")
    auth_worker.start()
    # Bind immediately to an ephemeral loopback port. Passing an already-bound
    # socket to uvicorn avoids races with other apps and never exposes the
    # user's map files to LAN clients.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # A stable origin makes the Chromium file picker's named directory
    # preference survive browser restarts. Native pywebview still uses
    # ephemeral loopback ports and its own persisted Windows file dialog.
    preferred_port = 63871 if args.browser else 0
    try:
        sock.bind(("127.0.0.1", preferred_port))
    except OSError:
        if not args.browser:
            sock.close()
            raise
        # A previous test instance might still own that port.
        # Never connect to it by mistake: start a distinct localhost server.
        sock.bind(("127.0.0.1", 0))
        _say("Port 63871 zajęty; przeglądarka może nie zapamiętać katalogu.")
    sock.listen(128)
    port = sock.getsockname()[1]
    address = f"http://127.0.0.1:{port}/"
    config = uvicorn.Config(
        app=app, log_level="warning", access_log=False, server_header=False,
        log_config=_uvicorn_log_config())
    server = uvicorn.Server(config)
    _say("GeoStudio 2.0 — edycja w pamięci, oryginał chroniony")
    _say(address)

    if args.browser:
        webbrowser.open(address)
        try:
            server.run(sockets=[sock])
        finally:
            stop_auth.set()
            sock.close()
        return

    try:
        _check_windows_runtime()
        import webview
    except RuntimeError as exc:
        stop_auth.set()
        sock.close()
        if os.name == "nt" and _is_pythonnet_loader_error(exc):
            _show_windows_runtime_error()
            return 1
        raise
    except ImportError as exc:
        stop_auth.set()
        sock.close()
        raise SystemExit(
            'Brakuje pywebview. Uruchom: py -m pip install -e ".[web]" '
            'lub użyj opcji --browser.'
        ) from exc

    worker = threading.Thread(
        target=server.run, kwargs={"sockets": [sock]}, daemon=True,
        name="GeoStudioLocalAPI")
    worker.start()
    try:
        # Wait until the local socket accepts requests before showing WebView2.
        for _ in range(150):
            if server.started:
                break
            if not worker.is_alive():
                raise RuntimeError("Nie udało się uruchomić lokalnego serwera.")
            time.sleep(0.03)
        if not server.started:
            raise RuntimeError("Lokalny serwer nie wystartował.")
        from .documents import DocumentNativeBridge
        native_picker = DocumentNativeBridge(app.state.documents, access_gate=gate)
        webview.create_window(
            "GeoStudio 2.0",
            address, width=1480, height=940, min_size=(960, 640),
            background_color="#101A2B", js_api=native_picker,
        )
        # Crucially, the JS bridge keeps NO reference to the pywebview
        # Window: dialogs open independently through Tk on the worker thread.
        webview.start()
    except RuntimeError as exc:
        if os.name == "nt" and _is_pythonnet_loader_error(exc):
            _show_windows_runtime_error()
            return 1
        raise
    finally:
        stop_auth.set()
        server.should_exit = True
        worker.join(timeout=4)
        sock.close()


if __name__ == "__main__":
    sys.exit(main())
