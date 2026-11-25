"""Synthetic whole-map trace proposals and their one-step atomic MAP save."""
from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Polygon

from conftest import MapBuilder
from geostudio.geomap import GeoMap
from geostudio.web_app.data import PreviewWorkspace, TOPOLOGY_STACK_KEY
from geostudio.web_app.geometry_6a import geometry_of
from geostudio.web_app.server import create_app


LEFT = [(0, 0), (100, 0), (100, 100), (0, 100)]


def rectangle(x, y, w=30, h=30):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def workspace_with(*polygons):
    builder = MapBuilder()
    for i, (code, ring) in enumerate(polygons or [("5310", LEFT)]):
        builder.object(code, f"SOURCE-{i}", {"A1": str(i + 1)}, ring)
    source = builder.build()
    workspace = PreviewWorkspace()
    workspace.load_map(source, "synthetic.MAP")
    return workspace, source


def context(workspace):
    status = workspace.editing_status()
    return {"document_token": status["documentToken"], "revision": status["revision"]}


def proposal(identity, points=None, a1="10", **extra):
    return {"id": identity, "points": points if points is not None else rectangle(102, 10),
            "a1": a1, **extra}


def fit(workspace, items, distance=3):
    return workspace.fit_trace_batch(items, snap_distance=distance, **context(workspace))


def ready_items(report):
    return [{key: item[key] for key in ("id", "points", "a1")}
            for item in report["items"] if item["status"] == "ready"]


def preview(workspace, items):
    return workspace.preview_trace_batch(items, **context(workspace))


def apply(workspace, report):
    return workspace.apply_trace_batch(preview_key=report["previewKey"], **context(workspace))


def test_fit_is_read_only_with_individual_missing_a1_and_geometry_errors():
    workspace, source = workspace_with()
    result = fit(workspace, [proposal("good"), proposal("missing", rectangle(150, 10), ""),
                             proposal("bad", [[200, 10], [200, 10], [200, 10]])])
    assert [item["status"] for item in result["items"]] == ["ready", "needsA1", "rejected"]
    assert result["stats"] == dict(total=3, ready=1, needsA1=1, rejected=1, clipped=0, snapped=1)
    assert Polygon(result["items"][0]["points"]).intersection(Polygon(LEFT)).length == 30
    assert result["items"][2]["reason"]
    assert workspace.export_copy(result["documentToken"])[1] == source
    assert result["revision"] == 0 and not result["canUndo"]
    assert workspace._objects_preview_key == "" and workspace._trace_batch_preview is None


def test_existing_5310_is_clipped_but_occupied_seed_cannot_teleport():
    workspace, _ = workspace_with()
    result = fit(workspace, [
        proposal("clipped", rectangle(95, 10, 40, 25), seedPoints=[[120, 20]]),
        proposal("occupied", rectangle(95, 50, 40, 25), seedPoints=[[97, 60]]),
        proposal("covered", rectangle(10, 10)),
    ])
    first, occupied, covered = result["items"]
    assert first["status"] == "ready" and first["clipped"]
    assert Polygon(first["points"]).intersection(Polygon(LEFT)).area == 0
    assert occupied["status"] == covered["status"] == "rejected"
    assert "zajmuje" in occupied["reason"] and "zajmuje" in covered["reason"]


def test_near_edge_seed_uses_requested_tolerance_in_the_unfitted_first_pass():
    workspace, _ = workspace_with(("5216", [(0, 0), (200, 0), (200, 200), (0, 200)]))
    result = fit(workspace, [proposal("edge", rectangle(20, 20), seedPoints=[[19, 30]])])
    assert result["items"][0]["status"] == "ready"
    assert preview(workspace, ready_items(result))["canApply"], "5216 is reference land, never occupied 5310"


def test_shared_border_and_its_extension_stay_identical_when_outer_sides_fit_5310():
    workspace, _ = workspace_with()
    result = fit(workspace, [proposal("top", rectangle(102, 0, 98, 50)),
                             proposal("bottom", rectangle(102, 50, 98, 50), "11")])
    top, bottom = result["items"]
    assert top["status"] == bottom["status"] == "ready"
    assert top["snapped"] and bottom["snapped"]
    a, b = Polygon(top["points"]), Polygon(bottom["points"])
    assert a.intersection(b).equals(LineString([(100, 50), (200, 50)]))
    assert a.intersection(Polygon(LEFT)).equals(LineString([(100, 0), (100, 50)]))
    assert b.intersection(Polygon(LEFT)).equals(LineString([(100, 50), (100, 100)]))
    assert preview(workspace, ready_items(result))["canApply"]


