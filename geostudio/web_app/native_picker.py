"""Native Windows file picker with a persisted last map directory.

Only invoked from a pywebview window's JS API, never from an HTTP endpoint.
The user selects the file with a native OS dialog; no arbitrary filesystem
paths are accepted from browser JavaScript. The absolute path stays local
to the native bridge, and only GEO-MAP metadata is returned to the UI.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .data import MAX_MAP_BYTES, PreviewWorkspace


def preference_file() -> Path:
    """Writable per-user location, independent of the Git checkout."""
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return root / "GeoStudio2" / "preferences.json"
    root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "geostudio2" / "preferences.json"


def read_last_map_directory(settings: Path) -> str:
    try:
        value = json.loads(settings.read_text(encoding="utf-8"))
        last = value.get("last_map_directory")
        if isinstance(last, str) and Path(last).is_dir():
            return last
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return ""


def save_last_map_directory(settings: Path, directory: Path) -> None:
    if not directory.is_dir():
        return
    settings.parent.mkdir(parents=True, exist_ok=True)
    # Store only a folder, never the MAP content or credentials.
    payload = json.dumps(
        {"last_map_directory": str(directory)},
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    # Replace atomically to prevent truncated settings on a forced exit.
    fd, temporary = tempfile.mkstemp(
        prefix=".geostudio2-", suffix=".tmp", dir=settings.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, settings)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


class NativeMapPicker:
    """JS bridge open_map() returns metadata only, never an absolute path."""

    def __init__(self, workspace: PreviewWorkspace,
                 *, settings: Path | None = None, window=None):
        self.workspace = workspace
        self.settings = settings if settings is not None else preference_file()
        self.window = window

    def open_map(self) -> dict:
        if self.window is None:
            raise RuntimeError("Natywne okno wyboru pliku jest niedostępne.")

        import webview

        files = self.window.create_file_dialog(
            dialog_type=webview.FileDialog.OPEN,
            directory=read_last_map_directory(self.settings),
            allow_multiple=False,
            file_types=("Mapy GEO-MAP (*.map;*.MAP)",),
        )
        if not files:
            return {"cancelled": True}
        chosen = Path(files[0])
        if chosen.suffix.casefold() != ".map" or not chosen.is_file():
            raise ValueError("Wybierz prawidłowy plik GEO-MAP .MAP.")
        if not 0 < chosen.stat().st_size <= MAX_MAP_BYTES:
            raise ValueError("Plik MAP jest pusty lub przekracza limit 80 MB.")
        meta = self.workspace.load_map(chosen.read_bytes(), chosen.name)
        try:
            save_last_map_directory(self.settings, chosen.parent)
        except OSError:
            # Map should still open even if a locked-down user profile
            # disallows saving GUI preferences.
            pass
        return {"cancelled": False, "metadata": meta}
