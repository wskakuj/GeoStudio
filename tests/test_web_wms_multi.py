"""Wiele podkładów WMS naraz."""
from __future__ import annotations

from pathlib import Path

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


def test_underlay_stack_exists():
    assert "const underlays = [];" in JS
    assert "function activeUnderlay()" in JS
    assert "function underlayTitle(item)" in JS


def test_enabling_adds_a_layer_instead_of_replacing():
    # Ten sam preset+warstwa+EPSG odświeża istniejący wpis, inny dodaje nowy.
    assert "let item=underlays.find(entry=>entry.preset===preset&&entry.layer===layer&&" in JS
    assert "underlays.push(item);" in JS


def test_all_layers_are_painted_and_listed():
    assert "for(const item of underlays){" in JS
    assert "for(const item of underlays)\n      items.push({kind:\"wms\"" in JS


def test_single_layer_can_be_removed():
    assert "function removeUnderlay(id){" in JS
    assert "removeUnderlay(item.id);" in JS
    assert "underlays.splice(index,1);" in JS
