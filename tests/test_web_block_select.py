"""Zaznaczanie po kodzie: cała mapa i fragment (sekcja „Blok”)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest  # noqa: E402

from geostudio.web_app.data import PreviewWorkspace  # noqa: E402

MAP = Path("/scratch/work/userzip/geostudio-test/MOKRA WIEŚ.MAP")


def _workspace():
    if not MAP.exists():
        pytest.skip("brak mapy testowej")
    workspace = PreviewWorkspace()
    workspace.load_map(MAP.read_bytes(), "M.MAP")
    return workspace


def test_select_all_with_code():
    workspace = _workspace()
    result = workspace.select_by_code("5310")
    assert result["count"] > 0
    assert result["code"] == "5310"
    assert len(result["ids"]) == result["count"]


def test_select_only_inside_rectangle():
    workspace = _workspace()
    everything = workspace.select_by_code("5310")["count"]
    part = workspace.select_by_code("5310", [668000, -517000, 672000, -513000])
    assert 0 < part["count"] < everything


def test_select_rejects_bad_code():
    workspace = _workspace()
    with pytest.raises(ValueError):
        workspace.select_by_code("")
    with pytest.raises(ValueError):
        workspace.select_by_code("abc")


def test_ui_has_block_section():
    html = Path("geostudio/web_app/static/index.html").read_text(encoding="utf-8")
    js = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
    assert 'id="block-code"' in html
    assert 'id="block-select-all"' in html
    assert 'id="block-select-rect"' in html
    assert "async function selectByCode(" in js
    assert "startBlockRectangle" in js
