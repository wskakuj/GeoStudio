"""Native Windows file picker with a persisted last map directory.

Only invoked from a pywebview window's JS API, never from an HTTP endpoint.
The user selects the file with a native OS dialog; no arbitrary filesystem
paths are accepted from browser JavaScript. The absolute path stays local
to the native bridge, and only GEO-MAP metadata is returned to the UI.
"""
from __future__ import annotations

import base64
import json
from hashlib import sha256
import os
from pathlib import Path
import tempfile
import re
from threading import RLock

from .data import MAX_MAP_BYTES, PreviewWorkspace
from .recovery import LocalRecoveryStore


def _raster_with_world(path: Path) -> dict:
    suffix = path.suffix.lower()
    short = {".png": ".pgw", ".jpg": ".jgw", ".jpeg": ".jgw",
             ".tif": ".tfw", ".tiff": ".tfw", ".webp": ".wpw"}
    if suffix not in short or not 0 < path.stat().st_size <= 48 * 1024 * 1024:
        raise ValueError("Wybierz obsługiwany raster o rozmiarze do 48 MB.")
    world = None
    warning = ""
    try:
        siblings = {p.name.casefold(): p for p in path.parent.iterdir()}
        for ext in (short[suffix], suffix + "w", ".wld"):
            sidecar = siblings.get((path.stem + ext).casefold())
            if sidecar is None or not sidecar.is_file():
                continue
            with sidecar.open("rb") as stream:
                content = stream.read(8193)
            if len(content) > 8192:
                raise ValueError("Plik world przekracza 8 KB.")
            world = {"name": sidecar.name, "text": content.decode("utf-8-sig")}
            break
    except (OSError, ValueError) as exc:
        warning = f"Nie udało się odczytać pliku world. {exc}"
    return {"name": path.name, "data": base64.b64encode(path.read_bytes()).decode("ascii"),
            "world": world, "warning": warning}


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


