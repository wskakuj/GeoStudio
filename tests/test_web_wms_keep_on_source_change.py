"""Zmiana źródła WMS nie usuwa wczytanych podkładów."""
from __future__ import annotations

from pathlib import Path

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


def test_changing_preset_does_not_remove_underlays():
    start = JS.index('$("underlay-preset").addEventListener("change"')
    block = JS[start:start + 420]
    assert "removeUnderlay" not in block
    assert "loadUnderlayLayers()" in block
    assert "showWmsPresetAddress()" in block


def test_remove_button_clears_the_whole_stack():
    # link() przekazuje obiekt zdarzenia, więc bez opakowania usuwanie
    # pojedynczej warstwy nie działało wcale.
    assert 'link("underlay-remove",()=>removeUnderlay());' in JS


def test_new_layer_can_be_added_from_another_service():
    # Różny preset = nowa pozycja na stosie.
    assert "entry.preset===preset&&entry.layer===layer&&" in JS
    assert "underlays.push(item);" in JS
