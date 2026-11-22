"""Znaczek wersji w nagłówku i endpoint /api/version."""
from __future__ import annotations

from fastapi.testclient import TestClient

from geostudio.web_app.server import create_app


def test_version_endpoint_requires_token_and_returns_version():
    app = create_app()
    client = TestClient(app)
    assert client.get("/api/version").status_code in (401, 403)
    ok = client.get("/api/version", headers={"X-GeoStudio-Token": app.state.api_token})
    assert ok.status_code == 200
    version = ok.json()["version"]
    assert version and version[0].isdigit()


def test_header_has_clickable_version_badge():
    html = TestClient(create_app()).get("/").text
    assert 'id="app-version"' in html
    assert "version-badge" in html
    assert "Sprawdź aktualizacje" in html or "sprawdzić aktualizacje" in html


def test_badge_is_green_then_yellow_in_styles():
    css = TestClient(create_app()).get("/styles.css").text
    assert ".version-badge" in css
    assert ".version-badge.is-stale" in css
