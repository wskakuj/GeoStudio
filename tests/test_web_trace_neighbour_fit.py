"""Actual raster-fit geometry, occupied-click guards and preview/save parity."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point, Polygon

from conftest import MapBuilder, point_record
from geostudio.geomap import GeoMap
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.geometry_6a import geometry_of
from geostudio.web_app.raster_trace_fit import fit_neighbour_boundaries
from geostudio.web_app.server import create_app


LEFT = [(0, 0), (100, 0), (100, 100), (0, 100)]
RIGHT = [[102, 10], [200, 10], [200, 90], [102, 90]]


def workspace_with(*polygons):
    builder = MapBuilder()
    for i, (code, ring) in enumerate(polygons or [("5310", LEFT)]):
        builder.object(code, f"SOURCE-{i}", {"A1": str(i + 1)}, ring)
    source = builder.build()
    workspace = PreviewWorkspace()
    workspace.load_map(source, "synthetic.MAP")
    return workspace, source


def fit(workspace, points, distance=3, seeds=None, locked=None):
    status = workspace.editing_status()
    return workspace.fit_trace_outline(points, snap_distance=distance, seed_points=seeds,
                                       locked_points=locked,
                                       document_token=status["documentToken"],
                                       revision=status["revision"])


@pytest.mark.parametrize("left_x", [101.5, 102, 102.9])
def test_full_parallel_side_closes_gap_and_keeps_other_sides(left_x):
    workspace, _ = workspace_with()
    points = [[left_x, 10], [200, 10], [200, 90], [left_x, 90]]
    result = fit(workspace, points, seeds=[[150, 50]])
    assert result["snapped"]
    assert not result["clipped"]
    assert result["points"] == [(100., 10.), (200, 10), (200, 90), (100., 90.)]
    proposed = Polygon(result["points"])
    assert proposed.intersection(Polygon(LEFT)).equals(LineString([(100, 10), (100, 90)]))


def test_partial_shared_side_retains_reference_t_junction_without_extrapolating():
    workspace, _ = workspace_with()
    result = fit(workspace, [[50, 102], [150, 102], [150, 150], [50, 150]], seeds=[[100, 130]])
    expected = [(50, 100), (100, 100), (150, 102), (150, 150), (50, 150)]
    assert result["snapped"]
    assert result["points"] == expected
    assert Polygon(expected).intersection(Polygon(LEFT)).equals(LineString([(50, 100), (100, 100)]))


def test_two_supported_sides_meet_at_real_neighbour_corner():
    workspace, _ = workspace_with()
    draft = [[102, 10], [200, 10], [200, 200], [10, 200], [10, 102], [102, 102]]
    result = fit(workspace, draft, seeds=[[150, 50], [50, 150]])
    assert result["snapped"]
    assert result["points"] == [(100., 10.), (200, 10), (200, 200), (10, 200), (10., 100.), (100., 100.)]
    assert Polygon(result["points"]).intersection(Polygon(LEFT)).area == 0


def test_reference_bend_is_retained_and_is_not_replaced_by_a_parallel_chord():
    reference = [(0, 0), (100, 0), (101, 50), (100, 100), (0, 100)]
    workspace, _ = workspace_with(("5310", reference))
    result = fit(workspace, [[103, 10], [200, 10], [200, 90], [103, 90]], distance=4)
    assert result["snapped"]
    assert (101., 50.) in result["points"]
    # Endpoint projections are rounded to the MAP 1 mm grid, intermediate
    # native vertices stay exact. Only a submillimetre boundary strip remains.
    shape = Polygon(result["points"])
    assert shape.intersection(Polygon(reference)).area < .05
    assert shape.boundary.distance(Polygon(reference).boundary) == 0


@pytest.mark.parametrize("draft,distance", [
    ([[104, 10], [200, 10], [200, 90], [104, 90]], 3),
    ([[101, 102], [190, 102], [190, 190], [101, 190]], 3),
    ([[102, 99], [150, 147], [180, 147], [130, 97]], 3),
])
def test_out_of_range_corner_only_and_crossing_sides_do_not_snap(draft, distance):
    fitted, count = fit_neighbour_boundaries(draft, [Polygon(LEFT)], distance)
    assert count == 0
    assert Polygon(fitted).equals(Polygon(draft))


def test_manual_fit_with_zero_range_keeps_deliberate_nearby_gap():
    workspace, _ = workspace_with()
    result = fit(workspace, RIGHT, distance=0)
    assert not result["snapped"]
    assert result["points"] == [tuple(p) for p in RIGHT]


def test_inherited_manual_corner_stays_fixed_while_new_side_joins_5310():
    workspace, _ = workspace_with()
    manual = [205, 7]
    draft = [[102, 10], manual, [200, 90], [102, 90]]
    result = fit(workspace, draft, locked=[manual])
    assert result["snapped"]
    assert tuple(manual) in result["points"]
    assert Polygon(result["points"]).intersection(Polygon(LEFT)).equals(
        LineString([(100, 10), (100, 90)]))


def test_locked_corner_on_fitted_side_uses_explicit_manual_bridge():
    workspace, _ = workspace_with()
    result = fit(workspace, RIGHT, locked=[[102, 10]])
    assert result["snapped"]
    assert (102., 10.) in result["points"], "The explicit manually moved point must remain a vertex"
    assert (100., 10.) in result["points"], "Keep the reference path endpoint beside the manual bridge"
    shape = Polygon(result["points"])
    assert shape.is_valid
    assert shape.intersection(Polygon(LEFT)).equals(LineString([(100, 10), (100, 90)]))


def test_safe_collinear_locked_vertex_survives_clipping_elsewhere():
    workspace, _ = workspace_with()
    draft = [[90, 10], [150, 10], [150, 50], [150, 90], [90, 90]]
    result = fit(workspace, draft, locked=[[150, 50]])
    assert result["clipped"]
    assert (150., 50.) in result["points"]
    assert Polygon(result["points"]).intersection(Polygon(LEFT)).area == 0


def test_locked_vertex_cannot_reintroduce_occupied_geometry():
    workspace, source = workspace_with()
    draft = [[90, 10], [150, 10], [150, 90], [90, 90]]
    with pytest.raises(ValueError, match="koliduje"):
        fit(workspace, draft, locked=[[90, 10]])
    assert workspace.export_copy(workspace.editing_status()["documentToken"])[1] == source


def test_lock_binds_to_existing_draft_vertex_with_map_rounding_tolerance():
    workspace, _ = workspace_with()
    result = fit(workspace, RIGHT, locked=[[200.0002, 9.9998]])
    assert result["snapped"]
    assert (200, 10) in result["points"]
    with pytest.raises(ValueError, match="nie należy"):
        fit(workspace, RIGHT, locked=[[200, 50]])


def test_locks_do_not_bypass_stale_document_or_hole_guards():
    workspace, _ = workspace_with()
    status = workspace.editing_status()
    with pytest.raises(RuntimeError, match="Mapa zmieniła się"):
        workspace.fit_trace_outline(RIGHT, locked_points=[[200, 10]], snap_distance=3,
                                    document_token=status["documentToken"], revision=status["revision"] + 1)
    draft = [[-10, -10], [150, -10], [150, 150], [-10, 150]]
    with pytest.raises(ValueError, match="osobne części lub otwór"):
        fit(workspace, draft, locked=[[-10, -10]])


@pytest.mark.parametrize("locked", ["invalid", [[True, 10]], [[float("inf"), 10]], [[200]], [[200, 10]] * 501])
def test_invalid_locked_vertices_are_rejected(locked):
    workspace, _ = workspace_with()
    with pytest.raises(ValueError, match="zablokowane węzły"):
        fit(workspace, RIGHT, locked=locked)


def test_locked_points_are_honoured_by_http_fit_and_canonical_save():
    workspace, _ = workspace_with()
    status = workspace.editing_status()
    context = {"documentToken": status["documentToken"], "revision": status["revision"]}
    app = create_app(workspace)
    headers = {"X-GeoStudio-Token": app.state.api_token}
    with TestClient(app) as client:
        fitted = client.post("/api/underlay/raster/fit", headers=headers, json={
            **context, "points": RIGHT, "snapDistance": 3, "lockedPoints": [[102, 10]],
        })
        assert fitted.status_code == 200, fitted.text
        assert fitted.json()["snapped"]
        assert [102, 10] in fitted.json()["points"]
        operation = {"action": "create", "code": "5310", "fields": {"A1": "73"},
                     "points": fitted.json()["points"], "clipRasterOverlap": True}
        preview = client.post("/api/objects/preview", headers=headers,
                              json={**context, "operation": operation})
        assert preview.status_code == 200, preview.text
        assert "adjustedPoints" not in preview.json()
        saved = client.post("/api/objects/apply", headers=headers, json={
            **context, "operation": operation, "previewKey": preview.json()["previewKey"],
        })
        assert saved.status_code == 200, saved.text
    result = GeoMap(workspace.export_copy(status["documentToken"])[1])
    created = result.by_id[saved.json()["createdUids"][0]]
    assert (102, 10) in {(p.x, p.y) for p in created.points}
    assert geometry_of(created).intersection(Polygon(LEFT)).area == 0


def test_5216_is_not_occupied_land_or_a_5310_neighbour():
    workspace, _ = workspace_with(("5216", LEFT))
    inside = [[10, 10], [90, 10], [90, 90], [10, 90]]
    result = fit(workspace, inside, seeds=[[50, 50]])
    assert not result["clipped"] and not result["snapped"]
    assert result["points"] == [tuple(p) for p in inside]


@pytest.mark.parametrize("seed", [[90, 50], [100, 50], [10, 10]])
def test_occupied_click_cannot_become_a_free_strip_elsewhere(seed):
    workspace, source = workspace_with()
    draft = [[80, 10], [150, 10], [150, 90], [80, 90]]
    with pytest.raises(ValueError, match="zajmuje już istniejący 5310"):
        fit(workspace, draft, seeds=[seed])
    assert workspace.export_copy(workspace.editing_status()["documentToken"])[1] == source


def test_each_selected_seed_is_checked_and_unrelated_remainders_are_rejected():
    workspace, _ = workspace_with()
    draft = [[80, 10], [150, 10], [150, 90], [80, 90]]
    with pytest.raises(ValueError, match="zajmuje już"):
        fit(workspace, draft, seeds=[[130, 50], [90, 50]])
    with pytest.raises(ValueError, match="nie obejmuje wskazanego pola"):
        fit(workspace, RIGHT, seeds=[[400, 50]])


def test_click_near_regularized_boundary_can_survive_the_chosen_fit_range():
    workspace, _ = workspace_with()
    result = fit(workspace, RIGHT, seeds=[[101, 50]])
    assert result["snapped"]
    assert Polygon(result["points"]).covers(Point(101, 50))


def test_clipping_keeps_single_free_region_and_rejects_disconnected_or_holed_drafts():
    workspace, _ = workspace_with()
    clipped = fit(workspace, [[90, 10], [150, 10], [150, 90], [90, 90]], seeds=[[130, 50]])
    assert clipped["clipped"]
    assert Polygon(clipped["points"]).intersection(Polygon(LEFT)).area == 0
    with pytest.raises(ValueError, match="osobne części lub otwór"):
        fit(workspace, [[-10, 10], [150, 10], [150, 90], [-10, 90]])
    with pytest.raises(ValueError, match="osobne części lub otwór"):
        fit(workspace, [[-10, -10], [150, -10], [150, 150], [-10, 150]])


def test_hole_in_existing_multipart_5310_remains_free_and_uses_its_inner_boundary():
    builder = MapBuilder().raw("*5310 8553090  15          0").field("ID", "DONUT")
    outer = LEFT + [LEFT[0]]
    inner = [(30, 30), (70, 30), (70, 70), (30, 70), (30, 30)]
    for ring in (outer, inner):
        for i, (x, y) in enumerate(ring):
            builder.raw(point_record(x, y, kind=0 if i == len(ring) - 1 else 1))
    workspace = PreviewWorkspace()
    workspace.load_map(builder.build(), "hole.MAP")
    result = fit(workspace, [[32, 32], [68, 32], [68, 68], [32, 68]], seeds=[[50, 50]])
    assert result["snapped"]
    assert Polygon(result["points"]).equals(Polygon(inner))
    assert not result["clipped"]


def test_full_fit_http_save_and_undo_preserve_existing_native_records():
    north, east = 5_847_000, 7_522_000

    def shifted(ring):
        return [[north + x, east + y] for x, y in ring]

    workspace, source = workspace_with(("5310", shifted(LEFT)))
    status = workspace.editing_status()
    context = {"documentToken": status["documentToken"], "revision": status["revision"]}
    app = create_app(workspace)
    headers = {"X-GeoStudio-Token": app.state.api_token}
    with TestClient(app) as client:
        fitted = client.post("/api/underlay/raster/fit", headers=headers, json={
            **context, "points": shifted(RIGHT), "snapDistance": 3,
            "seedPoints": shifted([[150, 50]]),
        })
        assert fitted.status_code == 200, fitted.text
        assert fitted.json()["snapped"]
        operation = {"action": "create", "code": "5310", "fields": {"A1": "73"},
                     "points": fitted.json()["points"], "clipRasterOverlap": True}
        preview = client.post("/api/objects/preview", headers=headers,
                              json={**context, "operation": operation})
        assert preview.status_code == 200, preview.text
        assert "adjustedPoints" not in preview.json()
        saved = client.post("/api/objects/apply", headers=headers, json={
            **context, "operation": operation, "previewKey": preview.json()["previewKey"],
        })
        assert saved.status_code == 200, saved.text
    result = GeoMap(workspace.export_copy(status["documentToken"])[1])
    original = GeoMap(source)
    before, after = original.by_id["SOURCE-0"], result.by_id["SOURCE-0"]
    assert original.lines[before.start:before.end] == result.lines[after.start:after.end]
    created = geometry_of(result.by_id[saved.json()["createdUids"][0]])
    assert created.equals(Polygon(operation["points"]))
    assert created.intersection(geometry_of(after)).equals(LineString(shifted([[100, 10], [100, 90]])))
    current = workspace.editing_status()
    workspace.step_history("undo", document_token=current["documentToken"], revision=current["revision"])
    assert workspace.export_copy(status["documentToken"])[1] == source


@pytest.mark.parametrize("extra", [
    {"snapDistance": -1}, {"snapDistance": 21}, {"snapDistance": True},
    {"seedPoints": [[float("inf"), 0]]}, {"seedPoints": [[True, 1]]},
    {"seedPoints": ["invalid"]}, {"seedPoints": [[150, 50]] * 501},
])
def test_fit_parameters_are_validated(extra):
    workspace, _ = workspace_with()
    with pytest.raises(ValueError):
        fit(workspace, RIGHT, distance=extra.get("snapDistance", 3), seeds=extra.get("seedPoints"))


def test_single_seed_alias_is_accepted_and_guarded_over_http():
    workspace, _ = workspace_with()
    status = workspace.editing_status()
    app = create_app(workspace)
    with TestClient(app) as client:
        response = client.post("/api/underlay/raster/fit", headers={"X-GeoStudio-Token": app.state.api_token},
                               json={"documentToken": status["documentToken"], "revision": status["revision"],
                                     "points": [[80, 10], [150, 10], [150, 90], [80, 90]],
                                     "seedPoint": [90, 50], "snapDistance": 3})
    assert response.status_code == 400
    assert "zajmuje już" in response.json()["detail"]