_PREFERENCES_LOCK = RLock()
_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _read_preferences(settings: Path) -> dict:
    try:
        if settings.stat().st_size > 16384:
            return {}
        payload = json.loads(settings.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def _save_preferences(settings: Path, changes: dict) -> None:
    """Atomically merge settings; appearance must not erase the last MAP folder."""
    with _PREFERENCES_LOCK:
        payload = {**_read_preferences(settings), **changes}
        settings.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(payload,ensure_ascii=False,indent=2).encode("utf-8")
        fd, temporary = tempfile.mkstemp(
            prefix=".geostudio2-", suffix=".tmp", dir=settings.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, settings)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def save_last_map_directory(settings: Path, directory: Path) -> None:
    if directory.is_dir():
        # Keep the existing appearance settings when a new MAP is opened.
        _save_preferences(settings, {"last_map_directory": str(directory)})


def read_appearance_preference(settings: Path) -> dict:
    stored = _read_preferences(settings).get("appearance")
    if not isinstance(stored, dict):
        stored = {}
    theme = stored.get("theme")
    color = stored.get("mapBackground")
    return {
        "theme": theme if theme in ("dark", "light") else "dark",
        "mapBackground": color.upper() if isinstance(color,str)
                         and _HEX_COLOR.fullmatch(color) else "#FFFFFF",
    }


def save_appearance_preference(settings: Path, theme: str, map_background: str) -> dict:
    if theme not in ("dark","light") or not isinstance(map_background,str) or (
        _HEX_COLOR.fullmatch(map_background) is None):
        raise ValueError("Niepoprawny motyw lub kolor tła mapy.")
    result={"theme":theme,"mapBackground":map_background.upper()}
    _save_preferences(settings,{"appearance":result})
    return result


def _ask_save_as(directory: Path, initialfile: str) -> str:
    """Windows Save As dialog, isolated so tests never need a display."""
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        return filedialog.asksaveasfilename(
            parent=root,
            title="GeoStudio 2.0 — Zapisz kopię mapy MAP",
            initialdir=str(directory),
            initialfile=initialfile,
            defaultextension=".MAP",
            filetypes=(("Mapy GEO-MAP", "*.MAP"),),
            confirmoverwrite=True,
        ) or ""
    finally:
        root.destroy()


def _ask_yes_no(title: str, message: str) -> bool:
    """Tk Yes/No dialog, isolated so tests never need a display."""
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        root.update()
        return bool(messagebox.askyesno(title=title, message=message, parent=root))
    finally:
        root.destroy()


def _atomic_write(path: Path, content: bytes) -> None:
    """Replace a file in one step so a crash cannot leave half a MAP."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".geostudio2-", suffix=".tmp",
                                dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        try:
            os.unlink(temp)
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

    __slots__ = ("_workspace", "_settings", "_source_path", "_source_sha",
                 "_tile_exports")

    def __init__(self, workspace: PreviewWorkspace,
                 *, settings: Path | None = None, tile_exports=None):
        self._workspace = workspace
        self._tile_exports = tile_exports
        self._settings = settings if settings is not None else preference_file()
        self._source_path = None
        self._source_sha = None

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
                "Użyj standardowego okna wyboru pliku."
            ) from exc
        if not filename:
            return {"cancelled": True}
        chosen = Path(filename)
        if chosen.suffix.casefold() != ".map" or not chosen.is_file():
            raise ValueError("Wybierz prawidłowy plik GEO-MAP .MAP.")
        if not 0 < chosen.stat().st_size <= MAX_MAP_BYTES:
            raise ValueError("Plik MAP jest pusty lub przekracza limit 512 MB.")
        raw=chosen.read_bytes()
        from geostudio.coordinates import detected_crs_from_prj
        meta=self._workspace.load_map(raw,chosen.name,epsg=detected_crs_from_prj(chosen))
        metadata_path=chosen.with_suffix(".geostudio-topology.json")
        if metadata_path.is_file():
            try:
                self._workspace.import_topology_metadata(
                    metadata_path.read_bytes(),raw)
                meta=self._workspace.metadata()
                meta["topologyImported"]=True
            except (ValueError, OSError, TypeError):
                meta["topologyWarning"]=(
                    "Pominięto niezgodny plik topologii. "
                    "Mapa bazowa została wczytana bez odwracalnych wycięć.")
        visual_path=chosen.with_suffix(".geostudio.json")
        if visual_path.is_file():
            try:
                visual=self._workspace.set_visual_sidecar(visual_path.read_bytes())
                meta={**self._workspace.metadata(),"visualImported":visual}
            except (ValueError,OSError,TypeError) as exc:
                meta["visualWarning"]=(
                    "Pominięto niezgodne ustawienia opisów GeoStudio: "+str(exc))
        self._source_path = chosen.resolve()
        self._source_sha = sha256(raw).hexdigest()
        available=self._recovery_store().candidate(
            self._source_path,self._source_sha)
        if available:
            meta["recoveryAvailable"]=available
        try:
            save_last_map_directory(self._settings, chosen.parent)
        except OSError:
            pass
        return {"cancelled": False, "metadata": meta}


    def _recovery_store(self) -> LocalRecoveryStore:
        return LocalRecoveryStore(self._settings.parent/"recovery")

    def save_recovery(self) -> dict:
        """Debounced from UI after edits; NEVER overwrites the input map."""
        path=self._source_path
        identity=self._source_sha
        status=self._workspace.editing_status()
        if not path or not identity or not status["dirty"]:
            return {"saved":False,"reason":"Brak niezapisanych zmian lub pliku źródłowego."}
        _,raw=self._workspace.export_copy(status["documentToken"])
        companion=self._workspace.export_topology_metadata(raw)
        if companion is None:
            companion=json.dumps({
                "format":"geostudio-topology-v1",
                "sha256":sha256(raw).hexdigest(),"uids":[]
            },separators=(",",":")).encode("utf-8")
        # Crash recovery must include label moves and compilation scale too;
        # placing the visual snapshot in the checksum-bound recovery blob
        # changes neither the public 6A nor 6B topology companion format.
        visual=self._workspace.export_visual_sidecar(raw)
        if visual:
            envelope=json.loads(companion)
            envelope["recoveryVisual"]=json.loads(visual)
            companion=json.dumps(envelope,ensure_ascii=False,
                                 separators=(",",":")).encode("utf-8")
        new=self._workspace.editing_status()
        if (new["revision"]!=status["revision"] or
                new["documentToken"]!=status["documentToken"] or
                path!=self._source_path or identity!=self._source_sha):
            return {"saved":False,"reason":"Zmieniono mapę podczas tworzenia migawki."}
        result=self._recovery_store().save(
            path,identity,raw,companion,status["revision"])
        return result

    def restore_recovery(self) -> dict:
        """Restore only when the source file still matches its original SHA."""
        path=self._source_path
        identity=self._source_sha
        if not path or not identity or not path.is_file():
            raise ValueError("Najpierw otwórz źródłowy MAP z dysku.")
        # Do not restore a journal over an externally updated source.
        if sha256(path.read_bytes()).hexdigest()!=identity:
            raise ValueError("MAP zmienił się na dysku. Nie odtworzono migawki.")
        recovery=self._recovery_store().load(path,identity)
        if recovery is None:
            raise ValueError("Brak zgodnej, kompletnej migawki odzyskiwania.")
        _,raw,companion=recovery
        from geostudio.geomap import GeoMap
        check=GeoMap(raw,filename=path.name)
        if (not check.checksum_valid or
                check.declared_lines!=len(check.lines)):
            raise ValueError("Migawka zawiera nieprawidłową sumę GEO-MAP.")
        recovery_meta=json.loads(companion)
        visual=recovery_meta.pop("recoveryVisual",None)
        topology=json.dumps(recovery_meta,ensure_ascii=False,
                            separators=(",",":")).encode("utf-8")
        self._workspace.load_map(raw,path.name)
        self._workspace.import_topology_metadata(topology,raw)
        if visual:
            self._workspace.set_visual_sidecar(
                json.dumps(visual,ensure_ascii=False).encode("utf-8"))
        self._workspace.mark_recovered_unsaved()
        return {"restored":True,"metadata":self._workspace.metadata()}

    def open_raster(self) -> dict:
        from tkinter import Tk, filedialog
        root = Tk()
        try:
            root.withdraw()
            root.attributes("-topmost", True)
            filename = filedialog.askopenfilename(
                parent=root, title="Wybierz raster",
                initialdir=str(self._source_path.parent) if self._source_path
                else read_last_map_directory(self._settings),
                filetypes=(("Rastry", "*.png *.jpg *.jpeg *.webp *.tif *.tiff"),))
        finally:
            root.destroy()
        return _raster_with_world(Path(filename)) if filename else {"cancelled": True}

    def open_libraries(self) -> dict:
        """Choose LAY/CDF/SYM with a real Windows dialog, never via JS paths."""
        import tkinter as tk
        from tkinter import filedialog
        root=tk.Tk()
        try:
            root.withdraw()
            root.attributes("-topmost",True)
            root.update()
            directory=(self._source_path.parent if self._source_path
                       else Path(read_last_map_directory(self._settings) or
                                 str(Path.home())))
            paths=filedialog.askopenfilenames(
                parent=root,initialdir=str(directory),
                title="GeoStudio 2.0 — biblioteki kartograficzne LAY/CDF/SYM",
                filetypes=(("Biblioteki GEO-MAP","*.LAY *.CDF *.SYM"),
                           ("Wszystkie pliki","*.*")))
        finally:
            root.destroy()
        if not paths:
            return {"cancelled":True}
        if len(paths)>3:
            raise ValueError("Wybierz najwyżej trzy biblioteki (LAY, CDF, SYM).")
        data=[]
        kinds=set()
        for filename in paths:
            path=Path(filename)
            kind=path.suffix.upper()
            if kind not in {".LAY",".CDF",".SYM"} or kind in kinds:
                raise ValueError("Wybierz maksymalnie po jednym LAY, CDF i SYM.")
            if not path.is_file() or not 0<path.stat().st_size<=8*1024*1024:
                raise ValueError("Niepoprawna biblioteka lub rozmiar ponad 8 MB.")
            data.append((path.name,path.read_bytes()))
            kinds.add(kind)
        reports=[self._workspace.set_cartographic_library(name,content)
                 for name,content in data]
        return {"cancelled":False,"libraries":reports,
                "status":self._workspace.cartography_status()}



    def save_tiled_export(self, ticket: str) -> dict:
        """Native Save As for large TIFF or ZIP, streamed from temporary disk.

        The browser never supplies a filesystem path and the source MAP
        remains untouched. This avoids the existing 120 MB in-memory export
        buffer limit, including for uncompressed TIFF tiles.
        """
        if self._tile_exports is None:
            raise ValueError("Obsługa kafelkowego eksportu jest niedostępna.")
        import tkinter as tk
        from tkinter import filedialog
        import shutil
        suggested, source = self._tile_exports.archive(ticket)
        extension=Path(suggested).suffix.lower()
        if extension not in (".tif", ".png", ".jpg", ".zip"):
            raise ValueError("Niedozwolony format dużego eksportu.")
        label=extension[1:].upper()
        root = tk.Tk()
        try:
            root.withdraw()
            root.attributes("-topmost", True)
            root.update()
            directory = (self._source_path.parent if self._source_path
                         else Path(read_last_map_directory(self._settings) or
                                   str(Path.home() / "Documents")))
            chosen_name = filedialog.asksaveasfilename(
                parent=root, initialdir=str(directory),
                initialfile=suggested,
                title="GeoStudio 2.0 — Zapisz mapę "+label,
                defaultextension=extension,
                filetypes=((label, "*"+extension),),
                confirmoverwrite=True)
        finally:
            root.destroy()
        if not chosen_name:
            return {"cancelled": True}
        chosen=Path(chosen_name)
        if chosen.suffix.lower() != extension:
            raise ValueError("Wybierz plik "+extension+".")
        if self._source_path and chosen.resolve() == self._source_path:
            raise ValueError("Nie wolno nadpisać pliku MAP.")
        fd, temporary = tempfile.mkstemp(
            prefix=".geostudio-tiles-",suffix=".tmp",dir=str(chosen.parent))
        try:
            with os.fdopen(fd, "wb") as out, source.open("rb") as inp:
                shutil.copyfileobj(inp, out, length=1024*1024)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, chosen)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        size=chosen.stat().st_size
        self._tile_exports.discard(ticket)
        return {"cancelled": False, "path": str(chosen), "bytes": size}

    def save_generated_export(self, ticket: str) -> dict:
        """Windows Save As for PNG/JPG/TIFF/DXF produced in the browser.

        The trusted in-memory workspace holds bytes behind a random ticket.
        JS can never pass a file path or make the native bridge overwrite the
        original MAP. The picker is created/destroyed on this worker thread.
        """
        import tkinter as tk
        from tkinter import filedialog

        suggested,extension,data=self._workspace.generated_export(ticket)
        known={"png":"PNG","jpg":"JPG","tif":"TIFF","dxf":"DXF","pdf":"PDF"}
        if extension not in known:
            raise ValueError("Niedozwolony typ eksportu.")
        root=tk.Tk()
        try:
            root.withdraw()
            root.attributes("-topmost",True)
            root.update()
            directory=(self._source_path.parent if self._source_path
                       else Path(read_last_map_directory(self._settings) or
                                 str(Path.home()/"Documents")))
            chosen_name=filedialog.asksaveasfilename(
                parent=root,
                initialdir=str(directory),
                initialfile=suggested,
                title="GeoStudio 2.0 — Zapisz eksport "+known[extension],
                defaultextension="."+extension,
                filetypes=((known[extension],"*."+extension),),
                confirmoverwrite=True)
        finally:
            root.destroy()
        if not chosen_name:
            return {"cancelled":True}
        chosen=Path(chosen_name)
        if chosen.suffix.lower()!="."+extension:
            raise ValueError("Wybierz plik ."+extension+".")
        if self._source_path and chosen.resolve()==self._source_path:
            raise ValueError("Nie wolno nadpisać otwartej mapy MAP.")
        fd,temporary=tempfile.mkstemp(
            prefix=".geostudio-export-",suffix=".tmp",dir=str(chosen.parent))
        try:
            with os.fdopen(fd,"wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary,chosen)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        self._workspace.generated_export(ticket,consume=True)
        return {"cancelled":False,"path":str(chosen),"bytes":len(data)}

    def save_map(self) -> dict:
        """Default Save As: bake same-code overlays when any exist."""
        return self._save_map(burn_cutouts=None)

    def check_update(self) -> dict:
        """Ręczne sprawdzenie aktualizacji z panelu programu."""
        from . import updater
        info = updater.check_for_update()
        if not info:
            return {"available": False, "current": updater.current_version()}
        return {"available": True, **info}

    def install_update(self) -> dict:
        """Pobiera i uruchamia instalator nowej wersji (zamyka program)."""
        from . import updater
        info = updater.check_for_update()
        if not info or not info.get("assetUrl"):
            return {"started": False, "reason": "Brak nowszej wersji."}
        installer = updater.download_installer(info["assetUrl"])
        updater.launch_installer(installer)
        return {"started": True}

    def save_over_source(self) -> dict:
        """Write the working copy back into the MAP the user opened.

        Deliberately destructive, so it asks first and keeps the previous
        file as ``<name>.geostudio-backup.MAP`` next to the original.
        """
        status = self._workspace.editing_status()
        if not status.get("documentToken"):
            raise ValueError("Najpierw otwórz mapę GEO-MAP.")
        path = self._source_path
        if path is None or not path.is_file():
            raise ValueError(
                "Ta mapa nie została otwarta z dysku. Użyj „Zapisz kopię mapy”.")
        burn_cutouts = bool(status.get("hasReversibleMasks"))
        if burn_cutouts:
            _, content, overlay_bytes = (
                self._workspace.export_native_cutouts(status["documentToken"]))
        else:
            _, content = self._workspace.export_positive_copy(
                status["documentToken"])
            overlay_bytes = self._workspace.export_topology_metadata(content)
        visual_bytes = self._workspace.export_visual_sidecar(content)
        epsg = self._workspace.metadata().get("mapEPSG")

        confirmed = _ask_yes_no(
            "GeoStudio 2.0 — zapis na oryginale",
            ("Zapisać zmiany w otwartym pliku?\n\n" + str(path) +
             "\n\nPoprzednia wersja zostanie zachowana jako " +
             path.stem + ".geostudio-backup.MAP"),
        )
        if not confirmed:
            return {"cancelled": True}

        backup = path.with_name(path.stem + ".geostudio-backup.MAP")
        companion = path.with_suffix(".geostudio-topology.json")
        visual_path = path.with_suffix(".geostudio.json")
        prj_path = path.with_suffix(".prj")
        try:
            previous = path.read_bytes()
        except OSError as exc:
            raise ValueError("Nie można odczytać pliku źródłowego: " + str(exc)) from exc
        _atomic_write(backup, previous)
        # Companions first: a MAP pointing at a missing sidecar is worse than
        # a sidecar newer than the MAP.
        if overlay_bytes:
            _atomic_write(companion, overlay_bytes)
        if visual_bytes:
            _atomic_write(visual_path, visual_bytes)
        if epsg:
            from geostudio.coordinates import output_prj_text
            _atomic_write(prj_path, output_prj_text(epsg).encode("utf-8"))
        _atomic_write(path, content)
        self._source_sha = sha256(content).hexdigest()
        self._workspace.mark_saved()
        try:
            self._recovery_store().discard(self._source_path)
        except (OSError, ValueError):
            pass
        return {"saved": True, "path": str(path), "bytes": len(content),
                "backup": str(backup)}

    def save_base_map(self) -> dict:
        """Explicit compatibility fallback: MAP without baked cutouts."""
        return self._save_map(burn_cutouts=False)

    def save_baked_map(self) -> dict:
        """Stage 6B: export native holes plus a separate reversible companion."""
        return self._save_map(burn_cutouts=True)

    def _save_map(self, *, burn_cutouts: bool | None) -> dict:
        """Save an explicitly named new MAP through an actual Windows Save As dialog.

        Unlike a browser Blob download, WebView2 can display and reliably
        persist this path. Never guess the destination or overwrite source.
        """
        status = self._workspace.editing_status()
        if not status.get("documentToken"):
            raise ValueError("Najpierw otwórz mapę GEO-MAP.")
        if burn_cutouts is None:
            burn_cutouts=bool(status.get("hasReversibleMasks"))
        if burn_cutouts:
            suggested_name,content,overlay_bytes=(
                self._workspace.export_native_cutouts(status["documentToken"]))
        else:
            suggested_name,content=self._workspace.export_positive_copy(
                status["documentToken"])
            overlay_bytes=self._workspace.export_topology_metadata(content)
        visual_bytes=self._workspace.export_visual_sidecar(content)
        directory = (self._source_path.parent if self._source_path
                     else Path(read_last_map_directory(self._settings) or
                               str(Path.home() / "Documents")))
        chosen_name = _ask_save_as(directory, suggested_name)
        if not chosen_name:
            return {"cancelled": True}
        chosen = Path(chosen_name)
        if chosen.suffix.casefold() != ".map":
            raise ValueError("Kopia musi mieć rozszerzenie .MAP.")
        # Choosing the opened file means "save over the original": route it to
        # the explicit in-place path, which keeps a backup and asks first.
        if (self._source_path is not None and
                chosen.resolve() == self._source_path):
            return self.save_over_source()
        epsg = self._workspace.metadata().get("mapEPSG")
        prj_path = chosen.with_suffix(".prj")
        companion=chosen.with_suffix(".geostudio-topology.json")
        visual_path=chosen.with_suffix(".geostudio.json")
        # Overwriting an existing MAP/JSON set is allowed, but never silently.
        if chosen.exists() or prj_path.exists():
            replace = _ask_yes_no(
                "GeoStudio 2.0 — nadpisać pliki?",
                ("Plik o tej nazwie już istnieje.\n\n" + str(chosen) +
                 "\n\nNadpisać go razem z plikami towarzyszącymi?"),
            )
            if not replace:
                return {"cancelled": True}
        fd,tmp=tempfile.mkstemp(prefix=".geostudio2-",suffix=".tmp",
                                dir=str(chosen.parent))
        tmp_companion=None
        tmp_visual=None
        committed=[]
        map_committed=False
        try:
            with os.fdopen(fd,"wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            for target,data,prefix in (
                (companion,overlay_bytes,".geostudio-topology-"),
                (visual_path,visual_bytes,".geostudio-visual-")
            ):
                if not data:continue
                extra_fd,temp=tempfile.mkstemp(
                    prefix=prefix,suffix=".tmp",dir=str(chosen.parent))
                if target==companion:tmp_companion=temp
                else:tmp_visual=temp
                with os.fdopen(extra_fd,"wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
            if epsg:
                from geostudio.coordinates import output_prj_text
                projection = output_prj_text(epsg)
                # Overwrite is confirmed above, so a plain replace is safe and
                # atomic; "x" would fail when the user chose an existing pair.
                committed.append(prj_path)
                _atomic_write(prj_path, projection.encode("utf-8"))
            if burn_cutouts or visual_bytes or epsg:
                # Publish the companions first. The MAP is committed last.
                if tmp_companion:
                    os.replace(tmp_companion,companion)
                    committed.append(companion)
                if tmp_visual:
                    os.replace(tmp_visual,visual_path)
                    committed.append(visual_path)
                os.replace(tmp,chosen)
                map_committed=True
            else:
                os.replace(tmp,chosen)
                map_committed=True
                if tmp_companion:os.replace(tmp_companion,companion)
        except Exception:
            if not map_committed:
                for target in committed:
                    try:target.unlink()
                    except OSError:pass
            raise
        finally:
            for candidate in (tmp,tmp_companion,tmp_visual):
                if candidate:
                    try:os.unlink(candidate)
                    except FileNotFoundError:pass
        try:
            save_last_map_directory(self._settings,chosen.parent)
        except OSError:
            pass
        # The work is on disk now, so the crash-recovery snapshot of the
        # source map is stale: drop it instead of leaving megabytes behind.
        if self._source_path is not None:
            try:
                self._recovery_store().discard(self._source_path)
            except (OSError, ValueError):
                pass
        return {"cancelled": False, "path": str(chosen),
                "bytes": len(content), "nativeCutouts": burn_cutouts,
                "topologyPath":str(companion) if overlay_bytes else None,
                 "visualPath":str(visual_path) if visual_bytes else None}
