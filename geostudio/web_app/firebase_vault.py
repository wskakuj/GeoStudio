"""Remember only the Firebase refresh token, encrypted by Windows DPAPI."""
from __future__ import annotations

import ctypes
import json
import os
import tempfile
from pathlib import Path


def _dpapi(data: bytes, decrypt: bool) -> bytes:
    if os.name != "nt":
        raise OSError("Windows DPAPI is unavailable")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    common = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
              ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt.CryptProtectData.argtypes = common
    crypt.CryptProtectData.restype = wintypes.BOOL
    crypt.CryptUnprotectData.argtypes = common
    crypt.CryptUnprotectData.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    # CRYPTPROTECT_UI_FORBIDDEN; current Windows user, not machine-wide.
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel.LocalFree(ctypes.cast(target.pbData, ctypes.c_void_p))


class WindowsSessionVault:
    def __init__(self, project_id, path=None, crypt=_dpapi):
        self.project_id = project_id
        self.path = (Path(path) if path is not None else
                     Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
                     / "GeoStudio2" / "firebase-session.bin")
        self._crypt = crypt

    def load(self):
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(65537)
        except FileNotFoundError:
            return None
        if not 0 < len(raw) <= 65536:
            raise ValueError("invalid encrypted session")
        payload = json.loads(self._crypt(raw, True))
        if not isinstance(payload, dict) or payload.get("project") != self.project_id:
            return None
        token = payload.get("refreshToken")
        if not isinstance(token, str) or not 1 <= len(token) <= 16384:
            raise ValueError("invalid refresh token")
        return token

    def save(self, refresh_token):
        protected = self._crypt(json.dumps({
            "project": self.project_id, "refreshToken": refresh_token,
        }).encode("utf-8"), False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".firebase-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(protected)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    def clear(self):
        self.path.unlink(missing_ok=True)
