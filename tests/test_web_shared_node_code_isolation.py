"""Cross-code topology regression tests for GeoStudio 2.0."""
import pytest
from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.geomap import GeoMap
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app


def crossed_map():
    return (MapBuilder(ext=(5000, 0, 0, 100, 100))
        .object("5310", "A", {"A1": "b"},
                [(0, 0), (10, 0), (10, 10), (0, 10)])
        .object("5310", "B", {"A1": "b"},
                [(10, 0), (20, 0), (20, 10), (10, 10)])
        .object("5220", "C", {"A1": "R"},
                [(10, 0), (10, -8), (18, -8), (18, 0)])
        .build())


def token(ws):
    state = ws.editing_status()
    return {"document_token": state["documentToken"], "revision": state["revision"]}


def ws_of(data):
    ws = PreviewWorkspace()
    ws.load_map(data, "test.MAP")
    return ws


def foreign_lines(doc):
    obj = doc.by_id["C"]
    return doc.lines[obj.start:obj.end]


def test_5310_linked_moves_only_5310_not_adjacent_5220():
    raw = crossed_map()
    ws = ws_of(raw)
    before = GeoMap(raw)
    result = ws.move_vertex("f0", 1, 11, 1, shared=True, **token(ws))
    assert result["sourceCode"] == "5310"
    assert result["foreignCodesProtected"] is True
    assert set(result["affected"]) == {"A", "B"}
    assert {o["code"] for o in result["affectedObjects"]} == {"5310"}
    doc = GeoMap(ws.export_copy(token(ws)["document_token"])[1])
    assert foreign_lines(doc) == foreign_lines(before)
    assert doc.by_id["A"].points[1].x == 11
    assert doc.by_id["B"].points[0].x == 11
    ws.step_history("undo", **token(ws))
    assert ws.export_copy(token(ws)["document_token"])[1] == raw


def test_shared_mode_does_not_snap_to_5220_at_all():
    raw = crossed_map()
    ws = ws_of(raw)
    before = GeoMap(raw)
    result = ws.move_vertex("f0", 0, 10.03, -7.96,
                            shared=True, snap_radius=.12, **token(ws))
    assert result["snap"] is None
    assert set(result["affected"]) == {"A"}
    exported = GeoMap(ws.export_copy(token(ws)["document_token"])[1])
    assert foreign_lines(exported) == foreign_lines(before)
    assert (exported.by_id["A"].points[0].x,
            exported.by_id["A"].points[0].y) == (10.03, -7.96)


def test_isolated_mode_can_still_snap_to_5220_without_editing_it():
    raw = crossed_map()
    ws = ws_of(raw)
    before = GeoMap(raw)
    result = ws.move_vertex("f0", 0, 10.03, -7.96,
                            shared=False, snap_radius=.12, **token(ws))
    assert result["snap"]["code"] == "5220"
    exported = GeoMap(ws.export_copy(token(ws)["document_token"])[1])
    assert foreign_lines(exported) == foreign_lines(before)
    assert (exported.by_id["A"].points[0].x,
            exported.by_id["A"].points[0].y) == (10, -8)


def test_duplicate_id_across_5310_and_5220_must_never_edit_5220():
    raw = (MapBuilder(ext=(5000, 0, 0, 100, 100))
        .object("5310", "SAME", {"A1": "b"},
                [(0, 0), (10, 0), (10, 10), (0, 10)])
        .object("5220", "SAME", {"A1": "R"},
                [(10, 0), (20, 0), (20, 10), (10, 10)])
        .build())
    ws = ws_of(raw)
    before = ws.export_copy(token(ws)["document_token"])[1]
    with pytest.raises(ValueError, match="Niejednoznaczny"):
        ws.move_vertex("f0", 1, 11, 1, shared=True, **token(ws))
    with pytest.raises(ValueError, match="Niejednoznaczny"):
        ws.edit_fields("f0", {"A1": "nowe"}, **token(ws))
    assert ws.export_copy(token(ws)["document_token"])[1] == before
    assert not ws.editing_status()["canUndo"]


def test_duplicate_neighbor_uid_must_abort_shared_move():
    raw = (MapBuilder(ext=(5000, 0, 0, 100, 100))
        .object("5310", "A", {"A1": "b"},
                [(0, 0), (10, 0), (10, 10), (0, 10)])
        .object("5310", "REUSED", {"A1": "b"},
                [(10, 0), (20, 0), (20, 10), (10, 10)])
        .object("5220", "REUSED", {"A1": "R"},
                [(10, 0), (10, -8), (18, -8), (18, 0)])
        .build())
    ws = ws_of(raw)
    before = ws.export_copy(token(ws)["document_token"])[1]
    with pytest.raises(ValueError, match="wyłącznie jednoznacznych"):
        ws.move_vertex("f0", 1, 11, 1, shared=True, **token(ws))
    assert ws.export_copy(token(ws)["document_token"])[1] == before
    assert not ws.editing_status()["dirty"]


def test_http_linked_5310_response_identifies_exact_code_and_preserves_5220():
    raw = crossed_map()
    app = create_app()
    with TestClient(app) as client:
        headers = {"X-GeoStudio-Token": app.state.api_token}
        status = client.post("/api/map", content=raw, headers={
            **headers, "X-Map-Name": "mixed.MAP"}).json()
        changed = client.patch("/api/object/f0/vertex", headers=headers, json={
            "index": 1, "x": 11, "y": 1, "shared": True, "snapRadius": 0,
            "documentToken": status["documentToken"], "revision": 0})
        assert changed.status_code == 200, changed.text
        assert {o["code"] for o in changed.json()["affectedObjects"]} == {"5310"}
        dl = client.get("/api/export/map", headers=headers,
                        params={"documentToken": status["documentToken"]})
        assert dl.status_code == 200
        assert foreign_lines(GeoMap(dl.content)) == foreign_lines(GeoMap(raw))
