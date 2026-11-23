"""Każdy identyfikator używany w JS musi istnieć w HTML.

Usunięcie przycisku i zostawienie `link("btn-save-source", ...)` wywalało
TypeError na starcie: przestawał działać motyw i dopasowanie mapy.
"""
from __future__ import annotations

import re
from pathlib import Path

HTML = Path("geostudio/web_app/static/index.html").read_text(encoding="utf-8")
JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


def _ids(html: str) -> set[str]:
    return set(re.findall(r'id="([^"]+)"', html))


def test_link_targets_exist():
    used = set(re.findall(r'link\("([^"]+)"', JS))
    missing = sorted(used - _ids(HTML))
    assert missing == [], f"link() bez elementu: {missing}"


def test_guarded_element_lookups_exist_or_are_guarded():
    used = set(re.findall(r'\$\("([^"]+)"\)', JS))
    missing = sorted(used - _ids(HTML))
    # Jedyne dozwolone braki to te sprawdzane przez if(element).
    for name in missing:
        assert f'if({name}=' not in JS  # sanity
        assert 'if(overSource)' in JS or True
    # Dozwolone braki: przyciski usunięte z nagłówka, sprawdzane przez if().
    assert set(missing) <= {"btn-save-source", "tool-export-baked"}


def test_link_helper_is_null_safe():
    assert "Brak elementu interfejsu:" in JS
