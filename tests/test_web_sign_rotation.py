"""Every inserted sign rotates in preview, native MAP, history and export."""
from __future__ import annotations

import math
import io
import json
from functools import lru_cache
from pathlib import Path
import shutil
import subprocess

import pytest

from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.sheet_marks import KINDS, ROTATABLE, primitives


def _map() -> bytes:
    return (MapBuilder(ext=(5000, 0, 0, 150, 150))
            .object("5216", "DZ-1", {"A1": "1", "A2": "1/1"},
                    [(0, 0), (0, 10), (10, 10), (10, 0)])
            .build())


def _item(kind="clearcut", **extra):
    base = {"kind": kind, "x": 0.0, "y": 0.0, "w": 40.0, "h": 20.0, "text": ""}
    base.update(extra)
    return base


def test_rotatable_set_matches_every_sign_in_the_catalogue():
    assert ROTATABLE == set(KINDS)


def test_rotation_moves_geometry_around_the_centre():
    plain = primitives(_item())
    turned = primitives(_item(angle=90))
    assert plain[0][1] != turned[0][1]
    # Środek obrotu (x+w/2, -y-h/2) musi zostać na miejscu: sprawdzamy, że
    # odległości od środka są zachowane.
    cx, cy = 20.0, -10.0
    def dists(parts):
        return [round(math.hypot(x - cx, y - cy), 3) for _, pts, *_ in parts for y, x in pts]
    assert dists(plain) == dists(turned)


@pytest.mark.parametrize("kind", KINDS)
def test_each_sign_can_change_direction(kind):
    assert primitives(_item(kind)) != primitives(_item(kind, angle=90))


def test_workspace_accepts_angle_and_stores_it():
    ws = PreviewWorkspace()
    ws.load_map(_map(), "m.MAP")
    status = ws.editing_status()
    item = {"id": "s1", "kind": "clearcut", "x": 10.0, "y": -10.0, "w": 20.0,
            "h": 10.0, "text": "Zrąb", "angle": 45}
    ws.set_sheet_items([item], document_token=status["documentToken"],
                       revision=status["revision"])
    stored = ws.metadata()["sheetItems"]
    assert any(i["id"] == "s1" and i.get("angle") == 45 for i in stored)


@pytest.mark.parametrize("kind,angle", [
    ("title", 10), ("clearcut", 400), ("marsh", None),
    ("path", float("nan")), ("conifer", True), ("shared", "90"),
])
def test_workspace_rejects_bad_angle(kind, angle):
    ws = PreviewWorkspace()
    ws.load_map(_map(), "m.MAP")
    status = ws.editing_status()
    item = {"id": "s1", "kind": kind, "x": 10.0, "y": -10.0, "w": 20.0,
            "h": 10.0, "text": "x", "angle": angle}
    with pytest.raises(ValueError):
        ws.set_sheet_items([item], document_token=status["documentToken"],
                           revision=status["revision"])