def test_internal_shared_edge_close_to_existing_5310_does_not_snap_independently():
    workspace, _ = workspace_with()
    result = fit(workspace, [proposal("thin", rectangle(100.5, 10, 1.5, 80)),
                             proposal("wide", rectangle(102, 10, 98, 80), "11")])
    a, b = [Polygon(item["points"]) for item in result["items"]]
    assert a.intersection(b).equals(LineString([(102, 10), (102, 90)]))
    assert a.intersection(Polygon(LEFT)).equals(LineString([(100, 10), (100, 90)]))
    assert b.distance(Polygon(LEFT)) == 2
    assert all(item["status"] == "ready" for item in result["items"])


def test_partial_shared_edge_is_noded_on_both_sides_without_moving_t_junction():
    workspace, _ = workspace_with()
    result = fit(workspace, [proposal("long", rectangle(102, 0, 98, 100)),
                             proposal("short", rectangle(200, 20, 100, 60), "11")])
    long, short = result["items"]
    assert [200, 20] in long["points"] and [200, 80] in long["points"]
    assert Polygon(long["points"]).intersection(Polygon(short["points"])).equals(
        LineString([(200, 20), (200, 80)]))
    assert long["snapped"] and not short["snapped"]


@pytest.mark.parametrize("offset", [(0, 0), (5850000, 7520000)])
@pytest.mark.parametrize("reverse", [False, True])
def test_diagonal_t_junction_is_noded_before_map_rounding_and_saved_identically(offset, reverse):
    north, east = offset
    move = lambda points: [[north + x, east + y] for x, y in points]
    workspace, source = workspace_with(("5216", move(rectangle(100, 100))))
    items = [proposal("long", move([[0, 0], [3, 1], [0, 5]])),
             proposal("short", move([[1, 1 / 3], [1, -2], [2, -2], [2, 2 / 3]]), "11")]
    if reverse:
        items.reverse()
    result = fit(workspace, items, distance=0)
    assert all(item["status"] == "ready" for item in result["items"])
    junctions = [[round(north + 1, 3), round(east + 1 / 3, 3)],
                 [round(north + 2, 3), round(east + 2 / 3, 3)]]
    for item in result["items"]:
        assert all(point in item["points"] for point in junctions)
    a, b = [Polygon(item["points"]) for item in result["items"]]
    assert a.intersection(b).equals(LineString(junctions))
    report = preview(workspace, ready_items(result))
    assert report["canApply"]
    saved = apply(workspace, report)
    a, b = [geometry_of(workspace._doc.by_id[uid]) for uid in saved["createdUids"]]
    assert a.intersection(b).equals(LineString(junctions))
    assert b"".join(workspace._doc.lines).startswith(source)


def test_pre_round_noding_does_not_hide_a_real_millimetre_diagonal_overlap():
    workspace, _ = workspace_with(("5216", rectangle(100, 100)))
    items = [proposal("long", [[0, 0], [3, 1], [0, 5]]),
             proposal("short", [[1, 1 / 3 + .001], [1, -2], [2, -2], [2, 2 / 3 + .001]], "11")]
    assert all(item["status"] == "rejected" for item in fit(workspace, items, distance=0)["items"])
    report = preview(workspace, items)
    assert not report["canApply"] and report["items"][0]["conflicts"] == ["short"]


def test_collinear_shared_subdivision_and_explicit_manual_corner_survive():
    workspace, _ = workspace_with()
    top = [[102, 0], [205, -3], [200, 50], [170, 50], [102, 50]]
    result = fit(workspace, [proposal("top", top, lockedPoints=[[205, -3]]),
                             proposal("bottom", rectangle(102, 50, 98, 50), "11")])
    a, b = result["items"]
    assert [205, -3] in a["points"]
    assert [170, 50] in a["points"] and [170, 50] in b["points"]
    assert Polygon(a["points"]).intersection(Polygon(b["points"])).equals(
        LineString([(100, 50), (200, 50)]))


def test_all_overlapping_candidates_are_reported_without_order_based_winner():
    workspace, _ = workspace_with()
    items = [proposal("a", rectangle(150, 10)), proposal("b", rectangle(160, 10), "11"),
             proposal("safe", rectangle(210, 10), "12")]
    result = fit(workspace, items)
    a, b, safe = result["items"]
    assert a["status"] == b["status"] == "rejected"
    assert a["conflicts"] == ["b"] and b["conflicts"] == ["a"]
    assert safe["status"] == "ready"
    reversed_result = fit(workspace, list(reversed(items)))
    assert {item["id"]: item["status"] for item in reversed_result["items"]} == {
        item["id"]: item["status"] for item in result["items"]}


