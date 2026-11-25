"""Saving adjacent raster outlines fitted to 5216 preserves parcel records."""
from __future__ import annotations

from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point, Polygon

from conftest import MapBuilder
from geostudio.geomap import GeoMap
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app


def test_parcel_snap_script_is_served_before_the_tracing_ui():
    app = create_app()
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert page.text.index('src="/raster_parcel_snap.js"') < page.text.index(
            'src="/raster_trace.js"')
        script = client.get("/raster_parcel_snap.js")
        assert script.status_code == 200, script.text
        assert script.headers["content-type"].startswith("text/javascript")
        assert "GeoStudioRasterParcelSnap" in script.text


def test_fitted_5310_preview_save_preserves_5216_and_shared_boundary():
    # Native MAP axes are north/east, while viewport geometry is east/-north.
    north, east = 5_847_000, 7_522_000

    def native(points):
        return [[north + x, east + y] for x, y in points]

    parcel_left = native([(0, 0), (0, 40), (100, 60), (100, 0)])
    parcel_right = native([(0, 40), (0, 100), (100, 100), (100, 60)])
    source = (MapBuilder()
              .object("5216", "PARCEL-LEFT", {"A2": "101/1"}, parcel_left)
              .raw(";# preserve parcel annotation")
              .object("5216", "PARCEL-RIGHT", {"A2": "101/2"}, parcel_right)
              .build())
    original = GeoMap(source)
    workspace = PreviewWorkspace()
    workspace.load_map(source, "parcels.MAP")
    initial = workspace.editing_status()
    app = create_app(workspace)
    headers = {"X-GeoStudio-Token": app.state.api_token}

    # The candidate's shared edge has already been fitted to the real diagonal
    # parcel edge. Use submillimetre projections to exercise MAP rounding.
    start = (20.123, 44.0246)
    end = (80.456, 56.0912)
    drafts = [
        native([(start[0], 10), start, end, (end[0], 10)]),
        native([start, (start[0], 90), (end[0], 90), end]),
    ]
    created = []
    with TestClient(app) as client:
        reference = client.get("/api/viewport", headers=headers, params={
            "xmin": east - 1, "ymin": -north - 101,
            "xmax": east + 101, "ymax": -north + 1,
            "native": "1", "limit": 1,
        })
        assert reference.status_code == 200, reference.text
        feature = reference.json()["features"][0]
        assert feature["code"] == "5216"
        assert feature["nativeGeometry"][0][1] == [east + 40, -north]
        assert reference.json()["total"] == 2

        for index, points in enumerate(drafts):
            status = workspace.editing_status()
            context = {"documentToken": status["documentToken"],
                       "revision": status["revision"]}
            fitted = client.post("/api/underlay/raster/fit", headers=headers,
                                 json={**context, "points": points})
            assert fitted.status_code == 200, fitted.text
            assert not fitted.json()["clipped"]
            expected = [[round(x, 3), round(y, 3)] for x, y in points]
            assert fitted.json()["points"] == expected

            payload = {**context, "operation": {
                "action": "create", "code": "5310", "points": points,
                "fields": {"A1": str(173 + index)},
                "clipRasterOverlap": True, "mergeSameA1": True,
            }}
            preview = client.post("/api/objects/preview", headers=headers,
                                  json=payload)
            assert preview.status_code == 200, preview.text
            assert "adjustedPoints" not in preview.json()
            saved = client.post("/api/objects/apply", headers=headers, json={
                **payload, "previewKey": preview.json()["previewKey"],
            })
            assert saved.status_code == 200, saved.text
            assert len(saved.json()["createdUids"]) == 1
            created.extend(saved.json()["createdUids"])

        exported = client.get("/api/export/map", headers=headers,
                              params={"documentToken": initial["documentToken"]})
        assert exported.status_code == 200, exported.text

    result = GeoMap(exported.content)
    assert result.checksum_valid
    assert result.declared_lines == len(result.lines)
    for uid in ("PARCEL-LEFT", "PARCEL-RIGHT"):
        before, after = original.by_id[uid], result.by_id[uid]
        assert original.lines[before.start:before.end] == result.lines[after.start:after.end]

    shapes = []
    for index, uid in enumerate(created):
        obj = result.by_id[uid]
        assert obj.code == "5310" and obj.fields["A1"] == str(173 + index)
        assert obj.is_closed
        expected = [(round(x, 3), round(y, 3)) for x, y in drafts[index]]
        # The MAP writer may normalize winding, while retaining every vertex.
        assert {(p.x, p.y) for p in obj.points[:-1]} == set(expected)
        shape = Polygon([(p.x, p.y) for p in obj.points])
        assert shape.equals(Polygon(expected))
        shapes.append(shape)

    shared = LineString([
        (round(north + x, 3), round(east + y, 3)) for x, y in (start, end)
    ])
    assert shapes[0].intersection(shapes[1]).equals(shared)
    assert shapes[0].union(shapes[1]).geom_type == "Polygon"
    parcel_edge = LineString(native([(0, 40), (100, 60)]))
    assert max(parcel_edge.distance(Point(p)) for p in shared.coords) < .001

    # Both normal history steps restore exactly the source MAP, including
    # parcel attributes and unrelated source records.
    for _ in created:
        status = workspace.editing_status()
        workspace.step_history("undo", document_token=status["documentToken"],
                               revision=status["revision"])
    assert workspace.export_copy(initial["documentToken"])[1] == source
