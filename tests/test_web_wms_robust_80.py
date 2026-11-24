"""Odporność okna WMS: brak cichych błędów, działające krycie, czytelny status."""
from __future__ import annotations

from pathlib import Path

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


def test_apply_underlay_cannot_die_silently():
    assert "function applyUnderlay(){\n    try{applyUnderlayUnsafe();}" in JS
    assert 'catch(error){inform("Nie udało się dodać podkładu: ' in JS


def test_dialog_stays_open_to_show_status():
    """Zamykanie okna ukrywało status i błąd Geoportalu."""
    assert 'const dialog=$("underlay-dialog");\n    if(dialog?.open)dialog.close();' not in JS
    assert "Krycie i widoczność ustawisz w panelu Rastry." in JS


def test_opacity_updates_every_wms_entry():
    start = JS.index('$("underlay-opacity").addEventListener("input"')
    block = JS[start:start + 420]
    assert 'for(const item of underlays)if(item.kind!=="raster")item.opacity=value;' in block


def test_entries_get_a_kind():
    assert 'item={kind:"wms",id:"wms"+(++underlaySerial)' in JS
    assert 'item.kind="wms";' in JS


def test_changing_only_the_date_updates_the_entry():
    start = JS.index("function applyUnderlayUnsafe(){")
    block = JS[start:start + 2600]
    assert "item.time=chosenTime;" in block


def test_last_error_is_visible_in_the_panel():
    # Plik użytkownika trzyma błąd w item.error — pole jest pokazywane w panelu.
    assert 'item.error=error.message||"Błąd pobierania";' in JS
    assert 'status:item.error?("Błąd: "+item.error):' in JS
    assert 'item.error="";' in JS
