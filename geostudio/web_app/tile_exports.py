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
import os
from shutil import disk_usage
from .mosaic_tiff import tiff_header

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


@dataclass
class _MosaicSession:
    path: Path
    filename: str
    token: str
    revision: int
    columns: int
    rows: int
    format: str
    next_index: int
    ready: bool
    width: int
    height: int
    tile_width: int
    tile_height: int
    pixel_offset: int


class TiledArchiveStore:
    """Only the localhost API and native bridge can access generated paths."""

    def __init__(self, workspace):
        self.workspace = workspace
        self._directory = TemporaryDirectory(prefix="geostudio-export-")
        self._lock = RLock()
        self._sessions: dict[str, _Session | _MosaicSession] = {}

    def _same_document(self, entry: _Session | _MosaicSession) -> None:
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

    def _get(self, ticket: str) -> _Session | _MosaicSession:
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
            if (not isinstance(entry, _Session) or entry.ready or\n                    index != entry.next_index or index >= entry.rows * entry.columns):
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
            if not isinstance(entry, _Session):
                raise ValueError("Zła metoda zakończenia eksportu TIFF.")
            if entry.next_index != entry.rows * entry.columns:
                raise ValueError("Nie wszystkie arkusze zostały zapisane.")
            entry.ready = True
            return {"ticket": ticket, "filename": entry.filename,
                    "bytes": entry.path.stat().st_size,
                    "tiles": entry.next_index}


    def begin_mosaic(self, document_token: str, revision: int,
                     filename: str, width: int, height: int, dpi: int,
                     tile_width: int, tile_height: int) -> str:
        """Allocate a single RGB TIFF/BigTIFF on disk, not a ZIP.

        Pixels are written at image-global offsets. No per-tile frame,
        legend or screenshot DPI is embedded in the final mosaic.
        """
        if (type(document_token) is not str or not document_token or
                type(revision) is not int or
                not isinstance(filename, str) or
                not _ARCHIVE_NAME.fullmatch(filename) or
                type(tile_width) is not int or type(tile_height) is not int or
                not 1 <= tile_width <= 4096 or not 1 <= tile_height <= 4096 or
                tile_width * tile_height > 12_000_000):
            raise ValueError("Nieprawidłowe parametry pojedynczego TIFF.")
        header, pixel_offset, _ = tiff_header(width, height, dpi)
        total_bytes = pixel_offset + width * height * 3
        if total_bytes > 16 * 1024**3:
            raise ValueError("Mapa przekracza limit 16 GiB dla pojedynczego TIFF.")
        columns = (width + tile_width - 1) // tile_width
        rows = (height + tile_height - 1) // tile_height
        if columns * rows > 1024:
            raise ValueError("Mapa wymaga ponad 1024 fragmentów — zawęź zakres.")
        status = self.workspace.editing_status()
        if (document_token != status.get("documentToken") or
                revision != status.get("revision")):
            raise RuntimeError("Mapa zmieniła się podczas eksportu.")
        with self._lock:
            for ticket in tuple(self._sessions):
                self._discard_unlocked(ticket)
            # Sparse-file truncation alone is not a space reservation.
            if total_bytes + 128 * 1024**2 > disk_usage(self._directory.name).free:
                raise ValueError("Za mało wolnego miejsca na dysku na TIFF.")
            ticket = token_urlsafe(24)
            path = Path(self._directory.name) / (ticket + ".tif")
            try:
                with path.open("w+b") as output:
                    output.write(header)
                    output.truncate(total_bytes)
            except OSError as exc:
                path.unlink(missing_ok=True)
                raise ValueError("Nie można utworzyć pliku TIFF na dysku.") from exc
            self._sessions[ticket] = _MosaicSession(
                path=path, filename=filename + "_calosc.tif",
                token=document_token, revision=revision,
                columns=columns, rows=rows, format="mosaic",
                next_index=0, ready=False, width=width, height=height,
                tile_width=tile_width, tile_height=tile_height,
                pixel_offset=pixel_offset,
            )
            return ticket

    def add_mosaic(self, ticket: str, index: int, data: bytes) -> None:
        """Write one RGB8 tile directly to its absolute TIFF coordinates."""
        if type(index) is not int or not isinstance(data, bytes):
            raise ValueError("Niepoprawny fragment obrazu TIFF.")
        with self._lock:
            entry = self._get(ticket)
            if not isinstance(entry, _MosaicSession) or entry.ready:
                raise ValueError("Eksport TIFF jest zamknięty lub nie istnieje.")
            if index != entry.next_index or index >= entry.rows * entry.columns:
                raise ValueError("Fragmenty muszą przychodzić kolejno.")
            row, col = divmod(index, entry.columns)
            x, y = col * entry.tile_width, row * entry.tile_height
            width = min(entry.tile_width, entry.width - x)
            height = min(entry.tile_height, entry.height - y)
            if len(data) != width * height * 3 or len(data) > MAX_TILE_BYTES:
                raise ValueError("Nieprawidłowy rozmiar danych RGB fragmentu.")
            stride = width * 3
            try:
                with entry.path.open("r+b") as output:
                    for local_y in range(height):
                        offset = (entry.pixel_offset +
                                  ((y + local_y) * entry.width + x) * 3)
                        output.seek(offset)
                        start = local_y * stride
                        output.write(data[start:start + stride])
            except OSError as exc:
                raise ValueError("Brak miejsca lub błąd zapisu TIFF.") from exc
            entry.next_index += 1

    def finish_mosaic(self, ticket: str) -> dict:
        with self._lock:
            entry = self._get(ticket)
            if not isinstance(entry, _MosaicSession):
                raise ValueError("Nieprawidłowy eksport TIFF.")
            if entry.next_index != entry.rows * entry.columns:
                raise ValueError("Brakuje fragmentów obrazu TIFF.")
            entry.ready = True
            return {"ticket": ticket, "filename": entry.filename,
                    "bytes": entry.path.stat().st_size,
                    "tiles": entry.next_index, "format": "tiff"}

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
