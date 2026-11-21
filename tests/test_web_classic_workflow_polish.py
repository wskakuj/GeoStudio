"""User workflow refinements: 5310 scope, toolbar and export cleanup."""
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.documents import MAX_DOCUMENTS
from geostudio.web_app.server import create_app

ROOT = Path(__file__).resolve().parents[1] / "geostudio" / "web_app"


def test_5310_audit_endpoint_and_default_stroke():
    raw = (MapBuilder()
           .object("5310", "A", {"A1": "A"}, [(0,0),(0,10),(10,10),(10,0),(0,0)])
           .object("5310", "B", {"A1": "B"}, [(0,0),(0,10),(10,10),(10,0),(0,0)])
           .object("5220", "C", {"A1": "C"}, [(20,0),(20,10),(30,10),(30,0),(20,0)])
           .object("5220", "D", {"A1": "D"}, [(20,0),(20,10),(30,10),(30,0),(20,0)])
           .build())
    workspace = PreviewWorkspace()
    meta = workspace.load_map(raw, "audit.MAP")
    app = create_app(workspace)
    with TestClient(app) as client:
        response = client.get("/api/topology/audit",
            headers={"X-GeoStudio-Token": app.state.api_token},
            params={"documentToken": meta["documentToken"], "revision": meta["revision"]})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["checked"] == 2
        assert result["detected"] >= 1
        assert all(issue["code"] == "5310" for issue in result["issues"])
    style = workspace.outline_settings("5310")
    assert style["stroke"] == "#FF0000"
    assert style["strokeWidth"] == 3
    assert not style["custom"]
    assert workspace.outline_settings("5220")["strokeWidth"] != 3


def test_workflow_ui_and_export_requirements():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "map.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
    pdf = (ROOT / "print_layout.py").read_text(encoding="utf-8")
    assert MAX_DOCUMENTS == 10
    assert 'state.tool==="select"&&ev.button===2' in js
    assert 'canvas.setPointerCapture(ev.pointerId)' in js
    for name in ("float-line","float-draw","float-snap"):
        assert 'id="'+name+'"' in html
        assert 'link("'+name+'"' in js
    assert 'state.expandedForest' in js
    assert 'forest-classes-list' in js
    assert 'layer-chevron' in css
    assert 'data-map-bg="#FFFFFF"] {--swatch:#FFFFFF;}' in css
    assert 'id="layout-orientation-row" hidden' in html
    assert 'if(!state.meta||!state.exportAreaPicking)return;' in js
    assert 'X/Y GEO-MAP • bez transformacji współrzędnych' not in js
    assert 'GEO-MAP X/Y  |  Wektorowy PDF' not in pdf
    assert 'Wczytaj prawdziwy plik' not in html
    assert 'Odczyt geometrii GEO-MAP' not in html
    assert '<span>HTML5 Canvas</span>' not in html
