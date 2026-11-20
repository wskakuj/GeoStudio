"""Full MAP attribute filtering, selection safeguards and native file picker."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.geomap import GeoMap
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.native_picker import (
    NativeMapPicker, read_last_map_directory, save_last_map_directory
)
from geostudio.web_app.server import create_app


def source():
    return (MapBuilder(ext=(5000, 0, 0, 500, 500))
        .object("5310", "A", {"A1": "b", "A2": "Bud. Łódź"},
                [(0, 0), (0, 10), (10, 10), (10, 0)])
        .object("5310", "B", {"A1": "b", "A2": "Garaż"},
                [(15, 0), (15, 10), (25, 10), (25, 0)])
        .object("5310", "C", {"A1": "g", "A2": "Budynek"},
                [(30, 0), (30, 10), (40, 10), (40, 0)])
        .object("5220", "D", {"A1": "R", "A2": "Łódź"},
                [(0, 50), (0, 60), (10, 60), (10, 50)])
        .object("5230", "E", {"A1": "dr", "A2": "droga"},
                [(15, 50), (15, 60), (25, 60), (25, 50)])
        .object("5216", "F", {"A2": "144/2"},
                [(40, 50), (40, 60), (50, 60), (50, 50)])
        .build())


def load():
    ws = PreviewWorkspace()
    ws.load_map(source(), "test.MAP")
    return ws


def test_code_only_finds_all_same_code_objects_independent_of_viewport():
    ws = load()
    assert ws.viewport((0, -10, 10, 0))["total"] == 1
    result = ws.select_by_attributes(code="5310")
    assert result["ids"] == ["f0", "f1", "f2"]
    assert result["count"] == 3
    assert result["criteria"]["code"] == "5310"
    assert result["documentToken"] == ws.editing_status()["documentToken"]


def test_a1_and_a2_combinations_exact_and_contains():
    ws = load()
    assert ws.select_by_attributes(code="5310", a1="b")["ids"] == ["f0", "f1"]
    assert ws.select_by_attributes(code="5310", a1="b", a2="Garaż")["ids"] == ["f1"]
    assert ws.select_by_attributes(code="5310", a2="ŁÓDŹ",
                                   match="contains")["ids"] == ["f0"]
    assert ws.select_by_attributes(a2="ŁÓDŹ", match="contains")["ids"] == [
        "f0", "f3"]
    assert ws.select_by_attributes(a2="ŁÓDŹ", match="exact")["ids"] == ["f3"]
    assert ws.select_by_attributes(code="5230", a1="dr")["ids"] == ["f4"]
    assert ws.select_by_attributes(code="5310", a1="R")["ids"] == []


@pytest.mark.parametrize("filters", [
    {}, {"code":""}, {"code":"abc"}, {"code":"5310","match":"regex"},
    {"code":"5310","a2":55}, {"code":"5310","a1":"x"*161},
])
def test_invalid_selection_filters_are_rejected(filters):
    with pytest.raises(ValueError):
        load().select_by_attributes(**filters)


def test_selection_maximum_explicit_error_not_partial(monkeypatch):
    from geostudio.web_app import data
    monkeypatch.setattr(data, "MAX_SELECTED_FEATURES", 2)
    with pytest.raises(ValueError, match="50 000"):
        load().select_by_attributes(code="5310")


def test_selection_does_not_mutate_map_history_or_lines():
    ws = load()
    original = ws.export_copy(ws.editing_status()["documentToken"])[1]
    before = ws.editing_status()
    ws.select_by_attributes(code="5310", a1="b")
    ws.select_by_attributes(code="5230")
    assert ws.export_copy(ws.editing_status()["documentToken"])[1] == original
    assert ws.editing_status() == before
    assert GeoMap(original).checksum_valid


def test_authenticated_http_selection_and_invalid_queries():
    app = create_app()
    with TestClient(app) as client:
        auth = {"X-GeoStudio-Token": app.state.api_token}
        opened = client.post("/api/map", content=source(),
                             headers={**auth, "X-Map-Name":"test.MAP"})
        assert opened.status_code == 200
        denied = client.get("/api/select", params={"code":"5310"})
        assert denied.status_code == 403
        response = client.get("/api/select", headers=auth, params={
            "code":"5310", "a1":"b", "match":"exact"})
        assert response.status_code == 200, response.text
        assert response.json()["ids"] == ["f0", "f1"]
        assert response.json()["revision"] == 0
        assert client.get("/api/select", headers=auth).status_code == 400
        assert client.get("/api/select", headers=auth,
                          params={"code":"5310","match":"invalid"}).status_code == 400


def test_native_picker_remembers_previous_folder_across_new_instances(
        tmp_path, monkeypatch):
    # A fake Tk dialog tests native folder persistence on headless CI.
    folder = tmp_path / "Polskie mapy"
    folder.mkdir()
    path = folder / "MOKRA WIEŚ.MAP"
    path.write_bytes(source())
    prefs = tmp_path / "settings" / "preferences.json"
    calls = []
    selected = [str(path), ""]

    class Root:
        def withdraw(self): pass
        def attributes(self, *args): pass
        def update(self): pass
        def destroy(self): pass
    def askopenfilename(**kwargs):
        calls.append(kwargs)
        return selected.pop(0)
    tkinter_mock = SimpleNamespace(
        Tk=Root,
        filedialog=SimpleNamespace(askopenfilename=askopenfilename),
    )
    monkeypatch.setitem(sys.modules, "tkinter", tkinter_mock)

    bridge = NativeMapPicker(PreviewWorkspace(), settings=prefs)
    result = bridge.open_map()
    assert result["cancelled"] is False
    assert result["metadata"]["name"] == "MOKRA WIEŚ.MAP"
    assert result["metadata"]["objectCount"] == 6
    assert "last_map_directory" not in result["metadata"]
    assert str(folder) not in str(result)
    assert calls[0]["initialdir"] == str(Path.home())
    assert read_last_map_directory(prefs) == str(folder)
    assert json.loads(prefs.read_text(encoding="utf-8")) == {
        "last_map_directory": str(folder)
    }

    other = NativeMapPicker(PreviewWorkspace(), settings=prefs)
    assert other.open_map() == {"cancelled": True}
    assert calls[1]["initialdir"] == str(folder)

def test_pywebview_js_bridge_has_no_native_window_or_workspace(tmp_path):
    """Prevent recursive WinForms COM inspection by the JS API."""
    workspace = PreviewWorkspace()
    picker = NativeMapPicker(workspace, settings=tmp_path / "preferences.json")
    exposed = [name for name in dir(picker) if not name.startswith("_")]
    assert exposed == ["open_libraries", "open_map", "restore_recovery",
                       "save_baked_map", "save_base_map", "save_generated_export", "save_map",
                       "save_recovery", "save_tiled_export"]
    assert callable(picker.open_map)
    assert picker._workspace is workspace
    assert not hasattr(picker, "_window")
    assert not hasattr(picker, "__dict__")
    with pytest.raises(AttributeError):
        picker.window = object()
    with pytest.raises(AttributeError):
        picker.workspace = workspace

def test_desktop_window_not_exported_to_js_api():
    from geostudio.web_app import __main__ as entry
    import inspect
    source_text = inspect.getsource(entry.main)
    assert "js_api=native_picker" in source_text
    assert "native_picker._window = window" not in source_text
    assert "native_picker.window = window" not in source_text

def test_bad_map_does_not_replace_last_folder(tmp_path, monkeypatch):
    previous = tmp_path / "old"
    previous.mkdir()
    prefs = tmp_path / "prefs.json"
    save_last_map_directory(prefs, previous)
    bad = tmp_path / "broken.MAP"
    bad.write_bytes(b"not a GEO-MAP map")
    monkeypatch.setattr(NativeMapPicker, "_choose_path",
                        lambda self: str(bad))
    picker = NativeMapPicker(PreviewWorkspace(),settings=prefs)
    with pytest.raises(ValueError):
        picker.open_map()
    assert read_last_map_directory(prefs) == str(previous)


def test_native_picker_failure_gives_clickable_fallback(tmp_path, monkeypatch):
    def fail(self):
        raise RuntimeError("No native picker")
    monkeypatch.setattr(NativeMapPicker, "_choose_path", fail)
    picker = NativeMapPicker(PreviewWorkspace(), settings=tmp_path / "prefs.json")
    with pytest.raises(RuntimeError, match="Z dysku"):
        picker.open_map()

def test_web_buttons_and_browser_fallback_exist():
    static = Path(__file__).resolve().parents[1] / "geostudio/web_app/static"
    html = (static / "index.html").read_text(encoding="utf-8")
    js = (static / "map.js").read_text(encoding="utf-8")
    for element in ["tool-advanced-select", "select-dialog", "select-code",
                    "select-a1", "select-a2", "select-match", "select-action",
                    "select-apply", "select-clear"]:
        assert 'id="'+element+'"' in html
    assert 'ev.key.toLowerCase()==="h"' in js
    assert 'window.pywebview.api?.open_map' in js
    assert 'id="btn-open-direct"' in html
    assert 'for="file-map"' in html
    assert 'if(window.pywebview)' in js
    assert 'window.pywebview.api?.open_map' in js
    assert 'window.showOpenFilePicker' in js
    assert 'id:"geostudio-map-folder"' in js
    assert "state.pinned=matches" in js
    assert "state.tool===\"nodes\"" in js
