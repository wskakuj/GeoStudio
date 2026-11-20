"""Stage 11: safe movement of all geometries, paginated views and DXF."""
from __future__ import annotations

from io import StringIO

import ezdxf
import pytest
from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.geomap import GeoMap
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app


def fixture_map() -> bytes:
    return (MapBuilder(ext=(5000, -100, -100, 100, 100))
        .object("5310", "B1", {"A1": "b", "A2": "Budynek"},
                [(0, 0), (0, 5), (5, 5), (5, 0)])
        .object("6900", "LINE", {"TX": "Linia"},
                [(20, 10), (21, 12), (25, 15)], closed=False,
                labels=["P1", "P2", "P3"])
        .object("1246", "POINT", {"A1": "Punkt"},
                [(40, 20)], closed=False)
        .object("5220", "UNCHANGED", {"A1": "R"},
                [(70, 20), (70, 25), (75, 25), (75, 20)])
        .build())


def current(state: PreviewWorkspace) -> dict:
    report = state.editing_status()
    return {"document_token": report["documentToken"],
            "revision": report["revision"]}


def test_mixed_polygon_line_point_move_undo_is_atomic():
    source = fixture_map()
    state = PreviewWorkspace()
    state.load_map(source, "mapa.MAP")
    ids = ["f0", "f1", "f2"]
    params = {"ids": ids, "dx": 3.0, "dy": -7.0,
              "allow_detach": True, **current(state)}
    plan = state.preview_move_polygons(**params)
    assert plan["canApply"] and plan["selected"] == 3
    assert plan["vertexCount"] == 9
    assert state.export_copy(current(state)["document_token"])[1] == source
    moved = state.apply_move_polygons(
        **params, preview_key=plan["previewKey"])
    assert moved["movedObjects"] == 3

    exported = state.export_copy(current(state)["document_token"])[1]
    assert GeoMap(exported).checksum_valid
    original_map, edited_map = GeoMap(source), GeoMap(exported)
    for uid in ("B1", "LINE", "POINT"):
        old, new = original_map.by_id[uid], edited_map.by_id[uid]
        assert len(old.points) == len(new.points)
        for before, after in zip(old.points, new.points):
            assert after.x == pytest.approx(before.x + 3)
            assert after.y == pytest.approx(before.y - 7)
            assert after.point_type == before.point_type
    old_stationary = original_map.by_id["UNCHANGED"]
    new_stationary = edited_map.by_id["UNCHANGED"]
    assert original_map.lines[old_stationary.start:old_stationary.end] == (
        edited_map.lines[new_stationary.start:new_stationary.end])
    assert b",P2" in exported

    state.step_history("undo", **current(state))
    assert state.export_copy(current(state)["document_token"])[1] == source
    state.step_history("redo", **current(state))
    assert state.export_copy(current(state)["document_token"])[1] == exported


def test_multipart_point_type_zero_remains_unmodified():
    original = MapBuilder().multipart("5310", "COMPOUND").build()
    state = PreviewWorkspace()
    state.load_map(original, "multi.MAP")
    params = {"ids": ["f0"], "dx": 1.0, "dy": 2.0,
              "allow_detach": True, **current(state)}
    plan = state.preview_move_polygons(**params)
    assert plan["canApply"]
    state.apply_move_polygons(**params, preview_key=plan["previewKey"])
    edited = GeoMap(state.export_copy(current(state)["document_token"])[1])
    old = GeoMap(original).by_id["COMPOUND"]
    new = edited.by_id["COMPOUND"]
    assert [p.point_type for p in old.points] == [p.point_type for p in new.points]
    assert [p.x for p in new.points] == pytest.approx(
        [p.x + 1 for p in old.points])


def test_pagination_returns_every_object_exactly_once():
    state = PreviewWorkspace()
    state.load_map(fixture_map(), "pagina.MAP")
    extent = tuple(state.metadata()["bounds"])
    batches = [state.viewport(extent, limit=2, offset=offset)
               for offset in (0, 2, 4)]
    ids = [item["id"] for batch in batches for item in batch["features"]]
    assert ids == ["f0", "f1", "f2", "f3"]
    assert batches[0]["limited"] is True
    assert batches[1]["limited"] is False
    assert batches[2]["features"] == []
    with pytest.raises(ValueError):
        state.viewport(extent, limit=2, offset=-1)


def test_dxf_all_geometries_and_separate_a1_a2():
    state = PreviewWorkspace()
    state.load_map(fixture_map(), "mapa.MAP")
    name, payload = state.export_dxf(current(state)["document_token"])
    assert name.endswith(".dxf")
    cad = ezdxf.read(StringIO(payload.decode("utf-8")))
    model = cad.modelspace()
    polylines = list(model.query("LWPOLYLINE"))
    points = list(model.query("POINT"))
    captions = list(model.query("TEXT"))
    assert len(polylines) >= 3
    assert len(points) == 1
    assert any(item.dxf.text == "b" for item in captions)
    assert any(item.dxf.text == "Budynek" for item in captions)
    assert any(item.dxf.layer == "G6900" for item in polylines)
    assert any(item.dxf.layer == "G1246" for item in points)


def test_dxf_http_auth_and_web_controls():
    app = create_app()
    with TestClient(app) as client:
        headers = {"X-GeoStudio-Token": app.state.api_token}
        opened = client.post("/api/map", headers={
            **headers, "X-Map-Name": "test.MAP"}, content=fixture_map())
        assert opened.status_code == 200
        params = {"documentToken": opened.json()["documentToken"]}
        assert client.get("/api/export/dxf", params=params).status_code == 403
        good = client.get("/api/export/dxf", params=params, headers=headers)
        assert good.status_code == 200, good.text[:160]
        assert b"SECTION" in good.content
        bad = client.get("/api/export/dxf", params={
            "documentToken": "stale"}, headers=headers)
        assert bad.status_code == 409

    with TestClient(app) as client:
        headers_for_file = {
            **headers,
            "X-Export-Name": "GeoStudio_plansza.png",
            "X-Export-Format": "png",
            "X-Document-Token": params["documentToken"],
            "X-Document-Revision": "0",
        }
        assert client.post("/api/export/buffer", headers={
            k:v for k,v in headers_for_file.items()
            if k!="X-GeoStudio-Token"}, content=b"IMG").status_code == 403
        buffered = client.post("/api/export/buffer", headers=headers_for_file,
                               content=b"IMG")
        assert buffered.status_code == 200, buffered.text
        ticket = buffered.json()["ticket"]
        assert app.state.workspace.generated_export(ticket) == (
            "GeoStudio_plansza.png","png",b"IMG")
        assert app.state.workspace.generated_export(ticket,consume=True)[2] == b"IMG"
        with pytest.raises(LookupError):
            app.state.workspace.generated_export(ticket)
        reject = client.post("/api/export/buffer", headers={
            **headers_for_file, "X-Export-Name": "../bad.png"}, content=b"IMG")
        assert reject.status_code == 400

    from pathlib import Path
    assets = Path(__file__).resolve().parents[1] / "geostudio/web_app/static"
    html = (assets / "index.html").read_text(encoding="utf-8")
    js = (assets / "map.js").read_text(encoding="utf-8")
    for name in ("btn-layout", "tool-clear-selection", "layout-dialog",
                 "layout-scale", "layout-dpi", "layout-legend",
                 "layout-north", "layout-scalebar", "layout-export"):
        assert 'id="' + name + '"' in html
    for phrase in ("renderLayoutCanvas(", "makeRGBTiff(", "/api/export/dxf",
                   "geometrySnapshotValid", "renderLabels(visible)"):
        assert phrase in js