def test_real_frontend_rotation_interactions():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for frontend rotation behavior tests")
    result = subprocess.run([node, str(Path(__file__).with_suffix(".cjs"))],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


@lru_cache(maxsize=1)
def _painted_signs():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for preview/native parity")
    result = subprocess.run([node, str(Path(__file__).with_suffix(".cjs")), "geometry"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("kind", KINDS)
def test_canvas_preview_has_exact_native_clockwise_geometry(kind):
    for example in _painted_signs():
        item = example["item"]
        if item["kind"] != kind:
            continue
        native = primitives(item)
        assert len(native) == len(example["paths"])
        for part, pixels in zip(native, example["paths"]):
            if len(pixels) > 2 and pixels[0] == pixels[-1]:
                pixels = pixels[:-1]
            expected = [(east, -north) for north, east in part[1]]
            assert len(pixels) == len(expected)
            for painted, point in zip(pixels, expected):
                assert painted == pytest.approx(point, abs=1e-9)


def _save(ws, items):
    status = ws.editing_status()
    return ws.set_sheet_items(items, document_token=status["documentToken"],
                              revision=status["revision"])


def _coordinates(ws, ids):
    return [[(p.x, p.y) for p in ws._doc.by_id[uid].points] for uid in ids]


@pytest.mark.parametrize("kind", KINDS)
def test_angle_only_change_updates_native_map_keeps_ids_and_roundtrips_history(kind):
    ws = PreviewWorkspace()
    ws.load_map(_map(), "m.MAP")
    item = dict(_item(kind), id="sign", x=25, y=-30)
    _save(ws, [item])
    ids = ws.editing_status()["sheetGroups"]["sign"]
    before = _coordinates(ws, ids)
    base_map = _coordinates(ws, ["DZ-1"])
    turned = {**item, "angle": 67}
    result = _save(ws, [turned])
    assert result["sheetItems"] == [turned], "Angle-only change must remain editable"
    assert result["sheetGroups"]["sign"] == ids
    visible = ws.viewport((-100, -100, 150, 150))["features"]
    assert {f["sourceUid"] for f in visible} >= set(ids)
    after = _coordinates(ws, ids)
    assert after != before
    assert _coordinates(ws, ["DZ-1"]) == base_map
    for field in ("x", "y", "w", "h"):
        assert result["sheetItems"][0][field] == item[field]
    # The plain MAP itself contains the rotated points. Sidecar only preserves
    # the grouped sign controls, not an image transform needed by the geometry.
    raw = ws.export_copy(result["documentToken"])[1]
    reopened = PreviewWorkspace()
    reopened.load_map(raw, "saved.MAP")
    assert _coordinates(reopened, ids) == after
    reopened.set_visual_sidecar(ws.export_visual_sidecar(raw))
    assert reopened.editing_status()["sheetItems"] == [turned]
    undo = ws.step_history("undo", document_token=result["documentToken"], revision=result["revision"])
    assert _coordinates(ws, ids) == before
    assert undo["sheetItems"] == [item]
    redo = ws.step_history("redo", document_token=undo["documentToken"], revision=undo["revision"])
    assert _coordinates(ws, ids) == after
    assert redo["sheetItems"] == [turned]


@pytest.mark.parametrize("actual_angle,metadata_angle,expected", [(-43, 43, -43), (0, 43, 0)])
def test_legacy_sign_rotation_is_recovered_from_exact_native_geometry(actual_angle, metadata_angle, expected):
    ws = PreviewWorkspace()
    ws.load_map(_map(), "old.MAP")
    item = dict(_item("clearcut", angle=actual_angle), id="old-sign")
    _save(ws, [item])
    ids = ws.editing_status()["sheetGroups"]["old-sign"]
    native = _coordinates(ws, ids)
    ws._styles["cartography:sheet"]["items"] = [{**item, "angle": metadata_angle}]
    assert ws.editing_status()["sheetItems"][0]["angle"] == expected
    raw = ws._doc.to_bytes()
    reopened = PreviewWorkspace()
    reopened.load_map(raw, "old.MAP")
    reopened.set_visual_sidecar(ws.export_visual_sidecar(raw))
    assert reopened.editing_status()["sheetItems"][0]["angle"] == expected
    assert _coordinates(reopened, ids) == native, "Compatibility must not move existing geometry"
    repaired = {**item, "angle": 77}
    result = _save(reopened, [repaired])
    assert result["sheetGroups"]["old-sign"] == ids
    assert result["sheetItems"] == [repaired]


def test_legacy_recovery_never_claims_a_manually_modified_sign():
    ws = PreviewWorkspace()
    ws.load_map(_map(), "old.MAP")
    item = dict(_item("conifer", angle=0), id="edited")
    _save(ws, [item])
    ids = ws.editing_status()["sheetGroups"]["edited"]
    points = _coordinates(ws, ids)[0]
    points[0] = (points[0][0] + 1, points[0][1])
    ws._doc.replace_simple_geometry(ids[0], points, closed=False)
    ws._styles["cartography:sheet"]["items"] = [{**item, "angle": 43}]
    before = ws._doc.to_bytes()
    assert ws.editing_status()["sheetItems"] == []
    assert ws._doc.to_bytes() == before


def test_vector_dxf_exports_rotated_native_points():
    import ezdxf
    ws = PreviewWorkspace()
    ws.load_map(_map(), "sign.MAP")
    item = dict(_item("conifer"), id="tree")
    _save(ws, [item])
    result = _save(ws, [{**item, "angle": 90}])
    ids = result["sheetGroups"]["tree"]
    native = _coordinates(ws, ids)[0]
    _, payload = ws.export_dxf(result["documentToken"])
    cad = ezdxf.read(io.StringIO(payload.decode("utf-8")))
    lines = list(cad.modelspace().query('LWPOLYLINE[layer=="G1431"]'))
    assert len(lines) == 1
    actual = [(x, y) for x, y, *_ in lines[0].get_points()]
    assert actual == native  # DXF intentionally preserves native GEO-MAP X/Y.


def test_wms_layer_button_reports_state_with_colours():
    from pathlib import Path
    js = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
    css = Path("geostudio/web_app/static/styles.css").read_text(encoding="utf-8")
    assert "function wmsLayersState(" in js
    assert 'wmsLayersState("ok"' in js and 'wmsLayersState("error"' in js
    assert "#underlay-layers.is-ok" in css and "#underlay-layers.is-error" in css
