"""Bounded, on-disk ZIP assembly for large full-resolution map exports.

A tile arrives as an individually rendered PNG/JPG/TIFF. The archive is
assembled incrementally so the browser and native bridge never buffer a
hundreds-of-megapixels image or a multi-gigabyte ZIP in RAM.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from threading import RLock
from zipfile import ZIP_STORED, ZipFile
import re

MAX_TILE_BYTES = 120 * 1024 * 1024
MAX_TILES = 256
_ARCHIVE_NAME = re.compile(r"^[\w .()-]{1,90}$", re.UNICODE)


@dataclass
class _Session:
    path: Path
    filename: str
    token: str
    revision: int
    columns: int
    rows: int
    format: str
    next_index: int = 0
    ready: bool = False


class TiledArchiveStore:
    """Only the localhost API and native bridge can access generated paths."""

    def __init__(self, workspace):
        self.workspace = workspace
        self._directory = TemporaryDirectory(prefix="geostudio-export-")
        self._lock = RLock()
        self._sessions: dict[str, _Session] = {}

    def _same_document(self, entry: _Session) -> None:
        status = self.workspace.editing_status()
        if (status.get("documentToken") != entry.token or
                status.get("revision") != entry.revision):
            raise RuntimeError("Mapa zmieniła się podczas eksportu.")

    def begin(self, document_token: str, revision: int, filename: str,
              fmt: str, columns: int, rows: int, manifest: str) -> str:
        if (type(document_token) is not str or not document_token or
                type(revision) is not int or
                fmt not in ("png", "jpeg", "tiff") or
                type(columns) is not int or type(rows) is not int or
                not 1 <= columns <= 64 or not 1 <= rows <= 64 or
                columns * rows > MAX_TILES or
                not isinstance(filename, str) or
                not _ARCHIVE_NAME.fullmatch(filename) or
                not isinstance(manifest, str) or len(manifest) > 32768):
            raise ValueError("Niepoprawne parametry eksportu kafelkowego.")
        status = self.workspace.editing_status()
        if (document_token != status.get("documentToken") or
                revision != status.get("revision")):
            raise RuntimeError("Mapa zmieniła się podczas eksportu.")
        with self._lock:
            # Only one large ZIP at a time. Drop unclaimed intermediate files
            # from previous runs to avoid filling the user's temp directory.
            for ticket in tuple(self._sessions):
                self._discard_unlocked(ticket)
            ticket = token_urlsafe(24)
            path = Path(self._directory.name) / (ticket + ".zip")
            with ZipFile(path, "w", compression=ZIP_STORED, allowZip64=True) as archive:
                archive.writestr("INFORMACJE.txt", manifest.encode("utf-8"))
            self._sessions[ticket] = _Session(
                path, filename + "_kafelki.zip", document_token, revision,
                columns, rows, fmt)
            return ticket

    def _get(self, ticket: str) -> _Session:
        if not isinstance(ticket, str):
            raise LookupError("Nieprawidłowy identyfikator eksportu.")
        result = self._sessions.get(ticket)
        if result is None:
            raise LookupError("Eksport wygasł. Uruchom go ponownie.")
        self._same_document(result)
        return result

    def add(self, ticket: str, index: int, data: bytes) -> None:
        if (type(index) is not int or not isinstance(data, bytes) or
                not 0 < len(data) <= MAX_TILE_BYTES):
            raise ValueError("Niewłaściwy rozmiar lub numer fragmentu.")
        with self._lock:
            entry = self._get(ticket)
            if entry.ready or index != entry.next_index or index >= entry.rows * entry.columns:
                raise ValueError("Fragmenty mapy muszą być zapisane w kolejności.")
            signatures = {
                "png": data.startswith(b"\x89PNG\r\n\x1a\n"),
                "jpeg": data.startswith(b"\xff\xd8\xff"),
                "tiff": data.startswith((b"II*\x00", b"MM\x00*")),
            }
            if not signatures[entry.format]:
                raise ValueError("Format fragmentu nie zgadza się z eksportem.")
            row, col = divmod(index, entry.columns)
            extension = {"png": "png", "jpeg": "jpg", "tiff": "tif"}[entry.format]
            name = f"mapa_r{row + 1:03d}_c{col + 1:03d}.{extension}"
            with ZipFile(entry.path, "a", compression=ZIP_STORED,
                         allowZip64=True) as archive:
                archive.writestr(name, data)
            entry.next_index += 1

    def finish(self, ticket: str) -> dict:
        with self._lock:
            entry = self._get(ticket)
            if entry.next_index != entry.rows * entry.columns:
                raise ValueError("Nie wszystkie arkusze zostały zapisane.")
            entry.ready = True
            return {"ticket": ticket, "filename": entry.filename,
                    "bytes": entry.path.stat().st_size,
                    "tiles": entry.next_index}

    def archive(self, ticket: str) -> tuple[str, Path]:
        with self._lock:
            entry = self._get(ticket)
            if not entry.ready:
                raise ValueError("Archiwum nie jest jeszcze gotowe.")
            return entry.filename, entry.path

    def discard(self, ticket: str) -> None:
        with self._lock:
            self._discard_unlocked(ticket)

    def _discard_unlocked(self, ticket: str) -> None:
        entry = self._sessions.pop(ticket, None)
        if entry is not None:
            entry.path.unlink(missing_ok=True)
