"""First edit milestone: reversible attribute updates without touching original MAP."""
from __future__ import annotations

import hashlib
import re

import pytest
from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.geomap import GeoMap
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app


@pytest.fixture
def source_map():
    return (MapBuilder(ext=(5000, 0, 0, 150, 150))
            .raw(";# Unknown vendor metadata — preserve bytes")
            .object("5310", "BUILDING-1",
                    {"A1": "b", "A2": "Budynek", "A3": "Przed"},
                    [(0, 0), (0, 10), (10, 10), (10, 0)])
            .object("5230", "FOREST-1",
                    {"A1": "LsV", "A2": "LsV"},
                    [(30, 30), (30, 40), (40, 40), (40, 30)])
            .build())


@pytest.fixture
def workspace(source_map):
    instance = PreviewWorkspace()
    instance.load_map(source_map, "MOKRA WIEŚ.MAP")
    return instance


def _token(workspace):
    status = workspace.editing_status()
    return {"document_token": status["documentToken"],
            "revision": status["revision"]}


def test_two_fields_are_one_atomic_history_step(workspace, source_map):
    old = source_map
    before = workspace.details("f0")
    # A4–A6 are the descriptive fields added for the 5310 outline; the parser
    # materialises them as empty strings, so they are editable from the start.
    assert before["editableFields"] == ["A1", "A2", "A3", "A4", "A5", "A6"]
    assert not workspace.editing_status()["dirty"]
    result = workspace.edit_fields(
        "f0", {"A2": "Budynek mieszkalny", "A3": "Żółć"}, **_token(workspace))
    assert result["changed"] is True
    assert result["dirty"] is True
    assert result["canUndo"] and not result["canRedo"]
    assert result["revision"] == 1
    assert result["object"]["fields"]["A3"] == "Żółć"
    exported_name, exported = workspace.export_copy(result["documentToken"])
    assert exported_name == "MOKRA WIEŚ_GeoStudio2_kopia.MAP"
    assert exported != old
    parsed = GeoMap(exported)
    assert parsed.checksum_valid
    assert parsed.declared_lines == len(parsed.lines)
    assert parsed.by_id["BUILDING-1"].fields["A3"] == "Żółć"
    assert parsed.by_id["FOREST-1"].fields["A1"] == "LsV"
    assert b";# Unknown vendor metadata" in exported
    # Attribute edit must not modify any P coordinates.
    assert [(p.x, p.y) for p in parsed.by_id["BUILDING-1"].points] == [
        (p.x, p.y) for p in GeoMap(old).by_id["BUILDING-1"].points]
    undo = workspace.step_history("undo", **_token(workspace))
    assert undo["changed"] and undo["canRedo"]
    assert not undo["dirty"]
    assert workspace.details("f0")["fields"]["A3"] == "Przed"
    redo = workspace.step_history("redo", **_token(workspace))
    assert redo["changed"] and redo["dirty"]
    assert workspace.details("f0")["fields"]["A3"] == "Żółć"
    assert source_map == old


@pytest.mark.parametrize("field,value", [
    ("ID", "change"), ("A7", "no"), ("A9", "spoza listy"),
    ("A1", "nowa\nlinia"), ("A1", "zamknij]"), ("A1", "😀"), ("A1", "x"*513),
])
def test_invalid_updates_are_rejected_without_partial_changes(
        workspace, source_map, field, value):
    before = workspace.export_copy(_token(workspace)["document_token"])[1]
    with pytest.raises(ValueError):
        workspace.edit_fields("f0", {field: value}, **_token(workspace))
    assert workspace.export_copy(_token(workspace)["document_token"])[1] == before
    assert not workspace.editing_status()["canUndo"]


def test_atomic_validation_for_multiple_fields(workspace):
    with pytest.raises(ValueError):
        workspace.edit_fields(
            "f0", {"A1": "Nowe", "A9": "nie ma"}, **_token(workspace))
    assert workspace.details("f0")["fields"]["A1"] == "b"
    assert not workspace.editing_status()["dirty"]


