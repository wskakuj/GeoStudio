"""Regression checks for the expanded WMS catalogue and the stable presets."""
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import urlsplit
import subprocess
import shutil

import pytest
from fastapi.testclient import TestClient

from geostudio.web_app import underlay_wms as wms
from geostudio.web_app.server import create_app

STATIC = Path(wms.__file__).parent / "static"


class CatalogParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inside = False
        self.options = {}
        self.groups = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and "src" in attrs:
            self.scripts.append(attrs["src"])
        if tag == "select":
            self.inside = attrs.get("id") == "underlay-preset"
        if self.inside and tag == "optgroup":
            self.groups.append({"label": attrs["label"], "options": []})
        if self.inside and tag == "option":
            assert attrs["value"] not in self.options
            self.options[attrs["value"]] = attrs.get("data-url", "")
            self.groups[-1]["options"].append({
                "value": attrs["value"], "url": attrs.get("data-url", ""), "text": "",
            })

    def handle_data(self, data):
        if self.inside and self.groups and self.groups[-1]["options"]:
            self.groups[-1]["options"][-1]["text"] += data

    def handle_endtag(self, tag):
        if tag == "select":
            self.inside = False


def test_catalog_is_complete_and_frontend_matches():
    parser = CatalogParser()
    parser.feed((STATIC / "index.html").read_text(encoding="utf-8"))
    assert len(wms.PRESETS) == 95
    assert len(wms.CATALOG_PRESETS) == 87
    assert len([key for key in wms.PRESETS if key.startswith("bdl_")]) == 13
    assert parser.options == {key: url for key, (_, url) in wms.PRESETS.items()}
    assert len(set(parser.options.values())) == len(parser.options)
    for key, url in parser.options.items():
        if key != "custom":
            assert urlsplit(url).scheme == "https"
            assert urlsplit(url).hostname in {
                "mapy.geoportal.gov.pl", "integracja.gugik.gov.pl",
                "mapserver.bdl.lasy.gov.pl",
            }


def test_legacy_formats_and_new_transparent_overlays():
    assert wms.WMTS_PRESETS == {"standard_wmts", "high_wmts"}
    assert wms.TIME_PRESETS == {"standard_time", "high_time"}
    assert wms._attempts_for("standard") == wms.ORTO_ATTEMPTS
    assert wms._attempts_for("kieg")[0] == ("1.1.1", "image/png", True)
    for key in wms.CATALOG_PRESETS:
        assert wms._attempts_for(key)[0] == ("1.1.1", "image/png", True)
        assert wms._preset(key) == wms.PRESETS[key][1]


def test_bdl_layers_are_loaded_only_on_request(monkeypatch):
    calls = []
    xml = b"""<WMS_Capabilities version="1.3.0"><Capability>
      <Layer><CRS>EPSG:2180</CRS><Layer><Name>0</Name>
      <Title>Forest</Title></Layer></Layer></Capability></WMS_Capabilities>"""

    def fake_download(url, max_bytes):
        calls.append(url)
        return xml

    monkeypatch.setattr(wms, "_download", fake_download)
    wms.clear_cache()
    try:
        assert calls == []
        response = wms.list_layers("bdl_basic")
        assert response["layers"] == [{"id": "0", "title": "Forest", "epsg": [2180]}]
        assert len(calls) == 1
        assert calls[0].startswith(wms.PRESETS["bdl_basic"][1])
        assert wms.list_layers("bdl_basic") == response
        assert len(calls) == 1
    finally:
        wms.clear_cache()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_search_ignores_polish_diacritics_and_filters_groups():
    module = str(STATIC / "wms_catalog.js")
    code = """
const assert = require('node:assert/strict');
const {matches} = require(process.argv[1]);
assert(matches('Lasy', 'Obwody łowieckie', 'bdl_hunting', '', 'Lasy', 'obwody lowieckie'));
assert(!matches('Lasy', 'Obwody łowieckie', 'bdl_hunting', '', 'Ortofotomapy', ''));
assert(!matches('Lasy', 'Obwody łowieckie', 'bdl_hunting', '', '', 'drzewostany'));
assert(matches('Mapa zasadnicza', 'Uzbrojenie terenu (KIUT)', 'gugik_kiut', '', '', 'KIUT'));
"""
    subprocess.run(["node", "-e", code, module], check=True)



@pytest.mark.parametrize("multi_document", [False, True])
def test_catalog_script_is_served_in_both_editor_modes(multi_document):
    # A file can be packaged on disk but still return 404 when requested by
    # WebView2. Check the actual HTTP route, not just the file contents.
    client = TestClient(create_app(multi_document=multi_document))
    response = client.get("/wms_catalog.js")
    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0] == "text/javascript"
    assert response.text == (STATIC / "wms_catalog.js").read_text(encoding="utf-8")


def test_all_editor_scripts_are_served():
    client = TestClient(create_app())
    parser = CatalogParser()
    parser.feed(client.get("/").text)
    assert "/wms_catalog.js" in parser.scripts
    for url in parser.scripts:
        response = client.get(url)
        assert response.status_code == 200, url
        assert "javascript" in response.headers["content-type"], url


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_served_catalog_filters_real_options():
    client = TestClient(create_app())
    parser = CatalogParser()
    parser.feed(client.get("/").text)
    response = client.get("/wms_catalog.js")
    assert response.status_code == 200
    script = Path(__file__).with_suffix(".cjs")
    run = subprocess.run(
        ["node", str(script)], input=json.dumps({
            "groups": parser.groups, "script": response.text,
        }), text=True, encoding="utf-8", capture_output=True, timeout=15,
    )
    assert run.returncode == 0, run.stdout + run.stderr
