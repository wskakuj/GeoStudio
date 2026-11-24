"""Automatyczne układanie etykiet A1/A2 dla poligonów 5310."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from shapely.geometry import box  # noqa: E402

from geostudio.web_app.label_layout import (  # noqa: E402
    FLAG_LEFT, FLAG_PLAIN, FLAG_RIGHT, auto_layout_5310_labels, polylabel,
    text_size)


def _layout(objects, scale=5000):
    return auto_layout_5310_labels(objects, scale=scale)


def test_large_polygon_gets_both_labels_inside():
    big = box(0, 0, 300, 300)
    result = _layout([("u1", big, (150.0, 150.0), "02r", "6OL55|0.26")])
    change = result["changes"][0]
    assert change["mode"] == "inside"
    assert change["labels"]["A1"]["flags"] == FLAG_PLAIN
    assert change["labels"]["A2"]["flags"] == FLAG_PLAIN
    # Napisy stoją w środku poligonu, więc offsety są niezerowe,
    # ale nie ma żadnego wysięgnika.
    assert result["stats"]["leaders"] == 0
    assert change["labels"]["A1"].get("anchor") is None


def test_narrow_polygon_keeps_a1_inside_and_puts_a2_on_leader():
    strip = box(0, 0, 22, 400)          # wąski w osi północy, długi pas
    result = _layout([("u2", strip, (11.0, 200.0), "02c", "OL55|0.02")])
    change = result["changes"][0]
    assert change["labels"]["A1"]["flags"] == FLAG_PLAIN
    leader = change["labels"]["A2"]
    assert leader["flags"] in (FLAG_RIGHT, FLAG_LEFT)
    assert result["stats"]["leaders"] >= 1


def test_flag_matches_the_side_of_the_anchor():
    # Pas 10 m w osi północy: etykieta A2 (12,4 m wysokości) się nie mieści.
    strip = box(0, 0, 10, 400)
    result = _layout([("u3", strip, (7.0, 200.0), "", "OL55|0.02")])
    label = result["changes"][0]["labels"]["A2"]
    # Napis na wschód od zaczepu => flaga 69, na zachód => 133.
    if label["dx"] >= 0:
        assert label["flags"] == FLAG_RIGHT
    else:
        assert label["flags"] == FLAG_LEFT


def test_small_polygon_puts_both_on_leaders():
    tiny = box(0, 0, 12, 12)
    result = _layout([("u4", tiny, (6.0, 6.0), "02c", "OL55|0.02")])
    change = result["changes"][0]
    assert change["mode"] in ("external", "mixed")
    assert result["stats"]["leaders"] >= 1


def test_polylabel_stays_inside_concave_polygon():
    from shapely.geometry import Point, Polygon
    shape = Polygon([(0, 0), (0, 100), (20, 100), (20, 20), (100, 20), (100, 0)])
    x, y = polylabel(shape, precision=0.5)
    assert shape.contains(Point(x, y))


def test_text_size_matches_the_renderer_metrics():
    """Rozmiar napisu nie zależy od skali — tak liczy klient (labelFontSize)."""
    small = text_size("02r", 5000)
    large = text_size("02r", 10000)
    assert small == large
    # 4 znaki + padding, wysokość jednej linii ~10,6 m
    assert 10.0 < small[1] < 13.0


def test_auto_layout_is_atomic_and_reversible():
    from geostudio.web_app.data import PreviewWorkspace
    source = Path("/scratch/input/02_BYSŁAWEK.MAP")
    if not source.exists():
        import pytest
        pytest.skip("brak mapy testowej")
    workspace = PreviewWorkspace()
    workspace.load_map(source.read_bytes(), "02.MAP")
    before = workspace._doc.to_bytes()
    status = workspace.editing_status()
    result = workspace.auto_layout_5310_labels(
        "all", 5000, document_token=status["documentToken"],
        revision=status["revision"])
    assert result["changed"] is True
    assert workspace._doc.to_bytes() != before
    # Cofnięcie przywraca dokładnie poprzednie bajty (jedna operacja historii).
    status = workspace.editing_status()
    workspace.step_history("undo", document_token=status["documentToken"],
                           revision=status["revision"])
    assert workspace._doc.to_bytes() == before


def test_offsets_use_geo_map_axis_order():
    """dx to przesunięcie na PÓŁNOC, dy na WSCHÓD (osie rekordu L)."""
    from shapely.geometry import box as _box
    strip = _box(0, 0, 10, 400)          # x = północ, y = wschód
    result = _layout([("u9", strip, (7.0, 200.0), "", "OL55|0.02")])
    label = result["changes"][0]["labels"]["A2"]
    # Etykieta odsuwa się na zewnątrz wąskiego pasa: albo na północ, albo
    # na wschód, ale NIGDY o setki kilometrów.
    assert abs(label["dx"]) < 500
    assert abs(label["dy"]) < 500


def test_leader_label_stays_near_its_polygon():
    from geostudio.web_app.data import PreviewWorkspace
    source = Path("/scratch/input/02_BYSŁAWEK.MAP")
    if not source.exists():
        import pytest
        pytest.skip("brak mapy testowej")
    workspace = PreviewWorkspace()
    workspace.load_map(source.read_bytes(), "02.MAP")
    status = workspace.editing_status()
    workspace.auto_layout_5310_labels(
        "all", 5000, document_token=status["documentToken"],
        revision=status["revision"])
    features = workspace.viewport((0, -1e6, 1e6, 1e6), limit=3000)["features"]
    for feature in features:
        if feature["code"] != "5310":
            continue
        west, south, east, north = feature["bbox"]
        diagonal = ((east - west) ** 2 + (north - south) ** 2) ** 0.5
        for label in feature["labels"]:
            assert abs(label["x"] - (west + east) / 2) < diagonal * 10 + 500
            assert abs(-label["y"] - (-south - north) / 2) < diagonal * 10 + 500


def test_inside_label_sits_at_the_polygon_centre_not_at_the_base_point():
    from shapely.geometry import box as _box
    shape = _box(0, 0, 200, 200)
    result = _layout([("u20", shape, (10.0, 10.0), "02r", "6OL55|0.26")])
    labels = result["changes"][0]["labels"]
    # Punkt bazowy to (10,10); napisy mają stać WEWNĄTRZ poligonu, blisko
    # środka (100,100). Każda etykieta ma teraz swoje miejsce.
    for field in ("A1", "A2"):
        x = 10.0 + labels[field]["dy"]      # wschód
        y = 10.0 + labels[field]["dx"]      # północ
        assert 0 < x < 200 and 0 < y < 200
        assert abs(x - 100) < 60 and abs(y - 100) < 60


def test_leader_attaches_to_the_polygon_centre():
    """A1 w środku, A2 na wysięgniku — zaczep w środku poligonu."""
    from shapely.geometry import box as _box
    # 22 m w osi północy: A1 (12,6 m + margines) się mieści, kolumna A1+A2 nie.
    shape = _box(0, 0, 22, 120)
    result = _layout([("u21", shape, (11.0, 60.0), "02c", "OL55|0.02")])
    labels = result["changes"][0]["labels"]
    assert labels["A1"]["flags"] == FLAG_PLAIN
    assert labels["A2"]["flags"] in (FLAG_RIGHT, FLAG_LEFT)
    # Zaczep wysięgnika leży wewnątrz poligonu.
    ax, ay = labels["A2"]["anchor"]
    assert 0 <= 11.0 + ax <= 22 and 0 <= 60.0 + ay <= 120


def test_both_outside_share_one_anchor_in_the_polygon():
    from shapely.geometry import box as _box
    shape = _box(0, 0, 12, 12)              # za mały na cokolwiek
    result = _layout([("u22", shape, (6.0, 6.0), "02c", "OL55|0.02")])
    labels = result["changes"][0]["labels"]
    assert labels["A1"]["flags"] != FLAG_PLAIN
    assert labels["A2"]["flags"] != FLAG_PLAIN
    assert labels["A1"]["anchor"] == labels["A2"]["anchor"]


def test_inside_labels_never_touch_the_boundary():
    from shapely.geometry import box as _box
    shape = _box(0, 0, 60, 30)
    result = _layout([("u23", shape, (15.0, 30.0), "02r", "OL55|0.02")])
    labels = result["changes"][0]["labels"]
    for field in ("A1", "A2"):
        if labels[field]["flags"] != FLAG_PLAIN:
            continue
        from geostudio.web_app.label_layout import text_size
        text = "02r" if field == "A1" else "OL55|0.02"
        width, height = text_size(text, 5000, fraction=(field == "A2"))
        east = 30.0 + labels[field]["dy"]
        north = 15.0 + labels[field]["dx"]
        rect = _box(north - height / 2, east - width / 2,
                    north + height / 2, east + width / 2)
        assert shape.contains(rect), f"{field} wychodzi poza poligon"
        assert rect.distance(shape.boundary) > 0, f"{field} dotyka granicy"