def test_revisions_and_documents_prevent_cross_map_edits(workspace, source_map):
    first = _token(workspace)
    workspace.edit_fields("f0", {"A1": "nowe"}, **first)
    with pytest.raises(RuntimeError):
        workspace.edit_fields("f0", {"A1": "stare"}, **first)
    workspace.load_map(source_map, "Drugi.MAP")
    with pytest.raises(RuntimeError):
        workspace.edit_fields("f0", {"A1": "nie"}, **first)
    with pytest.raises(RuntimeError):
        workspace.export_copy(first["document_token"])
    assert workspace.details("f0")["fields"]["A1"] == "b"


def test_noop_edit_does_not_create_history_entry(workspace):
    result = workspace.edit_fields(
        "f0", {"A1": "b"}, **_token(workspace))
    assert not result["changed"]
    assert not result["dirty"] and not result["canUndo"]


def test_api_downloads_a_new_valid_map_without_writing_server_files(source_map, tmp_path):
    original = tmp_path / "original.MAP"
    original.write_bytes(source_map)
    app = create_app()
    with TestClient(app) as c:
        headers = {"X-GeoStudio-Token": app.state.api_token}
        response = c.post("/api/map", content=original.read_bytes(),
                          headers={**headers, "X-Map-Name": "original.MAP"})
        assert response.status_code == 200
        status = response.json()
        assert status["editingEnabled"] is True
        assert status["readOnly"] is True
        assert status["revision"] == 0
        patch = c.patch("/api/object/f0/fields",
                        headers=headers, json={
                            "documentToken": status["documentToken"],
                            "revision": 0,
                            "changes": {"A2": "Zmieniony", "A1": "B"},
                        })
        assert patch.status_code == 200, patch.text
        assert patch.json()["revision"] == 1
        assert patch.json()["canUndo"]
        stale = c.patch("/api/object/f0/fields", headers=headers,
                        json={"documentToken": status["documentToken"],
                              "revision": 0, "changes": {"A1": "X"}})
        assert stale.status_code == 409
        copy = c.get("/api/export/map", params={
            "documentToken": status["documentToken"]
        }, headers=headers)
        assert copy.status_code == 200
        assert copy.headers["content-disposition"].startswith("attachment;")
        assert "filename*=UTF-8''" in copy.headers["content-disposition"]
        assert GeoMap(copy.content).checksum_valid
        assert GeoMap(copy.content).by_id["BUILDING-1"].fields["A2"] == "Zmieniony"
        assert original.read_bytes() == source_map
        assert sorted(p.name for p in tmp_path.iterdir()) == ["original.MAP"]

        restored = c.post("/api/edit/undo", headers=headers, json={
            "documentToken": status["documentToken"], "revision": 1
        })
        assert restored.status_code == 200
        assert restored.json()["dirty"] is False
        assert c.get("/api/object/f0", headers=headers).json()["fields"]["A1"] == "b"
        repeated = c.post("/api/edit/redo", headers=headers, json={
            "documentToken": status["documentToken"], "revision": 2
        })
        assert repeated.status_code == 200
        assert repeated.json()["dirty"]
        assert c.get("/api/edit/status").status_code == 403


def test_browser_has_real_edit_controls_and_safe_copy_download():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] /
           "geostudio/web_app/static")
    html = (src / "index.html").read_text(encoding="utf-8")
    js = (src / "map.js").read_text(encoding="utf-8")
    for element in ("inspector-edit-form", "tool-undo", "tool-redo",
                    "btn-export", "inspector-edit-toggle"):
        assert f'id="{element}"' in html
    assert '"/api/export/map"' in js
    assert '"/api/export/package"' in js
    assert 'documentToken' in js
    assert 'Ctrl+Z' in js
