"""Bounded, session-local storage for prepared raster previews and A1 readings.

Only compressed PNGs and small JSON results are retained. Recognition runs on
one background worker, independently of an HTTP caller's lifetime; reopening
tracing joins the same job instead of starting another model inference.
"""
from __future__ import annotations

from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
import json
import re
from threading import Lock, RLock
from typing import Callable

from .underlay_raster import MAX_PREVIEW_EDGE, MAX_RASTER_BYTES, MAX_RASTER_PIXELS


class RasterPreviewMissing(LookupError):
    """The bounded cache no longer contains this raster or its OCR result."""


class RasterOCRBusy(RuntimeError):
    """The one active inference and one queued image already occupy the worker."""


def raster_digest(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise ValueError("Nieprawidłowy identyfikator rastra.")
    return value.lower()


@dataclass(frozen=True)
class _Preview:
    content: bytes
    width: int
    height: int
    checksum: str


class RasterA1Cache:
    def __init__(self, recognizer: Callable[[bytes], dict] | None = None, *,
                 max_bytes: int = 96 * 1024 * 1024, max_images: int = 4,
                 max_result_bytes: int = 8 * 1024 * 1024, max_results: int = 16,
                 max_pending: int = 2, wait_seconds: float = 90):
        self._recognizer = recognizer
        self._max_bytes = max(1, int(max_bytes))
        self._max_images = max(1, int(max_images))
        self._max_result_bytes = max(1, int(max_result_bytes))
        self._max_results = max(1, int(max_results))
        self._max_pending = max(1, int(max_pending))
        self._wait_seconds = max(.001, float(wait_seconds))
        self._lock = RLock()
        self._restore_lock = Lock()
        self._images: OrderedDict[str, _Preview] = OrderedDict()
        self._results: OrderedDict[str, tuple[str, bytes]] = OrderedDict()
        self._pending: dict[str, Future] = {}
        self._image_bytes = self._result_bytes = 0
        self._executor: ThreadPoolExecutor | None = None
        self._closed = False

    def remember(self, digest: str, content: bytes, metadata: dict) -> None:
        """Register the PNG already decoded by the normal import/restore route."""
        digest = raster_digest(digest)
        width, height = metadata.get("width"), metadata.get("height")
        if (type(width) is not int or type(height) is not int
                or not 0 < width <= MAX_PREVIEW_EDGE or not 0 < height <= MAX_PREVIEW_EDGE
                or width * height > MAX_RASTER_PIXELS):
            raise ValueError("Nieprawidłowy rozmiar podglądu rastra.")
        if (not isinstance(content, bytes) or not content.startswith(b"\x89PNG\r\n\x1a\n")
                or len(content) > min(MAX_RASTER_BYTES, self._max_bytes)):
            raise ValueError("Podgląd rastra jest nieprawidłowy lub zbyt duży.")
        preview = _Preview(content, width, height, sha256(content).hexdigest())
        with self._lock:
            if self._closed:
                raise RuntimeError("Odczyt A1 został zamknięty.")
            old = self._images.pop(digest, None)
            if old:
                self._image_bytes -= len(old.content)
            previous = self._results.get(digest)
            if previous and previous[0] != preview.checksum:
                self._result_bytes -= len(self._results.pop(digest)[1])
            self._images[digest] = preview
            self._image_bytes += len(content)
            while len(self._images) > self._max_images or self._image_bytes > self._max_bytes:
                _, removed = self._images.popitem(last=False)
                self._image_bytes -= len(removed.content)

    def contains(self, digest: str) -> bool:
        digest = raster_digest(digest)
        with self._lock:
            return digest in self._images or digest in self._results or digest in self._pending

    def restore(self, digest: str, loader: Callable[[], tuple[bytes, dict] | None]) -> None:
        """Serialize cache-miss decoding and coalesce callers for one raster."""
        digest = raster_digest(digest)
        with self._restore_lock:
            if self.contains(digest):
                return
            with self._lock:
                if len(self._pending) >= self._max_pending:
                    raise RasterOCRBusy("Trwa odczyt A1 z innego rastra. Spróbuj ponownie za chwilę.")
            restored = loader()
            if restored is not None:
                self.remember(digest, *restored)

    def _run(self, digest: str, preview: _Preview) -> bytes:
        recognize = self._recognizer
        if recognize is None:
            # Importing the app or using raster tracing must not load ONNX or
            # initialize its model until A1 recognition is actually requested.
            from .raster_a1 import recognize_raster_a1
            recognize = recognize_raster_a1
        result = recognize(preview.content)
        if (not isinstance(result, dict) or result.get("width") != preview.width
                or result.get("height") != preview.height
                or not isinstance(result.get("annotations"), list)
                or len(result["annotations"]) > 4096):
            raise ValueError("Odczyt A1 zwrócił nieprawidłowe współrzędne obrazu.")
        encoded = json.dumps({**result, "digest": digest}, ensure_ascii=False,
                             allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > 4 * 1024 * 1024:
            raise ValueError("Wynik odczytu A1 przekracza limit rozmiaru.")
        with self._lock:
            current = self._images.get(digest)
            if not self._closed and (current is None or current.checksum == preview.checksum):
                previous = self._results.pop(digest, None)
                if previous:
                    self._result_bytes -= len(previous[1])
                self._results[digest] = (preview.checksum, encoded)
                self._result_bytes += len(encoded)
                while (len(self._results) > self._max_results
                       or self._result_bytes > self._max_result_bytes):
                    _, removed = self._results.popitem(last=False)
                    self._result_bytes -= len(removed[1])
        return encoded

    def _finished(self, digest: str, future: Future) -> None:
        with self._lock:
            if self._pending.get(digest) is future:
                del self._pending[digest]

    def begin(self, digest: str) -> Future:
        digest = raster_digest(digest)
        with self._lock:
            if self._closed:
                raise RuntimeError("Odczyt A1 został zamknięty.")
            saved = self._results.get(digest)
            if saved:
                self._results.move_to_end(digest)
                ready = Future()
                ready.set_result(saved[1])
                return ready
            if digest in self._pending:
                return self._pending[digest]
            preview = self._images.get(digest)
            if preview is None:
                raise RasterPreviewMissing("Podgląd rastra nie jest już dostępny w pamięci.")
            if len(self._pending) >= self._max_pending:
                raise RasterOCRBusy("Trwa odczyt A1 z innego rastra. Spróbuj ponownie za chwilę.")
            self._images.move_to_end(digest)
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="geostudio-a1")
            future = self._executor.submit(self._run, digest, preview)
            self._pending[digest] = future
            future.add_done_callback(lambda completed: self._finished(digest, completed))
            return future

    def recognize(self, digest: str) -> dict:
        """Wait at most 90s; inference remains reusable after timeout/HTTP abort."""
        encoded = self.begin(digest).result(timeout=self._wait_seconds)
        # Independent response objects protect the cached result from callers.
        return json.loads(encoded)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._images.clear()
            self._results.clear()
            self._image_bytes = self._result_bytes = 0
            executor = self._executor
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
