"""Bounded independent MAP sessions for the classic multi-document editor."""
from __future__ import annotations

import os
import subprocess
import sys
import threading

from dataclasses import dataclass, field
from secrets import token_hex
from threading import RLock

from .data import PreviewWorkspace
from .tile_exports import TiledArchiveStore
from .native_picker import NativeMapPicker

MAX_DOCUMENTS = 10


@dataclass
class DocumentSession:
    workspace: PreviewWorkspace
    tile_exports: TiledArchiveStore
    native: NativeMapPicker
    native_lock: RLock = field(default_factory=RLock)


def make_session(workspace=None):
    workspace = workspace if workspace is not None else PreviewWorkspace()
    tiles = TiledArchiveStore(workspace)
    return DocumentSession(workspace, tiles, NativeMapPicker(workspace, tile_exports=tiles))


class DocumentRegistry:
    def __init__(self, initial=None):
        self._lock = RLock()
        self._sessions = {}
        self.initial_id = self.create(initial)

    def create(self, workspace=None):
        with self._lock:
            if len(self._sessions) >= MAX_DOCUMENTS:
                raise ValueError(f"Można otworzyć maksymalnie {MAX_DOCUMENTS} mapy naraz.")
            key = token_hex(16)
            self._sessions[key] = make_session(workspace)
            return key

    def get(self, key):
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                raise KeyError("Zakładka mapy została zamknięta.")
            return session

    def ids(self):
        with self._lock:
            return list(self._sessions)

    def close(self, key, *, discard=False):
        with self._lock:
            session = self.get(key)
            if session.workspace.editing_status().get("dirty") and not discard:
                raise ValueError("Mapa ma niezapisane zmiany.")
            del self._sessions[key]
            # Any in-flight request holds its own reference to this isolated
            # session; it can never modify a different tab.


class DocumentNativeBridge:
    """Only these existing, document-scoped operations reach the native picker."""
    _ALLOWED = frozenset({"open_map", "open_raster", "open_libraries", "save_recovery",
                          "restore_recovery", "save_map", "save_over_source",
                          "save_base_map", "save_baked_map", "save_tiled_export",
                          "save_generated_export"})

    def __init__(self, registry, access_gate=None):
        self._registry = registry
        self._access_gate = access_gate

    def document_call(self, document_id, operation, args):
        if operation not in self._ALLOWED or not isinstance(args, list):
            raise ValueError("Nieprawidłowa operacja natywna.")
        session = self._registry.get(document_id)
        with session.native_lock:
            if self._access_gate is not None and not self._access_gate.allows_native(operation):
                raise PermissionError("Brak aktywnego dostępu. Zapisz otwarte mapy.")
            return getattr(session.native, operation)(*args)

    def change_account(self) -> dict:
        """Open a fresh login without killing this potentially dirty workspace."""
        if self._access_gate is None or not self._access_gate.status().get("loggedOut"):
            return {"started": False, "reason": "Najpierw wyloguj bieżące konto."}
        if getattr(sys, "frozen", False):
            args = [sys.executable, "--login"]
        else:
            args = [sys.executable, "-m", "geostudio.web_app", "--login"]
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
        try:
            subprocess.Popen(args, env=env)
        except OSError:
            return {"started": False, "reason": "Uruchom GeoStudio ponownie z opcją --login."}
        return {"started": True}

    # Sprawdzanie i instalacja aktualizacji nie zależą od konkretnej mapy,
    # więc muszą być dostępne także z paska zakładek (bez document_id).
    def check_update(self) -> dict:
        if self._access_gate is not None:
            return {"available": False, "reason": "Aktualizacje chronionej wersji są wyłączone."}
        from . import updater
        info = updater.check_for_update()
        if not info:
            return {"available": False, "current": updater.current_version()}
        return {"available": True, **info}

    def install_update(self) -> dict:
        if self._access_gate is not None:
            return {"started": False, "reason": "Aktualizacje chronionej wersji są wyłączone."}
        from . import updater
        info = updater.check_for_update()
        if not info or not info.get("assetUrl"):
            return {"started": False, "reason": "Brak nowszej wersji."}
        updater.start_update(info["assetUrl"], info["version"])
        threading.Timer(0.6, lambda: os._exit(0)).start()
        return {"started": True}


class ScopedAttribute:
    """Resolve the session per HTTP request, including Starlette threadpool calls."""
    def __init__(self, context, attribute):
        self._context = context
        self._attribute = attribute

    def __getattr__(self, name):
        return getattr(getattr(self._context.get(), self._attribute), name)
