"""Prepared-image OCR caching, bounded concurrency and document-safe HTTP reads."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
from threading import Event

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from conftest import MapBuilder
from geostudio.web_app import server
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.raster_a1_cache import (
    RasterA1Cache, RasterOCRBusy, RasterPreviewMissing,
)
from geostudio.web_app.underlay_raster import prepare_raster


def source_image(format_name="PNG", color="white"):
    image = Image.new("RGB", (40, 32), color)
    output = BytesIO()
    image.save(output, format=format_name)
    return output.getvalue()


def reading(content):
    with Image.open(BytesIO(content)) as image:
        width, height = image.size
    return {"width": width, "height": height, "annotations": [
        {"text": "178", "confidence": .99, "status": "ok", "source": "callout",
         "box": [1, 2, 10, 12], "anchor": [width / 2, height / 2], "hasLeader": True},
    ]}


def register(cache, color):
    raw = source_image(color=color)
    png, metadata = prepare_raster(raw)
    digest = sha256(raw).hexdigest()
    cache.remember(digest, png, metadata)
    return digest, png


def map_content(name="P"):
    return MapBuilder().object("5216", name, {},
                               [(0, 0), (0, 100), (100, 100), (100, 0)]).build()


def make_app(monkeypatch, recognizer, **limits):
    cache = RasterA1Cache(recognizer, **limits)
    monkeypatch.setattr(server, "RasterA1Cache", lambda: cache)
    workspace = PreviewWorkspace()
    metadata = workspace.load_map(map_content(), "first.MAP")
    app = server.create_app(workspace)
    headers = {"X-GeoStudio-Token": app.state.api_token,
               "X-Map-Token": metadata["documentToken"]}
    return app, cache, workspace, headers


def test_completed_readings_survive_png_eviction_and_are_independent():
    calls = []
    cache = RasterA1Cache(lambda content: (calls.append(content), reading(content))[1],
                          max_images=1, max_results=1)
    try:
        first, _ = register(cache, "white")
        result = cache.recognize(first)
        result["annotations"][0]["text"] = "wrong external mutation"
        second, _ = register(cache, "yellow")
        assert cache.recognize(first)["annotations"][0]["text"] == "178"
        assert len(calls) == 1, "A small cached result must not require the evicted image"
        cache.recognize(second)
        with pytest.raises(RasterPreviewMissing):
            cache.recognize(first)
    finally:
        cache.close()


def test_png_memory_budget_evicts_oldest_even_below_image_count():
    samples = [prepare_raster(source_image(color=color))[0] for color in ("white", "yellow")]
    cache = RasterA1Cache(reading, max_images=4, max_bytes=max(map(len, samples)))
    try:
        first, _ = register(cache, "white")
        second, _ = register(cache, "yellow")
        assert not cache.contains(first)
        assert cache.contains(second)
        assert cache.recognize(second)["annotations"][0]["text"] == "178"
    finally:
        cache.close()


def test_timeout_and_repeated_call_join_one_job_and_queue_is_bounded():
    started, release = Event(), Event()
    calls = []
    def recognize(content):
        calls.append(content)
        started.set()
        assert release.wait(5)
        return reading(content)
    cache = RasterA1Cache(recognize, wait_seconds=.01)
    try:
        first, _ = register(cache, "white")
        second, _ = register(cache, "yellow")
        third, _ = register(cache, "green")
        task = cache.begin(first)
        assert started.wait(2)
        assert cache.begin(first) is task
        with pytest.raises(TimeoutError):
            cache.recognize(first)
        waiting = cache.begin(second)
        with pytest.raises(RasterOCRBusy):
            cache.begin(third)
        release.set()
        task.result(timeout=2)
        waiting.result(timeout=2)
        assert cache.recognize(first)["digest"] == first
        assert len(calls) == 2, "Only one inference per raster, including after a timeout"
    finally:
        release.set()
        cache.close()


def test_concurrent_cache_misses_decode_one_saved_image_once():
    started, release = Event(), Event()
    raw = source_image("TIFF")
    digest = sha256(raw).hexdigest()
    calls = []
    def load():
        calls.append(True)
        started.set()
        assert release.wait(5)
        return prepare_raster(raw)
    cache = RasterA1Cache(reading)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(cache.restore, digest, load)
            assert started.wait(2)
            second = pool.submit(cache.restore, digest, load)
            release.set()
            first.result(timeout=2)
            second.result(timeout=2)
        assert len(calls) == 1
        assert cache.recognize(digest)["annotations"][0]["text"] == "178"
    finally:
        release.set()
        cache.close()


@pytest.mark.parametrize("format_name", ["PNG", "JPEG", "TIFF", "PDF"])
def test_prepare_cache_ocr_uses_normalized_png_coordinates(monkeypatch, format_name):
    calls = []
    def recognize(content):
        assert content.startswith(b"\x89PNG\r\n\x1a\n")
        calls.append(content)
        return reading(content)
    app, cache, workspace, headers = make_app(monkeypatch, recognize)
    with TestClient(app) as client:
        original = source_image(format_name)
        imported = client.post("/api/underlay/raster/prepare", content=original, headers=headers)
        assert imported.status_code == 200, imported.text
        digest = imported.headers["X-Raster-Digest"]
        before = workspace.editing_status()
        for _ in range(2):
            response = client.post("/api/underlay/raster/a1", json={"digest": digest}, headers=headers)
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["digest"] == sha256(original).hexdigest()
            assert body["width"] == int(imported.headers["X-Raster-Width"])
            assert body["height"] == int(imported.headers["X-Raster-Height"])
            assert body["annotations"][0]["anchor"] == [body["width"] / 2, body["height"] / 2]
        assert len(calls) == 1
        assert calls[0] == imported.content, "The existing prepared PNG goes straight to OCR"
        assert workspace.editing_status() == before, "OCR must not modify MAP or its revision"


def test_ocr_http_requires_current_document_and_bounds_payload(monkeypatch):
    app, _, _, headers = make_app(monkeypatch, reading)
    monkeypatch.setattr(server.raster_memory, "raster_bytes", lambda *_: None)
    with TestClient(app) as client:
        route = "/api/underlay/raster/a1"
        assert client.post(route, json={"digest": "0" * 64}).status_code == 403
        stale = {**headers, "X-Map-Token": "old-map"}
        assert client.post(route, json={"digest": "0" * 64}, headers=stale).status_code == 409
        assert client.post(route, json={"digest": "../../image.png"}, headers=headers).status_code == 400
        assert client.post(route, json={"digest": "0" * 64, "extra": "x" * 4096}, headers=headers).status_code == 413
        missing = client.post(route, json={"digest": "0" * 64}, headers=headers)
        assert missing.status_code == 404
        assert missing.json()["code"] == "raster_preview_missing"


@pytest.mark.parametrize("restore_first", [False, True])
def test_calibration_restore_or_cache_miss_reuses_saved_original(monkeypatch, restore_first):
    raw = source_image("TIFF")
    digest = sha256(raw).hexdigest()
    reads, calls = [], []
    def saved(map_key, requested):
        reads.append((map_key, requested))
        return raw if requested == digest else None
    app, _, workspace, headers = make_app(monkeypatch,
        lambda content: (calls.append(content), reading(content))[1])
    monkeypatch.setattr(server.raster_memory, "raster_bytes", saved)
    with TestClient(app) as client:
        if restore_first:
            restored = client.get("/api/underlay/calibrations/" + digest, headers=headers)
            assert restored.status_code == 200
        response = client.post("/api/underlay/raster/a1", json={"digest": digest}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["annotations"][0]["text"] == "178"
        assert len(reads) == 1, "Restore already registered its PNG; OCR does not decode the source again"
        assert reads[0] == (workspace.metadata()["rasterMapKey"], digest)
        assert len(calls) == 1


def test_model_failure_is_not_reported_as_missing_raster(monkeypatch):
    def unavailable(_):
        raise FileNotFoundError("bundled model unavailable")
    app, _, _, headers = make_app(monkeypatch, unavailable)
    with TestClient(app) as client:
        imported = client.post("/api/underlay/raster/prepare", content=source_image(), headers=headers)
        digest = imported.headers["X-Raster-Digest"]
        response = client.post("/api/underlay/raster/a1", json={"digest": digest}, headers=headers)
        assert response.status_code == 503
        assert response.json()["code"] == "ocr_unavailable"


def test_slow_ocr_returns_bounded_timeout_and_keeps_result_for_reopen(monkeypatch):
    started, release = Event(), Event()
    calls = []
    def recognize(content):
        calls.append(content)
        started.set()
        assert release.wait(5)
        return reading(content)
    app, cache, _, headers = make_app(monkeypatch, recognize, wait_seconds=.01)
    with TestClient(app) as client:
        imported = client.post("/api/underlay/raster/prepare", content=source_image(), headers=headers)
        digest = imported.headers["X-Raster-Digest"]
        try:
            response = client.post("/api/underlay/raster/a1", json={"digest": digest}, headers=headers)
            assert started.is_set()
            assert response.status_code == 504
            assert response.json()["code"] == "ocr_timeout"
            pending = cache.begin(digest)
            release.set()
            pending.result(timeout=2)
            ready = client.post("/api/underlay/raster/a1", json={"digest": digest}, headers=headers)
            assert ready.status_code == 200
            assert len(calls) == 1
        finally:
            release.set()


def test_ocr_finishing_after_another_map_is_opened_is_rejected(monkeypatch):
    started, release = Event(), Event()
    def recognize(content):
        started.set()
        assert release.wait(5)
        return reading(content)
    app, _, workspace, headers = make_app(monkeypatch, recognize)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        imported = client.post("/api/underlay/raster/prepare", content=source_image(), headers=headers)
        digest = imported.headers["X-Raster-Digest"]
        pending = pool.submit(client.post, "/api/underlay/raster/a1", json={"digest": digest}, headers=headers)
        try:
            assert started.wait(2)
            workspace.load_map(map_content("Q"), "second.MAP")
        finally:
            release.set()
        assert pending.result(timeout=3).status_code == 409
