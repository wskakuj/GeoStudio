"""Wysięgniki etykiet A1/A2 z natywnych rekordów L 2 / L 3."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from geostudio.geomap import parse_label_record  # noqa: E402
from geostudio.web_app.data import PreviewWorkspace  # noqa: E402


def test_right_leader_flags_133_and_shared_anchor():
    # 128 = prawa strona etykiety (tak jak rysuje to Geo-MAP).
    record = parse_label_record(
        b"L 2 10.232 -28.481 0.0000000 1.0000000 133 -8.180 1.438")
    assert record["slot"] == 2
    assert record["leader"] == "right"
    assert record["anchor"] == (-8.18, 1.438)
    assert record["dx"] == 10.232 and record["dy"] == -28.481


def test_left_leader_flags_69():
    # 64 = lewa strona etykiety.
    record = parse_label_record(
        b"L 3 8.506 48.331 0.0000393 1.0000000 69 -8.180 1.438")
    assert record["slot"] == 3
    assert record["leader"] == "left"
    assert record["anchor"] == (-8.18, 1.438)


def test_plain_label_has_no_leader():
    record = parse_label_record(b"L 2 0.000 0.000 0.0000000 1.0000000 5")
    assert record["leader"] is None
    assert record["anchor"] is None


def test_labels_payload_carries_leader_for_both_slots():
    source = Path("geostudio/web_app/data.py").read_text(encoding="utf-8")
    assert "label_records(" in source
    assert '"leader": leader' in source
    # slot 2 -> A1, slot 3 -> A2
    assert 'leaders.get(2 if field == "A1" else 3 if field == "A2" else 0)' in source


def _map_with_label(tmp_path=None):
    import pathlib
    source = pathlib.Path("/scratch/input/02_BYSŁAWEK.MAP")
    if not source.exists():
        import pytest
        pytest.skip("brak mapy testowej")
    from geostudio.web_app.data import PreviewWorkspace
    workspace = PreviewWorkspace()
    workspace.load_map(source.read_bytes(), "02.MAP")
    return workspace


def test_toggle_leader_writes_native_flags():
    from geostudio.geomap import parse_label_record
    workspace = _map_with_label()
    status = workspace.editing_status()
    features = workspace.viewport((0, -1e6, 1e6, 1e6), limit=3000)["features"]
    feature = next(f for f in features if f["code"] == "5310")
    # anchor podajemy we współrzędnych świata; do pliku idzie różnica
    # wobec punktu bazowego poligonu.
    from geostudio.web_app.data import _label_anchor
    base = _label_anchor(workspace._lookup[feature["id"]].obj)
    workspace.set_label_leader(feature["id"], 2, True,
                               (base[0] - 8.18, base[1] + 1.438), True,
                               document_token=status["documentToken"],
                               revision=status["revision"])
    entry = workspace._lookup[feature["id"]]
    records = [parse_label_record(line) for line in
               workspace._doc.lines[entry.obj.start:entry.obj.end]]
    slot2 = next(r for r in records if r and r["slot"] == 2)
    assert slot2["leader"] == "left"
    assert slot2["anchor"] == (-8.18, 1.438)
    assert slot2["flags"] & 64          # 64 = lewa strona


def test_moving_label_flips_leader_direction():
    workspace = _map_with_label()
    status = workspace.editing_status()
    features = workspace.viewport((0, -1e6, 1e6, 1e6), limit=3000)["features"]
    feature = next(f for f in features if f["code"] == "5310"
                   and any(item.get("leader") for item in f["labels"]))
    label = next(l for l in feature["labels"] if l.get("leader"))
    anchor_east = label["leader"]["x"]
    anchor_north = -label["leader"]["y"]
    before = label["leader"]["direction"]
    opposite = anchor_east + (500 if before == "left" else -500)
    workspace.move_label(feature["id"], label["field"], anchor_north, opposite,
                         document_token=status["documentToken"],
                         revision=status["revision"])
    updated = workspace.viewport((0, -1e6, 1e6, 1e6), limit=3000)["features"]
    changed = next(f for f in updated if f["id"] == feature["id"])
    moved = next(l for l in changed["labels"] if l["field"] == label["field"])
    assert moved["leader"]["direction"] != before


def test_anchor_is_relative_to_polygon_base():
    """Kotwica w pliku jest względna — payload musi dodać punkt bazowy."""
    from geostudio.web_app.data import _label_anchor
    workspace = _map_with_label()
    features = workspace.viewport((0, -1e6, 1e6, 1e6), limit=3000)["features"]
    feature = next(f for f in features if f["code"] == "5310"
                   and any(item.get("leader") for item in f["labels"]))
    label = next(l for l in feature["labels"] if l.get("leader"))
    base = _label_anchor(workspace._lookup[feature["id"]].obj)
    anchor_north = -label["leader"]["y"]
    anchor_east = label["leader"]["x"]
    # Kotwica nie może wylądować w (0, 0) ani daleko od poligonu.
    distance = ((anchor_east - base[1]) ** 2 + (anchor_north - base[0]) ** 2) ** 0.5
    assert distance < 5000


def test_reset_clears_all_leaders_in_one_step():
    workspace = _map_with_label()
    status = workspace.editing_status()
    before = [f for f in workspace.viewport((0, -1e6, 1e6, 1e6), limit=3000)["features"]
              if any(item.get("leader") for item in f["labels"])]
    assert before
    result = workspace.reset_label_leaders(None,
                                           document_token=status["documentToken"],
                                           revision=status["revision"])
    assert result["changed"] is True and result["reset"] >= 1
    after = [f for f in workspace.viewport((0, -1e6, 1e6, 1e6), limit=3000)["features"]
             if any(item.get("leader") for item in f["labels"])]
    assert after == []


def test_renderer_uses_east_south_anchor():
    """Kotwica w payloadzie to (wschód, -północ) — bez podwójnego minusa."""
    from pathlib import Path
    js = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
    assert "worldToScreen(label.leader.x,label.leader.y)" in js
    assert "worldToScreen(label.leader.y,-label.leader.x)" not in js


def test_leader_shortcuts_are_q_and_w():
    from pathlib import Path
    js = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
    assert 'if(key!=="q"&&key!=="w")return;' in js
    # E jest zajęte przez edycję atrybutów.
    assert 'if(key!=="q"&&key!=="e")return;' not in js


def test_label_move_refreshes_only_the_viewport():
    """Pełny reload dokumentu kasował listę etykiet i blokował kolejne chwycenie."""
    from pathlib import Path
    js = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
    assert "setTimeout(()=>{refreshEditedDocument(drag.fid)" not in js
    assert "scheduleViewport(true);" in js


def test_anchor_clicked_on_map_lands_where_clicked():
    """Kółko podaje [północ, wschód]; kotwica musi trafić w kliknięty punkt."""
    workspace = _map_with_label()
    status = workspace.editing_status()
    features = workspace.viewport((0, -1e6, 1e6, 1e6), limit=3000)["features"]
    feature = next(f for f in features if f["code"] == "5310"
                   and not any(item.get("leader") for item in f["labels"]))
    west, south, east, north = feature["bbox"]
    click = [(south + north) / 2, (west + east) / 2]      # [północ, wschód]
    workspace.set_label_leader(feature["id"], 2, True, click, True,
                               document_token=status["documentToken"],
                               revision=status["revision"])
    updated = workspace.viewport((0, -1e6, 1e6, 1e6), limit=3000)["features"]
    changed = next(f for f in updated if f["id"] == feature["id"])
    label = next(l for l in changed["labels"] if l["field"] == "A1")
    anchor_north = -label["leader"]["y"]
    anchor_east = label["leader"]["x"]
    distance = ((anchor_east - click[1]) ** 2 + (anchor_north - click[0]) ** 2) ** 0.5
    assert distance < 0.5


def test_canvas_sends_north_east_anchor():
    from pathlib import Path
    js = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
    assert "north:-world.y,east:world.x" in js
    assert "anchor:[world.north,world.east]" in js
    assert "anchor:[drag.point.north,drag.point.east]" in js


def test_edit_lock_has_watchdog():
    from pathlib import Path
    js = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
    assert "editBusySince" in js
    assert "odblokowano edycję" in js


def test_label_position_and_leader_survive_map_save():
    """Pozycja A1/A2 i kotwica muszą być w samym MAP, nie tylko w JSON."""
    workspace = _map_with_label()
    status = workspace.editing_status()
    features = workspace.viewport((0, -1e6, 1e6, 1e6), limit=3000)["features"]
    feature = next(f for f in features if f["code"] == "5310"
                   and not any(item.get("leader") for item in f["labels"]))
    west, south, east, north = feature["bbox"]
    click = [(south + north) / 2, (west + east) / 2]
    workspace.set_label_leader(feature["id"], 2, True, click, True,
                               document_token=status["documentToken"],
                               revision=status["revision"])
    status = workspace.editing_status()
    workspace.move_label(feature["id"], "A1", click[0] + 8, click[1] + 12,
                         document_token=status["documentToken"],
                         revision=status["revision"])
    reopened = PreviewWorkspace()
    reopened.load_map(workspace._doc.to_bytes(), "02.MAP")
    updated = reopened.viewport((0, -1e6, 1e6, 1e6), limit=3000)["features"]
    changed = next(f for f in updated if f["id"] == feature["id"])
    label = next(l for l in changed["labels"] if l["field"] == "A1")
    assert label["manuallyPlaced"] is True
    assert abs(label["x"] - (click[1] + 12)) < 0.5
    assert abs(-label["y"] - (click[0] + 8)) < 0.5
    assert label["leader"] is not None


def test_side_flags_match_geo_map(monkeypatch):
    """64 = lewa strona etykiety, 128 = prawa (tak jak rysuje Geo-MAP)."""
    from geostudio.geomap import LEADER_LEFT, LEADER_RIGHT
    assert LEADER_LEFT == 64
    assert LEADER_RIGHT == 128
    workspace = _map_with_label()
    status = workspace.editing_status()
    features = workspace.viewport((0, -1e6, 1e6, 1e6), limit=3000)["features"]
    feature = next(f for f in features if f["code"] == "5310")
    workspace.set_label_leader(feature["id"], 2, True, [0, 0], True,
                               document_token=status["documentToken"],
                               revision=status["revision"])
    entry = workspace._lookup[feature["id"]].obj
    record = next(r for r in (parse_label_record(line) for line in
                              workspace._doc.lines[entry.start:entry.end])
                  if r and r["slot"] == 2)
    assert record["flags"] & 64 and record["leader"] == "left"