def test_uncertain_local_fits_that_create_overlap_fall_back_to_original_disjoint_mesh():
    workspace, _ = workspace_with(("5216", LEFT))
    original = workspace.fit_trace_outline

    def local_fit(points, **kwargs):
        result = original(points, **kwargs)
        # Simulate two individually valid local fits competing for the same
        # narrow gap. The collection guard must not choose the first one.
        if kwargs.get("fit_boundaries", True):
            result = dict(result, points=rectangle(150, 10, 50, 30), snapped=True)
        return result

    workspace.fit_trace_outline = local_fit
    result = fit(workspace, [proposal("a", rectangle(150, 10, 20, 30)),
                             proposal("b", rectangle(180, 10, 20, 30), "11")])
    assert all(item["status"] == "ready" and not item["snapped"] for item in result["items"])
    assert Polygon(result["items"][0]["points"]).distance(Polygon(result["items"][1]["points"])) == 10
    assert all("bez przesuwania" in item["reason"] for item in result["items"])


def test_final_preview_does_not_silently_clip_or_accept_missing_a1():
    workspace, source = workspace_with()
    report = preview(workspace, [proposal("overlap", rectangle(95, 10)),
                                 proposal("missing", rectangle(150, 10), "  ")])
    assert not report["canApply"] and report["previewKey"] == ""
    assert [item["status"] for item in report["items"]] == ["rejected", "needsA1"]
    assert not report["items"][0]["clipped"]
    with pytest.raises(RuntimeError, match="świeży podgląd"):
        apply(workspace, report)
    assert workspace.export_copy(report["documentToken"])[1] == source


def test_final_preview_rechecks_overlap_between_selected_edited_rings():
    workspace, _ = workspace_with()
    report = preview(workspace, [proposal("a", rectangle(150, 10)),
                                 proposal("b", rectangle(160, 10), "11")])
    assert not report["canApply"]
    assert all(item["status"] == "rejected" for item in report["items"])
    assert report["items"][0]["conflicts"] == ["b"]


def test_new_neighbours_cannot_keep_two_displaced_borders_one_millimetre_apart():
    workspace, _ = workspace_with()
    items = [proposal("a", rectangle(150, 10, 30, 30)),
             proposal("b", rectangle(179.999, 10, 30, 30), "11")]
    assert all(item["status"] == "rejected" for item in fit(workspace, items)["items"])
    report = preview(workspace, items)
    assert not report["canApply"] and report["items"][0]["conflicts"] == ["b"]


def test_atomic_apply_keeps_sources_and_native_labels_with_one_undo_and_redo():
    workspace, source = workspace_with()
    fitted = fit(workspace, [proposal("a", rectangle(102, 0, 98, 50), "1"),
                             proposal("b", rectangle(102, 50, 98, 50), "1")])
    saved = apply(workspace, preview(workspace, ready_items(fitted)))
    assert saved["createdCount"] == 2 and saved["proposalIds"] == ["a", "b"]
    assert saved["revision"] == 1 and saved["canUndo"] and saved["mergedSameA1"] == 0
    assert b"".join(workspace._doc.lines).startswith(source)
    assert len(workspace._doc.objects) == 3, "Matching A1 must not merge original or new components"
    for uid, item in zip(saved["createdUids"], fitted["items"]):
        obj = workspace._doc.by_id[uid]
        assert geometry_of(obj).equals(Polygon(item["points"]))
        raw = b"".join(workspace._doc.lines[obj.start:obj.end])
        assert b":A1[1]" in raw and all(f"L {i} ".encode() in raw for i in (1, 2, 3))
    assert workspace._styles[TOPOLOGY_STACK_KEY]["uids"] == saved["createdUids"]
    export_after = workspace.export_copy(saved["documentToken"])[1]
    undone = workspace.step_history("undo", **context(workspace))
    assert undone["revision"] == 2 and not undone["canUndo"] and undone["canRedo"]
    assert workspace.export_copy(undone["documentToken"])[1] == source
    assert not workspace._overlay_uids()
    workspace.step_history("redo", **context(workspace))
    assert workspace.export_copy(undone["documentToken"])[1] == export_after


