"""GeoStudio 2.0 node editing — original MAP safety, topology, snapping, history."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.geomap import GeoMap
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app


def source():
    return (MapBuilder(ext=(5000, 0, 0, 100, 100))
            .raw(";# KEEP GEO-MAP unknown records verbatim")
            .object("5310", "A", {"A1": "b"}, [(0, 0), (10, 0), (10, 10), (0, 10)])
            .object("5310", "B", {"A1": "b"}, [(10, 0), (20, 0), (20, 10), (10, 10)])
            .object("5230", "C", {"A1": "LsV"}, [(10, 0), (10, -8), (18, -8), (18, 0)])
            .object("1246", "MARKER", {}, [(0.82, 1.09)], closed=False)
            .object("6900", "LINE", {}, [(2, 2), (8, 2)], closed=False)
            .build())


@pytest.fixture
def ws():
    state = PreviewWorkspace()
    state.load_map(source(), "Bezpieczna.MAP")
    return state


def auth(ws):
    status=ws.editing_status()
    return {"document_token": status["documentToken"],
            "revision": status["revision"]}


def test_isolated_vertex_move_and_single_step_undo_redo(ws):
    original=source()
    result=ws.move_vertex("f0", 1, 11, 1, shared=False, **auth(ws))
    assert result["changed"] and result["affected"] == ["A"]
    assert result["dirty"] and result["revision"] == 1
    _, data=ws.export_copy(result["documentToken"])
    doc=GeoMap(data)
    assert doc.checksum_valid
    assert doc.declared_lines == len(doc.lines)
    assert (doc.by_id["A"].points[1].x,doc.by_id["A"].points[1].y) == (11, 1)
    assert (doc.by_id["B"].points[0].x,doc.by_id["B"].points[0].y) == (10, 0)
    assert doc.by_id["C"].points[0].x == 10
    assert b";# KEEP GEO-MAP unknown records verbatim" in data
    assert source() == original
    ws.step_history("undo", **auth(ws))
    assert not ws.editing_status()["dirty"]
    assert ws.details("f0")["points"][1]["x"] == 10
    ws.step_history("redo", **auth(ws))
    assert ws.details("f0")["points"][1]["x"] == 11


def test_linked_mode_moves_ONLY_same_code_corner(ws):
    result=ws.move_vertex("f0", 1, 11, 1, shared=True, **auth(ws))
    assert set(result["affected"]) == {"A", "B"}
    _, exported=ws.export_copy(result["documentToken"])
    doc=GeoMap(exported)
    assert (doc.by_id["A"].points[1].x,doc.by_id["A"].points[1].y) == (11, 1)
    assert (doc.by_id["B"].points[0].x,doc.by_id["B"].points[0].y) == (11, 1)
    assert (doc.by_id["C"].points[0].x,doc.by_id["C"].points[0].y) == (10, 0)
    assert doc.by_id["A"].points[-1].x == doc.by_id["A"].points[0].x
    ws.step_history("undo", **auth(ws))
    assert ws.details("f0")["points"][1]["x"] == 10
    assert ws.details("f1")["points"][0]["x"] == 10


def test_first_vertex_move_also_closes_ring(ws):
    ws.move_vertex("f0", 0, 1, 1, shared=False, **auth(ws))
    doc=GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    assert (doc.by_id["A"].points[0].x,doc.by_id["A"].points[0].y) == (1, 1)
    assert (doc.by_id["A"].points[-1].x,doc.by_id["A"].points[-1].y) == (1, 1)


def test_snap_to_any_marker_including_hidden_map_layer(ws):
    # A survey marker (1246) is normally hidden by browser default.
    # Snapping is based on every native map object, not just drawn features.
    result=ws.move_vertex("f0", 0, 0.79, 1.08, shared=False,
                          snap_radius=.12, **auth(ws))
    assert result["snap"]["kind"] == "vertex"
    assert result["snap"]["code"] == "1246"
    assert ws.details("f0")["points"][0]["x"] == .82
    assert ws.details("f0")["points"][0]["y"] == 1.09


def test_snap_to_any_line_edge(ws):
    result=ws.move_vertex("f0", 0, 4.25, 2.14, shared=False,
                          snap_radius=.25, **auth(ws))
    assert result["snap"]["kind"] == "edge"
    assert result["snap"]["code"] == "6900"
    assert ws.details("f0")["points"][0]["x"] == 4.25
    assert ws.details("f0")["points"][0]["y"] == 2


@pytest.mark.parametrize("index,x,y,shared,snap_radius", [
    (999, 1, 2, False, 0),
    (1, 0, 0, False, 0),  # duplicate corner
    (1, float("nan"), 2, False, 0),
    (1, 2, float("inf"), False, 0),
    (1, 12, 1, "true", 0),
    (1, 12, 1, True, -1),
    (1, 12, 1, True, 1000),
])
def test_invalid_move_is_atomic(ws, index, x, y, shared, snap_radius):
    before=ws.export_copy(auth(ws)["document_token"])[1]
    with pytest.raises(ValueError):
        ws.move_vertex("f0", index, x, y, shared=shared,
                       snap_radius=snap_radius, **auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1] == before
    assert not ws.editing_status()["canUndo"]


def test_conflicting_revision_and_old_document_are_rejected(ws):
    stale=auth(ws)
    ws.move_vertex("f0", 1, 11, 1, shared=False, **stale)
    with pytest.raises(RuntimeError):
        ws.move_vertex("f0", 2, 9, 9, shared=False, **stale)
    ws.load_map(source(), "Nowy.MAP")
    with pytest.raises(RuntimeError):
        ws.move_vertex("f0", 1, 11, 1, shared=False, **stale)


def test_real_http_node_edit_and_undo():
    app=create_app()
    with TestClient(app) as client:
        headers={"X-GeoStudio-Token":app.state.api_token}
        opened=client.post("/api/map",content=source(),headers={
            **headers,"X-Map-Name":"test.MAP"}).json()
        changed=client.patch("/api/object/f0/vertex",json={
            "index":1, "x":11, "y":1, "shared":True, "snapRadius":0,
            "documentToken":opened["documentToken"], "revision":0,
        },headers=headers)
        assert changed.status_code==200,changed.text
        assert set(changed.json()["affected"])=={"A","B"}
        stale=client.patch("/api/object/f0/vertex",json={
            "index":1,"x":12,"y":1,"shared":False,"revision":0,
            "documentToken":opened["documentToken"]
        },headers=headers)
        assert stale.status_code==409
        downloaded=client.get("/api/export/map",params={
            "documentToken":opened["documentToken"]
        },headers=headers)
        doc=GeoMap(downloaded.content)
        assert doc.checksum_valid
        assert doc.by_id["B"].points[0].x == 11
        assert doc.by_id["C"].points[0].x == 10
        undo=client.post("/api/edit/undo",json={
            "documentToken":opened["documentToken"],"revision":1,
        },headers=headers)
        assert undo.status_code==200
        assert undo.json()["dirty"] is False


def test_p_shortcut_and_e_are_handled_with_default_prevented():
    from pathlib import Path
    js=(Path(__file__).resolve().parents[1]/
        "geostudio/web_app/static/map.js").read_text(encoding="utf-8")
    html=(Path(__file__).resolve().parents[1]/
          "geostudio/web_app/static/index.html").read_text(encoding="utf-8")
    for id in ["tool-nodes","opt-snap","opt-shared","float-nodes"]:
        assert f'id="{id}"' in html
    assert 'ev.preventDefault();' in js
    assert 'toggleInspectorEdit(true)' in js
    assert 'setTool("nodes")' in js
    assert '/vertex' in js
