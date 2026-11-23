"""„Utwórz linię” działa od razu, bez osobnego kroku „Sprawdź linię”."""
from __future__ import annotations

from pathlib import Path

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
HTML = Path("geostudio/web_app/static/index.html").read_text(encoding="utf-8")


def test_line_form_previews_and_applies_in_one_step():
    assert "async function applyOrPreviewGeometry(which, ev) {" in JS
    assert '$("line-form").addEventListener("submit",ev=>applyOrPreviewGeometry("line",ev));' in JS


def test_create_button_is_always_clickable():
    assert 'id="line-apply" type="submit" class="button primary">Utwórz linię' in HTML
    assert 'id="line-apply" type="submit" class="button primary" disabled' not in HTML
    assert '$("line-apply").disabled=false;' in JS


def test_preview_button_still_available():
    assert 'link("line-preview",()=>previewGeometryForm("line"));' in JS
