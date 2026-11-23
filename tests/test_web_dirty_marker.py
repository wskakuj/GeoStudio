"""Znacznik „Niezapisane zmiany w pamięci” musi gasnąć po zapisie kopii."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from geostudio.web_app.data import PreviewWorkspace  # noqa: E402

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
MAP = Path("/scratch/input/02_BYSŁAWEK.MAP")


def test_marker_text_explains_the_state():
    assert '"Niezapisane zmiany w pamięci":"Oryginał chroniony"' in JS


def test_status_is_refreshed_after_saving_the_copy():
    start = JS.index("async function downloadMapCopy() {")
    block = JS[start:start + 1200]
    assert 'await api("/api/edit/status")' in block
    assert "updateEditState(status);" in block


def test_server_clears_dirty_after_mark_saved():
    if not MAP.exists():
        pytest.skip("brak mapy testowej")
    workspace = PreviewWorkspace()
    workspace.load_map(MAP.read_bytes(), "02.MAP")
    assert workspace.editing_status()["dirty"] is False
    status = workspace.editing_status()
    operation = {"action": "create", "code": "5310",
                 "points": [[626100.0, 430900.0], [626120.0, 430900.0],
                            [626120.0, 430920.0], [626100.0, 430920.0]],
                 "fields": {"A1": "1a"}, "clipRasterOverlap": False}
    preview = workspace.preview_object_operation(
        operation, document_token=status["documentToken"],
        revision=status["revision"])
    status = workspace.editing_status()
    workspace.apply_object_operation(
        operation, preview_key=preview["previewKey"],
        document_token=status["documentToken"], revision=status["revision"])
    assert workspace.editing_status()["dirty"] is True
    workspace.mark_saved()
    assert workspace.editing_status()["dirty"] is False
