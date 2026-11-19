"""5310 next to 5310 along a side: T-junction topology regression."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.geomap import GeoMap
from geostudio.topology_edit import linked_vertex_plan
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app


def touching_map():
    return (MapBuilder(ext=(5000, -10, -10, 80, 80))
        .object("5310", "BUILDING_A", {"A1": "b"},
                [(0, 0), (10, 0), (10, 10), (0, 10)])
        .object("5310", "BUILDING_B", {"A1": "b"},
                [(10, -5), (20, -5), (20, 5), (10, 5)])
        .object("5220", "LAND_5220", {"A1": "R"},
                [(10, 0), (10, -10), (30, -10), (30, 0)])
        .object("5230", "LAND_5230", {"A1": "LsV"},
                [(0, 0), (-10, 0), (-10, 10), (0, 10)])
        .build())


def snapshot(doc, uid):
    obj = doc.by_id[uid]
    return list(doc.lines[obj.start:obj.end])


def auth(ws):
    status = ws.editing_status()
    return {"document_token": status["documentToken"],
            "revision": status["revision"]}


def test_planner_detects_same_code_side_without_a_vertex_at_the_junction():
    doc = GeoMap(touching_map())
    assert not any((p.x, p.y) == (10, 0) for p in doc.by_id["BUILDING_B"].points)
    plan = linked_vertex_plan(doc, "BUILDING_A", 1, 11, 1)
    assert plan.moves == {
        "BUILDING_A": {1: (11, 1)},
        "BUILDING_B": {4: (11, 1)},
    }
    assert plan.inserts == {"BUILDING_B": (3, (10.0, 0.0))}
    assert "LAND_5220" not in plan.moves
    assert "LAND_5230" not in plan.moves


def test_shared_mode_moves_neighboring_5310_side_and_not_5220():
    raw = touching_map()
    ws = PreviewWorkspace()
    ws.load_map(raw, "test.MAP")
    before = GeoMap(raw)
    response = ws.move_vertex("f0", 1, 11, 1, shared=True,
                              snap_radius=0, **auth(ws))
    assert response["changed"] is True
    assert response["sourceCode"] == "5310"
    assert response["affected"] == ["BUILDING_A", "BUILDING_B"]
    assert response["insertedSameCodeVertices"] == 1
    assert {entry["code"] for entry in response["affectedObjects"]} == {"5310"}
    _, output = ws.export_copy(auth(ws)["document_token"])
    after = GeoMap(output)
    assert after.checksum_valid
    assert after.declared_lines == len(after.lines)
    assert [(p.x, p.y) for p in after.by_id["BUILDING_B"].points][3:6] == [
        (10, 5), (11, 1), (10, -5)]
    assert (after.by_id["BUILDING_A"].points[1].x,
            after.by_id["BUILDING_A"].points[1].y) == (11, 1)
    assert snapshot(before, "LAND_5220") == snapshot(after, "LAND_5220")
    assert snapshot(before, "LAND_5230") == snapshot(after, "LAND_5230")
    # History must undo BOTH insertion and move, including exact bytes.
    ws.step_history("undo", **auth(ws))
    undone = ws.export_copy(auth(ws)["document_token"])[1]
    assert undone == raw
    ws.step_history("redo", **auth(ws))
    redone = GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    assert len(redone.by_id["BUILDING_B"].points) == len(before.by_id["BUILDING_B"].points) + 1
    assert snapshot(before, "LAND_5220") == snapshot(redone, "LAND_5220")


def test_shared_off_does_not_insert_neighboring_5310_vertex():
    raw = touching_map()
    ws = PreviewWorkspace()
    ws.load_map(raw, "test.MAP")
    response = ws.move_vertex("f0", 1, 11, 1, shared=False,
                              snap_radius=0, **auth(ws))
    assert response["affected"] == ["BUILDING_A"]
    assert response["insertedSameCodeVertices"] == 0
    old = GeoMap(raw)
    new = GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    assert snapshot(old, "BUILDING_B") == snapshot(new, "BUILDING_B")
    assert snapshot(old, "LAND_5220") == snapshot(new, "LAND_5220")


def test_http_shared_side_stays_in_5310_and_download_is_valid():
    raw = touching_map()
    app = create_app()
    with TestClient(app) as client:
        headers = {"X-GeoStudio-Token": app.state.api_token}
        opened = client.post("/api/map", content=raw, headers={
            **headers, "X-Map-Name": "test.MAP"}).json()
        reply = client.patch("/api/object/f0/vertex", json={
            "index": 1, "x": 11, "y": 1, "shared": True,
            "snapRadius": 0, "documentToken": opened["documentToken"],
            "revision": 0,
        }, headers=headers)
        assert reply.status_code == 200, reply.text
        assert reply.json()["insertedSameCodeVertices"] == 1
        assert reply.json()["affected"] == ["BUILDING_A", "BUILDING_B"]
        output = client.get("/api/export/map", headers=headers, params={
            "documentToken": opened["documentToken"]})
        assert output.status_code == 200
        original, exported = GeoMap(raw), GeoMap(output.content)
        assert snapshot(original, "LAND_5220") == snapshot(exported, "LAND_5220")
        assert len(exported.by_id["BUILDING_B"].points) == 6


def test_non_matching_other_code_edge_is_never_split():
    raw = (MapBuilder(ext=(5000, -10, -10, 80, 80))
        .object("5310", "A", {}, [(0, 0), (10, 0), (10, 10), (0, 10)])
        .object("5220", "FOREIGN_EDGE", {}, [
            (10, -5), (20, -5), (20, 5), (10, 5)])
        .build())
    ws = PreviewWorkspace()
    ws.load_map(raw, "foreign.MAP")
    result = ws.move_vertex("f0", 1, 11, 1, shared=True,
                            snap_radius=0, **auth(ws))
    assert result["affected"] == ["A"]
    assert result["insertedSameCodeVertices"] == 0
    before = GeoMap(raw)
    after = GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    assert snapshot(before, "FOREIGN_EDGE") == snapshot(after, "FOREIGN_EDGE")


def test_browser_disallows_selecting_foreign_code_in_active_P_mode():
    from pathlib import Path
    js = (Path(__file__).resolve().parents[1] /
          "geostudio/web_app/static/map.js").read_text(encoding="utf8")
    assert 'state.tool==="nodes"&&state.detail?.code' in js
    assert "feature.code!==state.detail?.code" in js
    assert "sameCodeNeighborPreview" in js
