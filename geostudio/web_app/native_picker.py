"""Native Windows file picker with a persisted last map directory.

Only invoked from a pywebview window's JS API, never from an HTTP endpoint.
The user selects the file with a native OS dialog; no arbitrary filesystem
paths are accepted from browser JavaScript. The absolute path stays local
to the native bridge, and only GEO-MAP metadata is returned to the UI.
"""
from __future__ import annotations

import json
from hashlib import sha256
import os
from pathlib import Path
import tempfile

from .data import MAX_MAP_BYTES, PreviewWorkspace
from .recovery import LocalRecoveryStore


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
                "Użyj przycisku Z dysku."
            ) from exc
        if not filename:
            return {"cancelled": True}
        chosen = Path(filename)
        if chosen.suffix.casefold() != ".map" or not chosen.is_file():
            raise ValueError("Wybierz prawidłowy plik GEO-MAP .MAP.")
        if not 0 < chosen.stat().st_size <= MAX_MAP_BYTES:
            raise ValueError("Plik MAP jest pusty lub przekracza limit 512 MB.")
        raw=chosen.read_bytes()
        meta=self._workspace.load_map(raw,chosen.name)
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
        if extension not in (".tif", ".zip"):
            raise ValueError("Niedozwolony format dużego eksportu.")
        label="TIFF" if extension==".tif" else "ZIP"
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
        import tkinter as tk
        from tkinter import filedialog
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
        # A MAP and its two companions are published as a new project;
        # never overwrite existing files when any companion is required.
        if (burn_cutouts or visual_bytes) and chosen.exists():
            raise ValueError("Wybierz nową nazwę MAP, aby nie nadpisać pary MAP/JSON.")
        companion=chosen.with_suffix(".geostudio-topology.json")
        visual_path=chosen.with_suffix(".geostudio.json")
        if overlay_bytes and companion.exists():
            raise ValueError("Istnieje już plik topologii. Wybierz nową nazwę.")
        if visual_bytes and visual_path.exists():
            raise ValueError("Istnieje już plik stylów. Wybierz nową nazwę.")
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
            if burn_cutouts or visual_bytes:
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
        return {"cancelled": False, "path": str(chosen),
                "bytes": len(content), "nativeCutouts": burn_cutouts,
                "topologyPath":str(companion) if overlay_bytes else None,
                 "visualPath":str(visual_path) if visual_bytes else None}