def test_failure_during_final_reindex_rolls_back_the_entire_batch_and_styles(monkeypatch):
    workspace, source = workspace_with()
    report = preview(workspace, [proposal("a"), proposal("b", rectangle(150, 10), "11")])
    before = deepcopy(workspace._styles)
    reindex = workspace._reindex
    calls = 0

    def fail_once(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("synthetic reindex failure")
        return reindex(*args)

    monkeypatch.setattr(workspace, "_reindex", fail_once)
    with pytest.raises(ValueError, match="synthetic"):
        apply(workspace, report)
    assert workspace.export_copy(report["documentToken"])[1] == source
    assert workspace._styles == before
    assert workspace.editing_status()["revision"] == 0
    assert not workspace.editing_status()["canUndo"]
    assert len(workspace._doc.objects) == 1


def test_encoding_failure_never_mutates_map_or_records_partial_history(monkeypatch):
    workspace, source = workspace_with()
    report = preview(workspace, [proposal("a"), proposal("b", rectangle(150, 10), "11")])
    append = GeoMap.append_polygon
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("synthetic encoder failure")
        return append(*args, **kwargs)

    monkeypatch.setattr(GeoMap, "append_polygon", fail_second)
    with pytest.raises(ValueError, match="synthetic"):
        apply(workspace, report)
    assert workspace.export_copy(report["documentToken"])[1] == source
    assert not workspace.editing_status()["canUndo"]


def test_apply_uses_immutable_reviewed_coordinates_and_cannot_replay():
    workspace, _ = workspace_with()
    items = [proposal("a")]
    report = preview(workspace, items)
    items[0]["points"][0] = [-500, -500]
    report["items"][0]["points"][0] = [-600, -600]
    saved = apply(workspace, report)
    assert geometry_of(workspace._doc.by_id[saved["createdUids"][0]]).equals(Polygon(rectangle(102, 10)))
    with pytest.raises(RuntimeError, match="świeży podgląd"):
        apply(workspace, report)


def test_preview_key_cannot_be_forged_or_reused_after_reselection():
    workspace, _ = workspace_with()
    first = preview(workspace, [proposal("a")])
    with pytest.raises(RuntimeError, match="świeży podgląd"):
        workspace.apply_trace_batch(preview_key="forged", **context(workspace))
    second = preview(workspace, [proposal("b", rectangle(150, 10), "11")])
    with pytest.raises(RuntimeError, match="świeży podgląd"):
        apply(workspace, first)
    assert apply(workspace, second)["createdCount"] == 1


@pytest.mark.parametrize("method", ["fit", "preview", "apply"])
@pytest.mark.parametrize("bad_context", [{"revision": True}, {"revision": 1}, {"document_token": "wrong"}])
def test_all_batch_stages_require_the_current_document_and_revision(method, bad_context):
    workspace, source = workspace_with()
    report = preview(workspace, [proposal("a")])
    args = {**context(workspace), **bad_context}
    with pytest.raises(RuntimeError, match="Mapa zmieniła się"):
        if method == "fit":
            workspace.fit_trace_batch([proposal("a")], **args)
        elif method == "preview":
            workspace.preview_trace_batch([proposal("a")], **args)
        else:
            workspace.apply_trace_batch(preview_key=report["previewKey"], **args)
    assert workspace.export_copy(workspace.editing_status()["documentToken"])[1] == source


def test_loading_another_map_clears_review_and_blocks_late_old_batch_apply():
    workspace, source = workspace_with()
    report = preview(workspace, [proposal("a")])
    old_context = context(workspace)
    workspace.load_map(source, "another.MAP")
    assert workspace._trace_batch_preview is None
    with pytest.raises(RuntimeError, match="Mapa zmieniła się"):
        workspace.apply_trace_batch(preview_key=report["previewKey"], **old_context)
    with pytest.raises(RuntimeError, match="świeży podgląd"):
        apply(workspace, report)


def test_late_preview_from_previous_map_cannot_clear_current_approved_batch():
    workspace, source = workspace_with()
    old_context = context(workspace)
    workspace.load_map(source, "another.MAP")
    report = preview(workspace, [proposal("current")])
    with pytest.raises(RuntimeError, match="Mapa zmieniła się"):
        workspace.preview_trace_batch([proposal("old")], **old_context)
    assert apply(workspace, report)["proposalIds"] == ["current"]


@pytest.mark.parametrize("items,match", [
    ([], "1–1000"),
    ([proposal(i) for i in range(1001)], "1–1000"),
    ([proposal("a"), proposal("a")], "unikatowych"),
    ([proposal(1), proposal("1")], "unikatowych"),
    ([proposal(True)], "unikatowych"),
    ([proposal("a" * 81)], "unikatowych"),
    ([proposal(i, [[0, 0]] * 500) for i in range(101)], "50 000"),
])
def test_global_batch_limits_fail_explicitly_without_truncation(items, match):
    workspace, _ = workspace_with()
    with pytest.raises(ValueError, match=match):
        fit(workspace, items)
    assert not workspace.editing_status()["canUndo"]


def test_full_map_can_contain_one_thousand_proposals_without_truncation():
    workspace, _ = workspace_with()
    items = [proposal(i, rectangle(150 + (i % 40) * 40, (i // 40) * 40)) for i in range(1000)]
    result = fit(workspace, items)
    assert result["stats"]["total"] == result["stats"]["ready"] == 1000
    assert [item["id"] for item in result["items"]] == list(range(1000))


@pytest.mark.parametrize("bad", [
    {"a1": "bad\nvalue"}, {"a1": "a]"}, {"a1": "🙂"}, {"a1": "1" * 513}, {"a1": True},
    {"points": [[float("nan"), 1], [2, 3], [4, 5]]}, {"points": rectangle(102, 10) * 126},
    {"lockedPoints": [[300, 300]]}, {"seedPoints": [[True, 3]]}, {"unknown": "value"},
])
def test_invalid_individual_item_does_not_discard_other_proposals(bad):
    workspace, _ = workspace_with()
    result = fit(workspace, [proposal("bad", **bad), proposal("good", rectangle(150, 10))])
    assert result["items"][0]["status"] == "rejected" and result["items"][0]["reason"]
    assert result["items"][1]["status"] == "ready"


def test_dense_geometry_work_limit_is_explicit_and_read_only(monkeypatch):
    from geostudio.web_app import raster_trace_batch
    workspace, source = workspace_with()
    monkeypatch.setattr(raster_trace_batch, "MAX_BATCH_PAIR_CHECKS", 2)
    with pytest.raises(ValueError, match="Zbyt wiele"):
        fit(workspace, [proposal(i, rectangle(150, 10)) for i in range(4)])
    assert workspace.export_copy(workspace.editing_status()["documentToken"])[1] == source


def test_source_noding_work_limit_is_explicit_and_read_only(monkeypatch):
    from geostudio.web_app import raster_trace_batch
    workspace, source = workspace_with()
    monkeypatch.setattr(raster_trace_batch, "MAX_BATCH_NODE_CHECKS", 2)
    with pytest.raises(ValueError, match="Zbyt wiele wspólnych węzłów"):
        fit(workspace, [proposal("a")])
    assert workspace.export_copy(workspace.editing_status()["documentToken"])[1] == source
    assert not workspace.editing_status()["canUndo"]


def test_http_batch_fit_review_apply_and_stale_session_guards():
    workspace, _ = workspace_with()
    app = create_app(workspace)
    headers = {"X-GeoStudio-Token": app.state.api_token}
    state = workspace.editing_status()
    args = {"documentToken": state["documentToken"], "revision": state["revision"]}
    base = "/api/underlay/raster/batch/"
    with TestClient(app) as client:
        assert client.post(base + "fit", json={**args, "items": [proposal("a")]}).status_code == 403
        response = client.post(base + "fit", headers=headers,
                               json={**args, "items": [proposal("a")], "snapDistance": 3})
        assert response.status_code == 200
        fitted = response.json()
        assert fitted["items"][0]["snapped"]
        response = client.post(base + "preview", headers=headers,
                               json={**args, "items": ready_items(fitted)})
        assert response.status_code == 200 and response.json()["canApply"]
        response = client.post(base + "apply", headers=headers,
                               json={**args, "previewKey": response.json()["previewKey"]})
        assert response.status_code == 200 and response.json()["createdCount"] == 1
        assert client.post(base + "fit", headers=headers,
                           json={**args, "items": [proposal("b")]}).status_code == 409
        assert client.post(base + "apply", headers=headers,
                           json={**args, "previewKey": "old"}).status_code == 409


def test_http_batch_limits_body_and_rejects_bad_snap_distance():
    workspace, _ = workspace_with()
    app = create_app(workspace)
    headers = {"X-GeoStudio-Token": app.state.api_token}
    status = workspace.editing_status()
    args = {"documentToken": status["documentToken"], "revision": status["revision"]}
    with TestClient(app) as client:
        assert client.post("/api/underlay/raster/batch/fit", headers=headers,
                           json={**args, "items": [proposal("a")], "snapDistance": 21}).status_code == 400
        response = client.post("/api/underlay/raster/batch/preview", headers=headers,
                               content=b"x" * (4 * 1024 * 1024 + 1))
        assert response.status_code == 413
