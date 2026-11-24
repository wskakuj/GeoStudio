"""GeoStudio 2.0 read-only API / real GEO-MAP parser smoke tests.

All samples are synthetic. No user map is committed or transmitted.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app


@pytest.fixture
def sample_map() -> bytes:
    return (MapBuilder(ext=(5000, 0, 0, 400, 500))
            .object("5310", "B-01", {"A1": "b", "A2": "Budynek A", "A3": "opis"},
                    [(100, 200), (110, 200), (110, 220), (100, 220)])
            .object("5230", "LS-01", {"A1": "LsV", "A2": "LsV"},
                    [(120, 230), (150, 230), (150, 280), (120, 280)])
            .object("5230", "ROAD", {"A1": "dr", "A2": "droga"},
                    [(180, 330), (190, 330), (190, 350), (180, 350)])
            .object("5216", "PARCEL", {"A2": "54/1"},
                    [(200, 360), (220, 360), (220, 390), (200, 390)])
            .object("6900", "LINE", {"TX": "Linia"},
                    [(240, 450), (250, 460)], closed=False)
            .build())


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c, {"X-GeoStudio-Token": app.state.api_token}


def test_preview_parser_preserves_source_and_correct_native_axes(sample_map):
    workspace = PreviewWorkspace()
    before = bytes(sample_map)
    meta = workspace.load_map(sample_map, "MOKRA WIEŚ.MAP")
    assert meta["name"] == "MOKRA WIEŚ.MAP"
    assert meta["objectCount"] == 5
    assert meta["checksumValid"]
    assert meta["readOnly"]
    assert meta["forestClasses"] == {"LsV": 1}
    # 6900 lines became the "Numery oddziałów · 6900" layer in the raster-trace
    # line; the fixture still holds exactly one such object.
    names = {d["name"] for d in meta["layers"]}
    # Kod 5310 to teraz „Wydzielenie”; 5332 to „Budynki”.
    assert names >= {"Wydzielenie", "Użytki Leśne", "Użytki", "Działki"}
    assert any(n.startswith("Numery oddziałów") for n in names), names
    # Map (native northing X=100, easting Y=200) becomes browser (200,-100).
    features = workspace.viewport((199, -112, 223, -99))["features"]
    building = next(f for f in features if f["code"] == "5310")
    assert building["geometry"][0][0] == [200, -100]
    assert building["bbox"] == (200, -110, 220, -100)
    assert building["labels"][0]["text"] == "b"
    assert building["labels"][1]["text"] == "Budynek A"
    assert workspace.details(building["id"])["sourceUid"] == "B-01"
    assert workspace.details(building["id"])["areaM2"] == 200
    assert before == sample_map


def test_backend_uses_viewport_index_not_entire_map(sample_map):
    state = PreviewWorkspace()
    state.load_map(sample_map, "test.MAP")
    nearby = state.viewport((200, -111, 220, -100))
    assert len(nearby["features"]) == 1
    assert nearby["features"][0]["code"] == "5310"
    far = state.viewport((-1000, -1000, -900, -900))
    assert far["features"] == []
    # Huge requests are clamped to actual map bounds to avoid tile explosions.
    broad = state.viewport((-1e8, -1e8, 1e8, 1e8))
    assert broad["total"] == 5
    assert len(state.viewport((-1e8, -1e8, 1e8, 1e8),limit=2)["features"]) == 2
    assert state.viewport((-1e8, -1e8, 1e8, 1e8),limit=2)["limited"] is True
    with pytest.raises(ValueError):
        state.viewport((float("inf"), 0, 4, 4))


def test_sidecar_changes_only_view_colors_and_labels(sample_map):
    state = PreviewWorkspace()
    state.load_map(sample_map, "test.MAP")
    payload = {
        "format": "geostudio-visual-v1",
        "objects": {
            "code:5310": {"opacity": 63, "fill": "#347ABC", "stroke": "#123456",
                          "stroke_width": 2.5, "force_fill": True},
            "labels:code:5310": {"fields": {
                "A1": {"visible": False},
                "A3": {"visible": True, "size": 18, "color": "#112233"}
            }},
        },
        "labels": {"B-01": {"A3": [105, 210]}},
    }
    state.set_visual_sidecar(json.dumps(payload).encode())
    result = state.viewport((190, -116, 225, -99))
    feature = result["features"][0]
    assert feature["style"]["fill"] == "#347ABC"
    assert feature["style"]["opacity"] == .63
    assert feature["style"]["stroke"] == "#123456"
    assert feature["style"]["strokeWidth"] == 2.5
    assert [label["field"] for label in feature["labels"]] == ["A3"]
    assert feature["labels"][0]["text"] == "opis"
    assert (feature["labels"][0]["x"],feature["labels"][0]["y"]) == (210,-105)
    assert state.details(feature["id"])["fields"]["A2"] == "Budynek A"


def test_local_only_api_file_upload_and_inspector(client, sample_map):
    c, auth = client
    assert c.get("/api/map").status_code == 403
    assert c.get("/api/map", headers={"host":"attack.example",**auth}).status_code == 403
    page = c.get("/")
    assert page.status_code == 200
    assert 'name="api-token"' in page.text
    assert "Nowy standard pracy" in page.text
    assert c.get("/map.js").status_code == 200
    assert c.get("/styles.css").status_code == 200
    response = c.post("/api/map", content=sample_map, headers={
        **auth, "X-Map-Name": "MOKRA%20WIE%C5%9A.MAP",
        "Content-Type": "application/octet-stream"
    })
    assert response.status_code == 200
    assert response.json()["name"] == "MOKRA WIEŚ.MAP"
    info = c.get("/api/map",headers=auth).json()
    assert info["objectCount"] == 5
    features = c.get("/api/viewport",params={
        "xmin":195,"ymin":-111,"xmax":225,"ymax":-99
    },headers=auth).json()["features"]
    assert len(features) == 1
    detail = c.get("/api/object/"+features[0]["id"],headers=auth).json()
    assert detail["code"] == "5310"
    assert detail["fields"]["A1"] == "b"
    assert c.get("/api/object/does-not-exist",headers=auth).status_code == 404
    assert c.get("/api/viewport",params={
        "xmin":10,"ymin":10,"xmax":0,"ymax":0
    },headers=auth).status_code == 400


def test_preview_rejects_invalid_sources_but_keeps_previous_map(sample_map):
    state = PreviewWorkspace()
    state.load_map(sample_map, "safe.MAP")
    with pytest.raises(ValueError, match="rozszerzeniem"):
        state.load_map(sample_map, "not-map.exe")
    with pytest.raises(ValueError, match="obiektów"):
        state.load_map(b"wrong", "broken.MAP")
    with pytest.raises(ValueError, match="Niepoprawny"):
        state.set_visual_sidecar(b"not json")
    assert state.metadata()["name"] == "safe.MAP"
    assert state.metadata()["checksumValid"]


def test_no_export_write_edit_paths_exposed(client, sample_map, tmp_path):
    c, auth = client
    source = tmp_path / "saved.MAP"
    source.write_bytes(sample_map)
    before = source.read_bytes()
    result = c.post("/api/map",content=source.read_bytes(),
                    headers={**auth, "X-Map-Name":"saved.MAP"})
    assert result.status_code == 200
    assert c.post("/api/save",headers=auth).status_code == 404
    assert c.post("/api/objects/f0",headers=auth).status_code == 404
    assert c.delete("/api/objects/f0",headers=auth).status_code == 404
    assert source.read_bytes() == before
