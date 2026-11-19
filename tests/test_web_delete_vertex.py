"""Remove GEO-MAP P records with same-code topology and atomic history."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.geomap import GeoMap
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app


def map_bytes():
    return (MapBuilder(ext=(5000, -10, -10, 80, 80))
        .object("5310", "A", {"A1": "b"},
                [(0, 0), (5, 0), (10, 0), (10, 10), (0, 10)])
        .object("5310", "B", {"A1": "b"},
                [(0, 0), (5, 0), (10, 0), (10, -5), (0, -5)])
        .object("5220", "LAND", {"A1": "R"},
                [(0, 0), (5, 0), (10, 0), (10, -8), (0, -8)])
        .object("5230", "FOREST", {"A1": "LsV"},
                [(20, 0), (25, 0), (30, 0), (30, 10), (20, 10)])
        .raw(":UNKNOWN[zachowaj bez zmian]")
        .build())


def state(raw=None):
    ws = PreviewWorkspace()
    ws.load_map(raw if raw is not None else map_bytes(), "MOKRA WIEŚ.MAP")
    return ws


def auth(ws):
    status = ws.editing_status()
    return {"document_token": status["documentToken"],
            "revision": status["revision"]}


def source_records(doc, uid):
    obj = doc.by_id[uid]
    return doc.lines[obj.start:obj.end]


def test_delete_shared_vertex_only_in_two_5310_polygons_and_undo_redo():
    original = map_bytes()
    ws = state(original)
    before = GeoMap(original)
    result = ws.delete_vertex("f0", 1, shared=True, **auth(ws))
    assert result["changed"]
    assert result["sourceCode"] == "5310"
    assert result["removedSameCodeVertices"] == 1
    assert result["foreignCodesProtected"] is True
    assert result["affected"] == ["A", "B"]
    assert {o["code"] for o in result["affectedObjects"]} == {"5310"}
    assert result["dirty"] and result["canUndo"]
    exported = GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    assert exported.checksum_valid
    assert exported.declared_lines == len(exported.lines)
    assert len(exported.by_id["A"].points) == 5
    assert len(exported.by_id["B"].points) == 5
    assert source_records(before, "LAND") == source_records(exported, "LAND")
    assert source_records(before, "FOREST") == source_records(exported, "FOREST")
    assert b":UNKNOWN[zachowaj bez zmian]" in ws.export_copy(auth(ws)["document_token"])[1]
    undo = ws.step_history("undo", **auth(ws))
    assert undo["changed"] and not undo["dirty"]
    assert ws.export_copy(auth(ws)["document_token"])[1] == original
    redo = ws.step_history("redo", **auth(ws))
    assert redo["changed"] and redo["dirty"]
    after_redo = GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    assert source_records(after_redo, "LAND") == source_records(before, "LAND")


def test_delete_single_vertex_shared_off_does_not_touch_other_5310():
    original = map_bytes()
    ws = state(original)
    result = ws.delete_vertex("f0", 1, shared=False, **auth(ws))
    assert result["affected"] == ["A"]
    after = GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    before = GeoMap(original)
    assert len(after.by_id["A"].points) == 5
    assert source_records(before, "B") == source_records(after, "B")
    assert source_records(before, "LAND") == source_records(after, "LAND")


def test_first_vertex_deletion_updates_closing_point_and_restores_exact_bytes():
    original = map_bytes()
    ws = state(original)
    result = ws.delete_vertex("f0", 0, shared=False, **auth(ws))
    updated = GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    obj = updated.by_id["A"]
    assert obj.is_closed
    assert (obj.points[0].x, obj.points[0].y) == (5, 0)
    assert (obj.points[-1].x, obj.points[-1].y) == (5, 0)
    assert len(obj.points) == 5
    assert updated.checksum_valid
    ws.step_history("undo", **auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1] == original
    ws.step_history("redo", **auth(ws))
    assert GeoMap(ws.export_copy(auth(ws)["document_token"])[1]).by_id["A"].is_closed


def test_three_corner_polygon_must_not_lose_a_vertex():
    triangle = (MapBuilder()
        .object("5310", "TRI", {}, [(0, 0), (5, 0), (0, 5)])
        .build())
    ws = state(triangle)
    with pytest.raises(ValueError, match="trójkąt"):
        ws.delete_vertex("f0", 1, shared=False, **auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1] == triangle
    assert not ws.editing_status()["canUndo"]


def test_shared_neighbor_triangle_blocks_every_change():
    raw = (MapBuilder()
        .object("5310", "A", {},
                [(0, 0), (5, 0), (10, 0), (10, 10), (0, 10)])
        .object("5310", "TRI", {},
                [(5, 0), (10, -3), (0, -3)])
        .build())
    ws = state(raw)
    with pytest.raises(ValueError):
        ws.delete_vertex("f0", 1, shared=True, **auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1] == raw
    assert not ws.editing_status()["dirty"]


def test_same_code_t_junction_without_neighbor_p_is_refused_in_shared_mode():
    raw = (MapBuilder()
        .object("5310", "A", {},
                [(0, 0), (5, 0), (10, 0), (10, 10), (0, 10)])
        .object("5310", "B", {},
                [(0, 0), (10, 0), (10, -5), (0, -5)])
        .build())
    ws = state(raw)
    with pytest.raises(ValueError, match="wspólną"):
        ws.delete_vertex("f0", 1, shared=True, **auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1] == raw


@pytest.mark.parametrize("index,shared", [
    (-1, False), (500, False), (0.5, False), (1, "yes"),
])
def test_invalid_delete_rejected_without_writing_source(index, shared):
    raw = map_bytes()
    ws = state(raw)
    with pytest.raises(ValueError):
        ws.delete_vertex("f0", index, shared=shared, **auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1] == raw


def test_wrong_revision_or_document_blocks_delete():
    raw = map_bytes()
    ws = state(raw)
    old = auth(ws)
    ws.delete_vertex("f0", 1, shared=False, **old)
    with pytest.raises(RuntimeError):
        ws.delete_vertex("f0", 1, shared=False, **old)
    ws.load_map(raw, "new.MAP")
    with pytest.raises(RuntimeError):
        ws.delete_vertex("f0", 1, shared=False, **old)


def test_delete_http_roundtrip_and_safe_export():
    raw = map_bytes()
    app = create_app()
    with TestClient(app) as client:
        headers = {"X-GeoStudio-Token": app.state.api_token}
        metadata = client.post("/api/map", content=raw, headers={
            **headers, "X-Map-Name": "original.MAP"}).json()
        answer = client.request(
            "DELETE", "/api/object/f0/vertices/1", headers=headers,
            json={"shared": True, "documentToken": metadata["documentToken"],
                  "revision": 0},
        )
        assert answer.status_code == 200, answer.text
        assert answer.json()["removedSameCodeVertices"] == 1
        stale = client.request(
            "DELETE", "/api/object/f0/vertices/1", headers=headers,
            json={"shared": True, "documentToken": metadata["documentToken"],
                  "revision": 0},
        )
        assert stale.status_code == 409
        exported = client.get("/api/export/map", headers=headers, params={
            "documentToken": metadata["documentToken"]})
        assert exported.status_code == 200
        after = GeoMap(exported.content)
        assert after.checksum_valid
        assert source_records(after, "LAND") == source_records(GeoMap(raw), "LAND")
        undone = client.post("/api/edit/undo", headers=headers, json={
            "documentToken": metadata["documentToken"], "revision": 1})
        assert undone.status_code == 200
        assert undone.json()["dirty"] is False
        again = client.get("/api/export/map", headers=headers, params={
            "documentToken": metadata["documentToken"]})
        assert again.content == raw


def test_browser_has_delete_and_selected_vertex_controls():
    from pathlib import Path
    base = Path(__file__).resolve().parents[1] / "geostudio/web_app/static"
    html = (base / "index.html").read_text(encoding="utf-8")
    js = (base / "map.js").read_text(encoding="utf-8")
    assert 'id="tool-delete-node"' in html
    assert 'method:"DELETE"' in js
    assert 'ev.key==="Delete"' in js
    assert 'state.selectedVertex=index' in js
    assert 'updateDeleteNodeButton()' in js
