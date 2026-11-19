"""Double-click a real GEO-MAP polygon edge: safe native P insertion."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.geomap import GeoMap
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app


def fixture_map() -> bytes:
    # Same segment (10,0)-(10,10) belongs to codes 5310, 5310, 5220.
    # In shared mode we MUST insert in the TWO 5310 polygons ONLY.
    return (MapBuilder(ext=(5000, 0, -15, 50, 50))
            .object("5310", "A", {"A1": "b"},
                    [(0, 0), (10, 0), (10, 10), (0, 10)])
            .object("5310", "B", {"A1": "b"},
                    [(10, 10), (20, 10), (20, 0), (10, 0)])
            .object("5220", "C", {"A1": "R"},
                    [(10, 0), (30, 0), (30, 10), (10, 10)])
            .object("5230", "D", {"A1": "LsV"},
                    [(0, 0), (0, -10), (-10, -10), (-10, 0)])
            .raw(":UNKNOWN[keep these bytes]")
            .build())


def get_ws(raw: bytes | None = None) -> PreviewWorkspace:
    ws = PreviewWorkspace()
    ws.load_map(raw or fixture_map(), "MOKRA WIEŚ.MAP")
    return ws


def auth(ws: PreviewWorkspace) -> dict:
    status = ws.editing_status()
    return {"document_token": status["documentToken"],
            "revision": status["revision"]}


def records(doc: GeoMap, uid: str) -> list[bytes]:
    entry = doc.by_id[uid]
    return doc.lines[entry.start:entry.end]


def test_doubleclick_insert_shared_5310_edges_but_never_5220():
    source = fixture_map()
    ws = get_ws(source)
    before = GeoMap(source)
    result = ws.insert_vertex(
        "f0", 1, 10, 4, shared=True, edge_radius=.01, **auth(ws))
    assert result["changed"] is True
    assert result["sourceCode"] == "5310"
    assert result["foreignCodesProtected"] is True
    assert result["insertedVertexIndex"] == 2
    assert result["insertedSameCodeVertices"] == 1
    assert set(result["affected"]) == {"A", "B"}
    assert {o["code"] for o in result["affectedObjects"]} == {"5310"}
    assert result["dirty"] and result["canUndo"]
    assert result["revision"] == 1

    name, data = ws.export_copy(auth(ws)["document_token"])
    assert name == "MOKRA WIEŚ_GeoStudio2_kopia.MAP"
    assert data != source
    after = GeoMap(data)
    assert after.checksum_valid
    assert after.declared_lines == len(after.lines)
    assert len(after.by_id["A"].points) == len(before.by_id["A"].points) + 1
    assert len(after.by_id["B"].points) == len(before.by_id["B"].points) + 1
    assert (after.by_id["A"].points[2].x,
            after.by_id["A"].points[2].y) == (10, 4)
    assert (after.by_id["B"].points[4].x,
            after.by_id["B"].points[4].y) == (10, 4)
    # The exact P records of adjacent foreign-code polygons must NOT change.
    assert records(after, "C") == records(before, "C")
    assert records(after, "D") == records(before, "D")
    assert b":UNKNOWN[keep these bytes]" in data

    undo = ws.step_history("undo", **auth(ws))
    assert undo["changed"]
    assert not undo["dirty"]
    assert ws.export_copy(auth(ws)["document_token"])[1] == source
    redo = ws.step_history("redo", **auth(ws))
    assert redo["dirty"]
    redone = GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    assert records(redone, "C") == records(before, "C")
    assert redone.by_id["A"].points[2].y == 4


def test_when_shared_disabled_only_active_polygon_gains_a_vertex():
    source = fixture_map()
    ws = get_ws(source)
    result = ws.insert_vertex(
        "f0", 1, 10, 4, shared=False, edge_radius=0, **auth(ws))
    assert result["insertedSameCodeVertices"] == 0
    assert result["affected"] == ["A"]
    original = GeoMap(source)
    updated = GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    assert len(updated.by_id["A"].points) == len(original.by_id["A"].points) + 1
    assert records(original, "B") == records(updated, "B")
    assert records(original, "C") == records(updated, "C")


def test_pixel_offset_is_projected_on_selected_edge_not_on_5220():
    ws = get_ws()
    result = ws.insert_vertex(
        "f0", 1, 9.985, 4.1231, shared=True,
        edge_radius=.03, **auth(ws))
    assert result["newVertex"] == {"x": 10.0, "y": 4.123}
    exported = GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    assert exported.by_id["A"].points[2].x == 10
    assert exported.by_id["B"].points[4].y == 4.123


@pytest.mark.parametrize("segment,x,y,shared,radius", [
    (99, 10, 4, False, 0),
    (1, 9, 4, False, .1),  # too far from the edge
    (1, 10, .001, False, 0),  # too close to source endpoint
    (1, 10, 9.999, False, 0),  # too close to another endpoint
    (1, 10, 4, "yes", 0),
    (1, 10, 4, False, float("inf")),
    (1, 10, 4, False, -1),
    (1, float("nan"), 4, False, 1),
])
def test_bad_inserts_leave_every_record_byte_identical(
        segment, x, y, shared, radius):
    source = fixture_map()
    ws = get_ws(source)
    with pytest.raises(ValueError):
        ws.insert_vertex("f0", segment, x, y, shared=shared,
                         edge_radius=radius, **auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1] == source
    assert not ws.editing_status()["canUndo"]


def test_rejected_old_revision_and_old_map():
    ws = get_ws()
    stale = auth(ws)
    ws.insert_vertex("f0", 1, 10, 4, shared=True, **stale)
    with pytest.raises(RuntimeError):
        ws.insert_vertex("f0", 1, 10, 6, shared=True, **stale)
    ws.load_map(fixture_map(), "second.MAP")
    with pytest.raises(RuntimeError):
        ws.insert_vertex("f0", 1, 10, 6, shared=False, **stale)


def test_same_code_vertex_already_present_never_creates_duplicate_neighbor():
    # Neighbor B has an existing vertex in the middle of its shared edge.
    source = (MapBuilder()
        .object("5310", "A", {}, [(0, 0), (10, 0), (10, 10), (0, 10)])
        .object("5310", "B", {}, [(10, 10), (20, 10), (20, 0),
                                  (10, 0), (10, 4)])
        .object("5220", "C", {}, [(10, 10), (30, 10), (30, 0), (10, 0)])
        .build())
    ws = get_ws(source)
    result = ws.insert_vertex("f0", 1, 10, 4, shared=True, **auth(ws))
    assert result["insertedSameCodeVertices"] == 0
    after = GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    before = GeoMap(source)
    assert len(after.by_id["A"].points) == len(before.by_id["A"].points) + 1
    assert records(after, "B") == records(before, "B")
    assert records(after, "C") == records(before, "C")


def test_web_api_add_vertex_then_undo_without_mutating_uploaded_map():
    raw = fixture_map()
    app = create_app()
    with TestClient(app) as client:
        headers = {"X-GeoStudio-Token": app.state.api_token}
        status = client.post("/api/map", content=raw, headers={
            **headers, "X-Map-Name": "original.MAP"}).json()
        resp = client.post("/api/object/f0/vertices", headers=headers, json={
            "segmentIndex": 1, "x": 10, "y": 4, "shared": True,
            "edgeRadius": .1,
            "documentToken": status["documentToken"], "revision": 0})
        assert resp.status_code == 200, resp.text
        assert resp.json()["insertedSameCodeVertices"] == 1
        assert resp.json()["affected"] == ["A", "B"]
        downloaded = client.get("/api/export/map", headers=headers,
                                params={"documentToken": status["documentToken"]})
        assert downloaded.status_code == 200
        assert GeoMap(downloaded.content).checksum_valid
        assert records(GeoMap(downloaded.content), "C") == records(GeoMap(raw), "C")
        bad = client.post("/api/object/f0/vertices", headers=headers, json={
            "segmentIndex": 1, "x": 10, "y": 5, "shared": True,
            "edgeRadius": 1,
            "documentToken": status["documentToken"], "revision": 0})
        assert bad.status_code == 409
        undo = client.post("/api/edit/undo", headers=headers, json={
            "documentToken": status["documentToken"], "revision": 1})
        assert undo.status_code == 200
        assert not undo.json()["dirty"]


def test_browser_inserts_only_on_current_polygon_edge_in_P_mode():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] /
          "geostudio/web_app/static/map.js").read_text(encoding="utf-8")
    assert 'canvas.addEventListener("dblclick"' in js
    assert "closestEditableSegment(eventCoords(ev))" in js
    assert 'state.tool!=="nodes"' in js
    assert "ev.preventDefault();ev.stopPropagation();" in js
    assert "/vertices" in js
    assert "state.tool===\"nodes\"&&closestEditableSegment(p)" in js
    assert "sourceCode!==code" in js
