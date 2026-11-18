"""The WMS layer picker must be a dropdown populated by GetCapabilities."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from geostudio.app import GeoStudioWindow
from geostudio.wms_qt import WMSDialog
from geostudio.wms_service import parse_capabilities, google_earth_browser_url


XML = b"""<?xml version="1.0"?>
<WMS_Capabilities xmlns="http://www.opengis.net/wms" version="1.3.0">
  <Capability><Layer><Title>Mapa</Title><CRS>EPSG:2180</CRS>
    <Layer><Name>ortofoto</Name><Title>Ortofotomapa</Title></Layer>
    <Layer><Name>granice</Name><Title>Granice</Title></Layer>
  </Layer></Capability>
</WMS_Capabilities>"""


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def wms(app):
    window = GeoStudioWindow()
    dialog = WMSDialog(window)
    yield dialog
    dialog.close()
    window.close()


def test_wms_uses_dropdown_not_text_field(wms):
    assert not wms.layer_selector.isEditable()
    assert not wms.layer_selector.isEnabled()
    assert not wms.map_button.isEnabled()
    assert "Pobierz warstwy" in wms.layer_selector.itemText(0)


def test_getcapabilities_populates_actual_selectable_layers(wms, monkeypatch):
    requested = []
    monkeypatch.setattr(wms, "_request", lambda url, callback, **kw: (
        requested.append((url, kw)), callback(XML)))
    wms.fetch_layers()
    assert requested and requested[0][1]["fetching_layers"]
    assert wms.layer_selector.isEnabled()
    assert wms.layer_selector.count() == 2
    assert wms.layer_selector.itemData(0) == "ortofoto"
    assert wms.layer_selector.itemText(0) == "Ortofotomapa  (ortofoto)"
    assert wms.layer_selector.itemData(1) == "granice"
    assert wms.map_button.isEnabled()
    assert wms._selected_layer().name == "ortofoto"
    wms.layer_selector.setCurrentIndex(1)
    assert wms._selected_layer().name == "granice"


def test_empty_capabilities_display_clear_message(wms, monkeypatch):
    empty = b"<WMS_Capabilities><Capability><Layer><Title>Brak warstw</Title></Layer></Capability></WMS_Capabilities>"
    monkeypatch.setattr(wms, "_request", lambda url, callback, **kw: callback(empty))
    wms.fetch_layers()
    assert not wms.layer_selector.isEnabled()
    assert not wms.map_button.isEnabled()
    assert "nie udostepnil" not in wms.message.text().lower()  # Polish diacritics preserved
    assert "nie udostępnił" in wms.message.text().lower()
    assert wms._selected_layer() is None


def test_ogc_service_exception_is_not_misreported_as_zero_layers():
    error = b'<ServiceExceptionReport><ServiceException code="RequestNotAllowed">No permission</ServiceException></ServiceExceptionReport>'
    with pytest.raises(ValueError, match="No permission"):
        parse_capabilities(error)


def test_earth_reference_opens_official_site_without_api_key():
    from pyproj import Transformer
    e, n = Transformer.from_crs("EPSG:4326", "EPSG:2180", always_xy=True).transform(
        21.011, 52.229)
    url = google_earth_browser_url(n, e, 2180)
    assert url.startswith("https://earth.google.com/web/search/52.229")
    assert "21.011" in url
    assert "key=" not in url
    with pytest.raises(ValueError):
        google_earth_browser_url(n, e, 12345)
