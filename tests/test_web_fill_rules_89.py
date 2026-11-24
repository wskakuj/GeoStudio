"""Styl wypełnienia: kod + warunek, kolor i nasycenie."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from geostudio.web_app.data import (  # noqa: E402
    fill_rule_matches, validate_fill_rules)

MAP = Path("/scratch/input/MOKRA_WIEŚ-2.MAP")


def test_validate_accepts_code_only_rule():
    rules = validate_fill_rules([{"code": "5310", "color": "#4FA3D1",
                                  "opacity": 35}])
    assert rules[0]["code"] == "5310"
    assert rules[0]["color"] == "#4FA3D1"
    assert rules[0]["opacity"] == 35


def test_validate_rejects_bad_values():
    with pytest.raises(ValueError):
        validate_fill_rules([{"code": "53", "color": "#FFFFFF"}])
    with pytest.raises(ValueError):
        validate_fill_rules([{"code": "5310", "color": "czerwony"}])
    with pytest.raises(ValueError):
        validate_fill_rules([{"code": "5310", "opacity": 140}])
    with pytest.raises(ValueError):
        validate_fill_rules([{"code": "5310", "field": "A2",
                              "operator": "zawiera", "value": ""}])


def test_matching_by_code_and_condition():
    rule = {"code": "5310", "field": "A2", "operator": "zawiera",
            "value": "Ls", "enabled": True}
    assert fill_rule_matches(rule, "5310", {"A2": "5So120 LsVI"})
    assert not fill_rule_matches(rule, "5310", {"A2": "So80"})
    assert not fill_rule_matches(rule, "5230", {"A2": "Ls"})
    # wielkość liter nie ma znaczenia
    assert fill_rule_matches(rule, "5310", {"A2": "lsvi"})


def test_operators():
    base = {"code": "", "field": "A1", "enabled": True}
    assert fill_rule_matches({**base, "operator": "rowna", "value": "b"},
                             "5310", {"A1": "b"})
    assert fill_rule_matches({**base, "operator": "zaczyna", "value": "L"},
                             "5310", {"A1": "Ls"})
    assert fill_rule_matches({**base, "operator": "konczy", "value": "VI"},
                             "5310", {"A1": "LsVI"})
    assert fill_rule_matches({**base, "operator": "nie_zawiera", "value": "X"},
                             "5310", {"A1": "Ls"})
    # wyłączona reguła nie działa
    assert not fill_rule_matches({**base, "operator": "zawiera",
                                  "value": "L", "enabled": False},
                                 "5310", {"A1": "Ls"})


def test_style_uses_the_rule():
    if not MAP.exists():
        pytest.skip("brak mapy testowej")
    from geostudio.web_app.data import PreviewWorkspace
    workspace = PreviewWorkspace()
    workspace.load_map(MAP.read_bytes(), "MOKRA.MAP")
    workspace.set_fill_rules([{"code": "5310", "color": "#FF0000",
                               "opacity": 25}])
    entry = next(e for e in workspace._entries
                 if e.obj.code == "5310" and e.obj.is_closed)
    style = workspace._style(entry)
    assert style["hasFill"] is True
    assert style["fill"] == "#FF0000"
    assert abs(style["opacity"] - 0.25) < 1e-6
