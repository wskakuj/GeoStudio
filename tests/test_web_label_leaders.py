"""Wysięgniki etykiet A1/A2 z natywnych rekordów L 2 / L 3."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from geostudio.geomap import parse_label_record  # noqa: E402


def test_left_leader_flags_133_and_shared_anchor():
    record = parse_label_record(
        b"L 2 10.232 -28.481 0.0000000 1.0000000 133 -8.180 1.438")
    assert record["slot"] == 2
    assert record["leader"] == "left"
    assert record["anchor"] == (-8.18, 1.438)
    assert record["dx"] == 10.232 and record["dy"] == -28.481


def test_right_leader_flags_69():
    record = parse_label_record(
        b"L 3 8.506 48.331 0.0000393 1.0000000 69 -8.180 1.438")
    assert record["slot"] == 3
    assert record["leader"] == "right"
    assert record["anchor"] == (-8.18, 1.438)


def test_plain_label_has_no_leader():
    record = parse_label_record(b"L 2 0.000 0.000 0.0000000 1.0000000 5")
    assert record["leader"] is None
    assert record["anchor"] is None


def test_labels_payload_carries_leader_for_both_slots():
    source = Path("geostudio/web_app/data.py").read_text(encoding="utf-8")
    assert "label_records(" in source
    assert '"leader": leader' in source
    # slot 2 -> A1, slot 3 -> A2
    assert 'leaders.get(2 if field == "A1" else 3 if field == "A2" else 0)' in source
