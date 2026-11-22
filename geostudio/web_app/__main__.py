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

import uvicorn

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
        app = create_app(workspace, multi_document=True)
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
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/", timeout=10) as response:
            return 0 if response.status == 200 else 1
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
    args = parser.parse_args(argv)

    workspace = PreviewWorkspace()
    if args.map is not None:
        workspace.load_map(args.map.read_bytes(), args.map.name)

    if args.selftest:
        return _selftest(workspace)

    app = create_app(workspace, multi_document=True)
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
            sock.close()
        return

    try:
        import webview
    except ImportError as exc:
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
        native_picker = DocumentNativeBridge(app.state.documents)
        webview.create_window(
            "GeoStudio 2.0 — Podgląd",
            address, width=1480, height=940, min_size=(960, 640),
            background_color="#101A2B", js_api=native_picker,
        )
        # Crucially, the JS bridge keeps NO reference to the pywebview
        # Window: dialogs open independently through Tk on the worker thread.
        webview.start()
    finally:
        server.should_exit = True
        worker.join(timeout=4)
        sock.close()


if __name__ == "__main__":
    sys.exit(main())
