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
    """Small JS API that never exposes pywebview/WinForms COM objects.

    The file picker is hosted by a short-lived Tk root instead of
    pywebview.Window.create_file_dialog. Tk owns its dialog independently
    of WebView2/COM; this avoids intermittent failures and thread-affinity
    problems in the old bridge. If Tk is missing, the UI shows a separate,
    synchronous HTML file input fallback.
    """

    __slots__ = ("_workspace", "_settings", "_source_path")

    def __init__(self, workspace: PreviewWorkspace,
                 *, settings: Path | None = None):
        self._workspace = workspace
        self._settings = settings if settings is not None else preference_file()
        self._source_path = None

    def _choose_path(self) -> str:
        # Called on pywebview's JS API worker thread, *not* the WebView2
        # GUI thread. Build/destroy Tk entirely on this worker thread.
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        try:
            root.withdraw()
            root.attributes("-topmost", True)
            root.update()
            directory = read_last_map_directory(self._settings)
            return filedialog.askopenfilename(
                parent=root,
                initialdir=directory or str(Path.home()),
                title="GeoStudio 2.0 — Wybierz mapę GEO-MAP",
                filetypes=(("Mapy GEO-MAP", "*.MAP *.map"),
                           ("Wszystkie pliki", "*.*")),
            )
        finally:
            root.destroy()

    def open_map(self) -> dict:
        try:
            filename = self._choose_path()
        except Exception as exc:
            # TkError and missing Tcl/Tk on minimally installed Python also
            # need a comprehensible fallback, not a silent JS bridge hang.
            raise RuntimeError(
                "Nie udało się wyświetlić okna wyboru Windows. "
                "Użyj przycisku Z dysku."
            ) from exc
        if not filename:
            return {"cancelled": True}
        chosen = Path(filename)
        if chosen.suffix.casefold() != ".map" or not chosen.is_file():
            raise ValueError("Wybierz prawidłowy plik GEO-MAP .MAP.")
        if not 0 < chosen.stat().st_size <= MAX_MAP_BYTES:
            raise ValueError("Plik MAP jest pusty lub przekracza limit 80 MB.")
        meta = self._workspace.load_map(chosen.read_bytes(), chosen.name)
        self._source_path = chosen.resolve()
        try:
            save_last_map_directory(self._settings, chosen.parent)
        except OSError:
            pass
        return {"cancelled": False, "metadata": meta}


    def save_map(self) -> dict:
        """Save an explicitly named new MAP through an actual Windows Save As dialog.

        Unlike a browser Blob download, WebView2 can display and reliably
        persist this path. Never guess the destination or overwrite source.
        """
        import tkinter as tk
        from tkinter import filedialog
        status = self._workspace.editing_status()
        if not status.get("documentToken"):
            raise ValueError("Najpierw otwórz mapę GEO-MAP.")
        suggested_name, content = self._workspace.export_copy(status["documentToken"])
        root = tk.Tk()
        try:
            root.withdraw()
            root.attributes("-topmost", True)
            root.update()
            directory = (self._source_path.parent if self._source_path
                         else Path(read_last_map_directory(self._settings) or
                                   str(Path.home() / "Documents")))
            chosen_name = filedialog.asksaveasfilename(
                parent=root,
                title="GeoStudio 2.0 — Zapisz kopię mapy MAP",
                initialdir=str(directory),
                initialfile=suggested_name,
                defaultextension=".MAP",
                filetypes=(("Mapy GEO-MAP", "*.MAP"),),
                confirmoverwrite=True,
            )
        finally:
            root.destroy()
        if not chosen_name:
            return {"cancelled": True}
        chosen = Path(chosen_name)
        if chosen.suffix.casefold() != ".map":
            raise ValueError("Kopia musi mieć rozszerzenie .MAP.")
        if (self._source_path is not None and
                chosen.resolve() == self._source_path):
            raise ValueError("Nie wolno nadpisać otwartego pliku źródłowego.")
        if chosen.name.casefold() == self._workspace.metadata()["name"].casefold():
            raise ValueError("Podaj inną nazwę niż mapa źródłowa.")
        # os.replace is atomic on the same volume. Never truncate a valid
        # target file in place if writing fails halfway.
        fd, tmp = tempfile.mkstemp(prefix=".geostudio2-",suffix=".tmp",
                                   dir=str(chosen.parent))
        try:
            with os.fdopen(fd,"wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp,chosen)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
        try:
            save_last_map_directory(self._settings,chosen.parent)
        except OSError:
            pass
        return {"cancelled": False, "path": str(chosen),
                "bytes": len(content)}
