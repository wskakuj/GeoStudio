"""Własny kod linii i rodzaje linii (przerywana, kropkowana itd.)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from geostudio.web_app.data import PreviewWorkspace  # noqa: E402

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
HTML = Path("geostudio/web_app/static/index.html").read_text(encoding="utf-8")
MAP = Path("/scratch/input/02_BYSŁAWEK.MAP")


def _workspace():
    if not MAP.exists():
        pytest.skip("brak mapy testowej")
    workspace = PreviewWorkspace()
    workspace.load_map(MAP.read_bytes(), "02.MAP")
    return workspace


def _create_line(workspace, code="7777"):
    status = workspace.editing_status()
    operation = {"action": "create_line", "code": code,
                 "points": [[626170.0, 430950.0], [626200.0, 430990.0]],
                 "fields": {}}
    preview = workspace.preview_geometry_operation(
        operation, document_token=status["documentToken"],
        revision=status["revision"])
    return workspace.apply_geometry_operation(
        operation, document_token=status["documentToken"],
        revision=status["revision"], preview_key=preview["previewKey"])


def test_own_code_can_be_used_for_a_new_line():
    workspace = _workspace()
    result = _create_line(workspace, "7777")
    assert result["createdUids"]
    features = workspace.viewport((0, -1e6, 1e6, 1e6), limit=3000)["features"]
    assert any(f["code"] == "7777" for f in features)


def test_non_numeric_code_is_rejected():
    workspace = _workspace()
    status = workspace.editing_status()
    with pytest.raises(ValueError, match="liczb"):
        workspace.preview_geometry_operation(
            {"action": "create_line", "code": "linia",
             "points": [[626170.0, 430950.0], [626200.0, 430990.0]],
             "fields": {}},
            document_token=status["documentToken"], revision=status["revision"])


def test_dash_is_stored_per_object():
    workspace = _workspace()
    uid = _create_line(workspace)["createdUids"][0]
    status = workspace.editing_status()
    workspace.set_line_dash(uid, [8, 4], document_token=status["documentToken"],
                            revision=status["revision"])
    features = workspace.viewport((0, -1e6, 1e6, 1e6), limit=3000)["features"]
    line = next(f for f in features if f["code"] == "7777")
    assert line["style"]["dash"] == [8.0, 4.0]


def test_dash_pattern_is_validated():
    workspace = _workspace()
    uid = _create_line(workspace)["createdUids"][0]
    status = workspace.editing_status()
    with pytest.raises(ValueError):
        workspace.set_line_dash(uid, [8], document_token=status["documentToken"],
                                revision=status["revision"])


def test_ui_offers_custom_code_and_styles():
    assert '<input id="line-code" type="text" list="line-code-list"' in HTML
    assert 'id="line-style"' in HTML
    for style in ("dashed", "dotted", "dashdot", "dashdotdot", "longdash"):
        assert f"{style}:[" in JS
    assert "applyLineStyle(res.createdUids[0],lineDash);" in JS
