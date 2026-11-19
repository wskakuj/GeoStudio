"""Map appearance parity smoke tests against the established Qt renderer rules."""
from __future__ import annotations

from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app


def _sample():
    return (MapBuilder(ext=(5000, 0, 0, 300, 300))
            .object("5216", "P", {"A2": "11/4"},
                    [(0, 0), (0, 30), (25, 30), (25, 0)],
                    style="255 15 0")
            .object("5310", "B", {"A1": "b", "A2": "Ol75|II-0.5"},
                    [(50, 50), (50, 60), (60, 60), (60, 50)],
                    style="255 15 0")
            .object("5230", "LS", {"A1": "LsV", "A2": "LsV"},
                    [(70, 70), (70, 90), (90, 90), (90, 70)],
                    style="65280 15 0")
            .object("5230", "ROAD", {"A1": "dr", "A2": "droga"},
                    [(100, 100), (100, 115), (115, 115), (115, 100)],
                    style="255 15 65280")
            .object("5216", "NATIVE", {"A2": "2/7"},
                    [(120, 120), (120, 130), (130, 130), (130, 120)],
                    style="255 15 65280")
            .object("7900", "TITLE", {"TX": "MAPA||Tytuł", "A1": "8"},
                    [(200, 200), (200, 220)], style="0 15 0",
                    closed=False)
            .object("1246", "POINT", {}, [(250, 250)], style="255 15 0",
                    closed=False)
            .build())


def _by_id(workspace):
    features = workspace.viewport((-1e4, -1e4, 1e4, 1e4))["features"]
    return {workspace.details(f["id"])["sourceUid"]: f for f in features}


def test_default_unchanged_parcel_has_native_stroke_and_NO_invented_blue_fill():
    workspace = PreviewWorkspace()
    workspace.load_map(_sample(), "demo.MAP")
    features = _by_id(workspace)
    parcel = features["P"]
    assert parcel["style"]["stroke"] == "#FF0000"
    assert parcel["style"]["hasFill"] is False
    assert parcel["style"]["opacity"] == 0
    building = features["B"]
    assert building["style"]["stroke"] == "#FF0000"
    assert building["style"]["hasFill"] is False
    assert [label["color"] for label in building["labels"]] == [
        "#CC202C", "#CC202C"
    ]
    assert building["labels"][1]["text"] == "Ol75\nII-0.5"
    assert building["labels"][0]["bold"] is True


def test_forest_is_translucent_road_has_no_fill_native_color_does_fill():
    workspace = PreviewWorkspace()
    workspace.load_map(_sample(), "demo.MAP")
    features = _by_id(workspace)
    assert features["LS"]["style"]["hasFill"]
    assert features["LS"]["style"]["opacity"] == 0.4
    assert features["LS"]["style"]["fill"] == "#3D9A62"
    assert features["ROAD"]["style"]["hasFill"] is False
    assert features["ROAD"]["style"]["opacity"] == 0
    assert features["NATIVE"]["style"]["hasFill"] is True
    assert features["NATIVE"]["style"]["fill"] == "#00FF00"
    assert features["NATIVE"]["style"]["opacity"] == 1


def test_annotation_has_no_fake_baseline_and_uses_A1_height():
    workspace = PreviewWorkspace()
    workspace.load_map(_sample(), "demo.MAP")
    features = _by_id(workspace)
    title = features["TITLE"]
    assert title["style"]["drawStroke"] is False
    assert title["labels"][0]["worldTextHeight"] == 8
    assert title["labels"][0]["text"] == "MAPA\nTytuł"
    assert title["labels"][0]["fontFamily"] == "Times New Roman"
    assert features["POINT"]["style"]["pointSize"] <= 1


def test_native_polygon_centroid_instead_of_wrong_bbox_midpoint():
    ws = PreviewWorkspace()
    irregular = (MapBuilder(ext=(5000, 0, 0, 100, 100))
        .object("5216", "ASYMM", {"A2": "12/1"},
                [(0, 0), (0, 20), (5, 20), (5, 5), (20, 5), (20, 0)])
        .build())
    ws.load_map(irregular, "test.MAP")
    label = ws.viewport((-50, -50, 50, 50))["features"][0]["labels"][0]
    # This concave L-shaped outline's bbox centre is (10, 10),
    # while centroid lies closer to the broad bottom and left arms.
    assert 2 < label["x"] < 10
    assert -10 < label["y"] < -2


def test_read_only_api_returns_no_synthetic_color_for_parcel():
    ws = PreviewWorkspace()
    ws.load_map(_sample(), "test.MAP")
    app = create_app(ws)
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        result = client.get("/api/viewport", params={
            "xmin": -100, "ymin": -300, "xmax": 300, "ymax": 100,
        }, headers={"X-GeoStudio-Token": app.state.api_token})
    assert result.status_code == 200
    parcel = next(f for f in result.json()["features"] if f["code"] == "5216")
    assert parcel["style"]["stroke"] == "#FF0000"
    assert parcel["style"]["hasFill"] is False
