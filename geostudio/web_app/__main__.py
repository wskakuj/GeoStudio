"""Run the opt-in GeoStudio 2.0 window, independently of PySide6."""
from __future__ import annotations

import argparse
import socket
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from .data import PreviewWorkspace
from .server import create_app


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="GeoStudio 2.0 — testowy interfejs GIS (edycja kopii w pamięci)"
    )
    parser.add_argument("--browser", action="store_true",
                        help="Otwórz interfejs w przeglądarce zamiast pywebview")
    parser.add_argument("--map", type=Path,
                        help="Opcjonalny lokalny plik MAP do wczytania przy starcie")
    args = parser.parse_args(argv)

    workspace = PreviewWorkspace()
    if args.map is not None:
        workspace.load_map(args.map.read_bytes(), args.map.name)

    app = create_app(workspace)
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
        print("Port 63871 zajęty; przeglądarka może nie zapamiętać katalogu.", flush=True)
    sock.listen(128)
    port = sock.getsockname()[1]
    address = f"http://127.0.0.1:{port}/"
    config = uvicorn.Config(
        app=app, log_level="warning", access_log=False, server_header=False)
    server = uvicorn.Server(config)
    print("GeoStudio 2.0 — edycja w pamięci, oryginał chroniony", flush=True)
    print(address, flush=True)

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
        from .native_picker import NativeMapPicker
        native_picker = NativeMapPicker(workspace)
        window = webview.create_window(
            "GeoStudio 2.0 — Podgląd",
            address, width=1480, height=940, min_size=(960, 640),
            background_color="#101A2B", js_api=native_picker,
        )
        native_picker.window = window
        webview.start()
    finally:
        server.should_exit = True
        worker.join(timeout=4)
        sock.close()


if __name__ == "__main__":
    main()
