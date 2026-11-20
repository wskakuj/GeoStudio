"""Regression checks for vector PDF captions and native print-scale layout."""
from __future__ import annotations

import pytest

from geostudio.web_app.print_layout import (
    _draw_pdf_labels, _font, _pdf_label_size,
)


def test_pdf_label_size_tracks_map_scale_and_compilation_scale():
    sample = {"text": "a", "size": 16}
    assert _pdf_label_size(sample, {"denominator": 5000}) == pytest.approx(6)
    assert _pdf_label_size(sample, {"denominator": 2500}) == pytest.approx(12)
    assert _pdf_label_size(sample, {
        "denominator": 5000,
        "sourceCompilationScale": 5000,
        "compilationScale": 10000,
    }) == pytest.approx(12)


def test_pdf_labels_are_centered_stacked_and_collision_aware():
    class Recorder:
        def __init__(self):
            self.lines = []
        def setFillColor(self, color):
            pass
        def setFont(self, font, size):
            pass
        def drawCentredString(self, x, y, text):
            self.lines.append((x, y, text))

    building = {
        "id": "building", "code": "5310", "bbox": [0, 0, 100, 100],
        "labels": [
            {"field": "A1", "text": "a", "x": 10, "y": 10, "size": 16},
            {"field": "A2", "text": "II\n0.5", "x": 10, "y": 10, "size": 16},
        ],
    }
    parcel = {
        "id": "parcel", "code": "5216", "bbox": [0, 0, 100, 100],
        "labels": [
            {"field": "A2", "text": "503", "x": 10, "y": 10, "size": 16},
        ],
    }
    recorder = Recorder()
    layout = {"map": (0, 0, 200, 200), "bounds": (0, 0, 100, 100),
              "font": _font()}
    _draw_pdf_labels(
        recorder, [parcel, building], {"denominator": 5000},
        layout, lambda xy: (xy[0], 100 - xy[1]),
    )
    # The PDF uses centered text drawing, preserves line breaks, and
    # suppresses the overlapping parcel rather than the mandatory 5310.
    assert [item[2] for item in recorder.lines] == ["a", "II", "0.5"]
    assert all(x == 10 for x, _, _ in recorder.lines)
    assert recorder.lines[0][1] > recorder.lines[1][1]
    assert recorder.lines[1][1] > recorder.lines[2][1]
