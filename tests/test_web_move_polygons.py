"""Whole-polygon translation: topology, native records, preview and history."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.geomap import GeoMap
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app


def source():
    return (MapBuilder(ext=(5000, -100, -100, 100, 100))
        .raw(";# unrecognized source records must survive unchanged")
        .object("5310", "A", {"A1": "Dom"},
                [(0, 0), (0, 10), (10, 10), (10, 0)])
        .object("5310", "B", {"A1": "Garaż"},
                [(10, 0), (10, 10), (20, 10), (20, 0)])
        .object("5310", "C", {"A1": "Dom"},
                [(40, 0), (40, 10), (50, 10), (50, 0)])
        .object("5220", "LAND", {"A1": "R"},
                [(0, 0), (0, -10), (-10, -10), (-10, 0)])
        .object("5230", "ROAD", {"A1": "dr", "A2": "droga"},
                [(10, 0), (20, 0), (20, -10), (10, -10)])
        .object("6900", "LINE", {}, [(5, 40), (10, 40)], closed=False)
        .build())


@pytest.fixture
def ws():
    state = PreviewWorkspace()
    state.load_map(source(), "MOKRA WIEŚ.MAP")
    return state


def auth(ws):
    status = ws.editing_status()
    return {"document_token": status["documentToken"],
            "revision": status["revision"]}


def preview(ws, ids, dx=2.0, dy=-3.0, allow_detach=False):
    return ws.preview_move_polygons(
        ids, dx, dy, allow_detach=allow_detach, **auth(ws))


def apply(ws, ids, plan, dx=2.0, dy=-3.0, allow_detach=False):
    return ws.apply_move_polygons(
        ids, dx, dy, allow_detach=allow_detach,
        preview_key=plan["previewKey"], **auth(ws))


def objlines(doc, uid):
    obj = doc.by_id[uid]
    return list(doc.lines[obj.start:obj.end])


def test_preview_has_no_side_effects_and_reports_topology(ws):
    raw = ws.export_copy(auth(ws)["document_token"])[1]
    report = preview(ws, ["f0"])
    assert report["selected"] == 1
    assert report["codes"] == {"5310": 1}
    assert report["vertexCount"] == 5
    assert report["delta"] == {"x": 2.0, "y": -3.0}
    assert report["samples"][0]["after"] == {"x": 2.0, "y": -3.0}
    assert report["topologyBlocked"] is True
    assert report["canApply"] is False
    assert any(x["stationaryUid"] == "B" for x in report["topologyConflicts"])
    assert ws.export_copy(auth(ws)["document_token"])[1] == raw
    assert ws.editing_status()["canUndo"] is False
    with pytest.raises(ValueError, match="wspólną granicę"):
        apply(ws, ["f0"], report)


def test_move_multiple_adjacent_same_code_polygons_undo_redo(ws):
    original = source()
    ids = ["f0", "f1"]
    plan = preview(ws, ids)
    assert plan["canApply"] and not plan["topologyConflicts"]
    result = apply(ws, ids, plan)
    assert result["changed"] and result["movedObjects"] == 2
    assert result["movedVertices"] == 10
    assert result["dirty"] and result["revision"] == 1

    name, exported = ws.export_copy(auth(ws)["document_token"])
    assert name.endswith("_GeoStudio2_kopia.MAP")
    doc = GeoMap(exported)
    base = GeoMap(original)
    assert doc.checksum_valid
    assert doc.declared_lines == len(doc.lines)
    for uid in ("A", "B"):
        before, after = base.by_id[uid], doc.by_id[uid]
        assert after.fields == before.fields
        assert len(after.points) == len(before.points)
        for old, new in zip(before.points, after.points):
            assert new.x == pytest.approx(old.x + 2)
            assert new.y == pytest.approx(old.y - 3)
            assert new.point_type == old.point_type
        assert after.is_closed
    for uid in ("C", "LAND", "ROAD", "LINE"):
        assert objlines(doc, uid) == objlines(base, uid)
    assert b";# unrecognized source records must survive unchanged" in exported

    ws.step_history("undo", **auth(ws))
    assert not ws.editing_status()["dirty"]
    assert ws.export_copy(auth(ws)["document_token"])[1] == original
    ws.step_history("redo", **auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1] == exported


def test_explicit_detach_moves_only_selected_same_code_without_touching_neighbors(ws):
    plan = preview(ws, ["f0"], dx=-2, dy=-3, allow_detach=True)
    assert plan["topologyConflicts"] and plan["canApply"]
    result = apply(ws, ["f0"], plan, dx=-2, dy=-3, allow_detach=True)
    assert result["topologyDetached"] is True
    doc = GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    base = GeoMap(source())
    assert doc.by_id["A"].points[0].x == -2
    for uid in ("B", "C", "LAND", "ROAD", "LINE"):
        assert objlines(doc, uid) == objlines(base, uid)


def test_t_junction_without_matching_native_vertex_is_detected():
    raw = (MapBuilder(ext=(5000, -20, -20, 20, 20))
        .object("5310", "A", {}, [(0, 0), (5, 0), (5, 5), (0, 5)])
        .object("5310", "T", {}, [(0, -10), (0, 10), (-10, 10), (-10, -10)])
        .build())
    state = PreviewWorkspace()
    state.load_map(raw, "T.MAP")
    plan = preview(state, ["f0"], dx=1, dy=1)
    assert plan["topologyBlocked"]
    assert plan["topologyConflicts"][0]["stationaryUid"] == "T"


@pytest.mark.parametrize("ids,dx,dy,allow_detach", [
    (["f0", "f0"], 1, 2, False),
    (["missing"], 1, 2, False),
    (["f0"], float("inf"), 2, False),
    (["f0"], 100001, 0, False),
    (["f0"], 1, 2, "true"),
    ([], 1, 2, False),
])
def test_invalid_move_does_not_mutate_document(ws, ids, dx, dy, allow_detach):
    raw = ws.export_copy(auth(ws)["document_token"])[1]
    with pytest.raises((ValueError, LookupError)):
        preview(ws, ids, dx=dx, dy=dy, allow_detach=allow_detach)
    assert ws.export_copy(auth(ws)["document_token"])[1] == raw
    assert not ws.editing_status()["canUndo"]


def test_requires_server_issued_preview_and_rejects_stale_version(ws):
    ids = ["f0", "f1"]
    raw = ws.export_copy(auth(ws)["document_token"])[1]
    with pytest.raises(RuntimeError, match="Podgląd"):
        ws.apply_move_polygons(
            ids, 2, -3, allow_detach=False, preview_key="guess",
            **auth(ws))
    plan = preview(ws, ids)
    with pytest.raises(RuntimeError, match="Podgląd"):
        ws.apply_move_polygons(
            ids, 2, 3, allow_detach=False,
            preview_key=plan["previewKey"], **auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1] == raw
    stale = auth(ws)
    apply(ws, ids, plan)
    with pytest.raises(RuntimeError):
        ws.preview_move_polygons(
            ids, 1, 1, allow_detach=False, **stale)
    with pytest.raises(RuntimeError):
        ws.apply_move_polygons(
            ids, 2, -3, allow_detach=False,
            preview_key=plan["previewKey"], **stale)
    ws.load_map(raw, "new.MAP")
    with pytest.raises(RuntimeError):
        ws.preview_move_polygons(
            ids, 1, 1, allow_detach=False, **stale)


def test_zero_delta_noop_does_not_add_history(ws):
    plan = preview(ws, ["f0"], dx=0, dy=0)
    assert plan["canApply"] is False
    assert apply(ws, ["f0"], plan, dx=0, dy=0)["changed"] is False
    assert not ws.editing_status()["canUndo"]


def test_http_move_preview_apply_undo_and_auth():
    app = create_app()
    with TestClient(app) as client:
        headers = {"X-GeoStudio-Token": app.state.api_token}
        opened = client.post("/api/map", content=source(), headers={
            **headers, "X-Map-Name": "move.MAP"})
        assert opened.status_code == 200, opened.text
        params = {"ids": ["f0", "f1"], "dx": 1.5, "dy": -2,
                  "allowDetach": False,
                  "documentToken": opened.json()["documentToken"],
                  "revision": 0}
        assert client.post("/api/move/preview", json=params).status_code == 403
        plan = client.post("/api/move/preview", json=params, headers=headers)
        assert plan.status_code == 200, plan.text
        moved = client.post("/api/move/apply", headers=headers, json={
            **params, "previewKey": plan.json()["previewKey"]})
        assert moved.status_code == 200, moved.text
        assert moved.json()["movedObjects"] == 2
        stale = client.post("/api/move/apply", headers=headers, json={
            **params, "previewKey": plan.json()["previewKey"]})
        assert stale.status_code == 409
        exported = client.get("/api/export/map", headers=headers, params={
            "documentToken": params["documentToken"]})
        assert exported.status_code == 200
        assert GeoMap(exported.content).checksum_valid
        undone = client.post("/api/edit/undo", headers=headers, json={
            "documentToken": params["documentToken"], "revision": 1})
        assert undone.status_code == 200 and not undone.json()["dirty"]


def test_ui_contains_move_dialog_and_shortcuts():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "geostudio/web_app/static"
    html = (root / "index.html").read_text(encoding="utf-8")
    js = (root / "map.js").read_text(encoding="utf-8")
    for id_ in ("tool-move", "tool-move-offset", "float-move",
                "move-dialog", "move-dx", "move-dy", "move-detach",
                "move-preview", "move-apply", "move-summary"):
        assert f'id="{id_}"' in html
    assert 'id="move-apply" type="submit" class="button primary" disabled' in html
    for required in ("/api/move/preview", "/api/move/apply",
                     "function drawMoveGhost", "state.moveGhost",
                     'ev.key.toLowerCase()==="m"'):
        assert required in js


def test_moving_inside_same_code_masks_underlying_geometry(ws):
    plan=preview(ws,["f2"],dx=-35,dy=0,allow_detach=True)
    assert not plan["overlapBlocked"]
    assert plan["canApply"] and plan["reversibleCutout"]
    result=apply(ws,["f2"],plan,dx=-35,dy=0,allow_detach=True)
    assert result["changed"]
    assert ws.editing_status()["hasReversibleMasks"]


def test_magnetic_snap_reaches_shared_border_without_overlap(ws):
    plan=ws.preview_move_polygons(
        ["f2"],-19.75,0,allow_detach=False,snap_distance=.5,**auth(ws))
    assert plan["snapApplied"] is not None
    assert plan["delta"]["x"] == -20.0
    assert plan["overlapConflicts"] == []
    outcome=ws.apply_move_polygons(
        ["f2"],-19.75,0,allow_detach=False,snap_distance=.5,
        preview_key=plan["previewKey"],**auth(ws))
    assert outcome["changed"]
    assert ws.details("f2")["points"][0]["x"]==20.0
