"""Numer oddziału 6900: okno przed kliknięciem, zapis i edycja dwuklikiem."""
from __future__ import annotations

from pathlib import Path

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
HTML = Path("geostudio/web_app/static/index.html").read_text(encoding="utf-8")
DATA = Path("geostudio/web_app/data.py").read_text(encoding="utf-8")


def test_server_accepts_font_size_for_numbers():
    # Bez tego zapis elementu 6900 kończył się „Nieprawidłowy element arkusza”
    # i numer nigdy nie pojawiał się na mapie.
    assert 'set(item)-{"runs","angle","fontSize"}' in DATA


def test_tool_opens_the_dialog_before_placing():
    assert "function openNumberDialog(editing){" in JS
    assert 'if(kind==="compartment"){' in JS
    assert "openNumberDialog(null);" in JS


def test_dialog_choice_is_used_when_clicking_the_map():
    assert "pendingNumber={text,size};" in JS
    assert "const chosen=pendingNumber||{text:\"\",size:12};" in JS


def test_double_click_edits_number_and_size():
    assert "openNumberDialog(item);" in JS
    assert 'if(editing){' in JS
    assert "Zmieniono numer na " in JS


def test_dialog_labels_match_the_new_flow():
    assert "Numer oddziału · 6900" in HTML
    assert "Dalej — wskaż miejsce" in HTML
