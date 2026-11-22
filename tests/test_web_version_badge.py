"""Znaczek wersji w nagłówku i endpoint /api/version."""
from __future__ import annotations

from fastapi.testclient import TestClient

from geostudio.web_app.server import create_app


def test_version_endpoint_returns_version_without_document_header():
    """/version jest poza /api: numer wersji nie jest tajemnicą, a nagłówek
    zakładek potrzebuje go przed otwarciem jakiejkolwiek mapy."""
    app = create_app()
    response = TestClient(app).get("/version")
    assert response.status_code == 200
    version = response.json()["version"]
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


def test_version_works_in_tab_mode_without_document_header():
    """Nagłówek zakładek nie ma identyfikatora dokumentu, a wersja jest wspólna."""
    app = create_app(multi_document=True)
    client = TestClient(app)
    response = client.get("/version", headers={"X-GeoStudio-Token": app.state.api_token})
    assert response.status_code == 200
    assert response.json()["version"]


def test_tabs_header_has_the_badge():
    html = TestClient(create_app(multi_document=True)).get("/").text
    assert 'id="app-version"' in html
    assert "version-badge" in html
