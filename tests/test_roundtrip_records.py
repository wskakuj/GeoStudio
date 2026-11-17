"""Round-trip and preservation tests built on the shared MapBuilder fixtures.

These cover the record types described in docs/FORMAT.md: header with N/CHK,
the EXT line, object headers, metadata fields, P vertices, P 0 terminators,
unknown records and Windows-1250 text. Every assertion is about bytes that
must survive a no-op save untouched.
"""
from __future__ import annotations

import hashlib

import pytest

from geostudio.geomap import GeoMap


def test_header_line_count_and_checksum_are_consistent(simple_map):
    doc = GeoMap(simple_map)
    assert doc.checksum_valid
    assert doc.declared_lines == len(doc.lines)


def test_noop_roundtrip_is_byte_exact(simple_map):
    assert GeoMap(simple_map).to_bytes() == simple_map


def test_declared_extent_is_parsed(simple_map):
    # The leading token of the EXT line is the compilation scale; the parser
    # returns only the four extent values that follow it.
    assert GeoMap(simple_map).declared_extent == (0.0, 0.0, 100.0, 100.0)


def test_all_metadata_fields_are_read(map_builder):
    raw = (map_builder()
           .object(uid="F-1", fields={"A1": "1", "A2": "2", "A3": "3", "A4": "4",
                                      "A5": "5", "A6": "#POLE=12.5000;",
                                      "TX": "opis", "MP": "0", "KR": "7"})
           .build())
    obj = GeoMap(raw).by_id["F-1"]
    assert obj.fields["A6"] == "#POLE=12.5000;"
    assert obj.fields["TX"] == "opis"
    assert obj.fields["KR"] == "7"


def test_unknown_records_survive_edits(map_builder):
    raw = (map_builder()
           .object(uid="U-1", fields={"A2": "przed"})
           .raw(":ZZZ[nieznany rekord]")
           .raw("L 12 34 56 78")
           .build())
    doc = GeoMap(raw)
    doc.update_field("U-1", "A2", "po")
    out = doc.to_bytes()
    assert b":ZZZ[nieznany rekord]" in out
    assert b"L 12 34 56 78" in out
    assert GeoMap(out).by_id["U-1"].fields["A2"] == "po"


def test_edit_recomputes_checksum_and_line_count(map_builder):
    doc = GeoMap(map_builder().object(uid="C-1", fields={"A2": "x"}).build())
    doc.update_field("C-1", "A2", "y")
    out = doc.to_bytes()
    header = out.split(b"\r\n", 1)[0]
    body = out.split(b"\r\n", 1)[1]
    assert hashlib.md5(body).hexdigest().encode() in header
    assert GeoMap(out).declared_lines == len(out.splitlines())


def test_multipart_object_keeps_both_components(map_builder):
    raw = map_builder().multipart(uid="MP-1").build()
    obj = GeoMap(raw).by_id["MP-1"]
    assert len(obj.points) == 8
    assert [len(part) for part in obj.display_parts] == [4, 4]
    assert GeoMap(raw).to_bytes() == raw


def test_windows_1250_text_roundtrip(map_builder):
    text = "Łąka, część północna — zażółć gęślą jaźń"
    raw = map_builder().object(uid="PL-1", fields={"TX": text}).build()
    assert GeoMap(raw).by_id["PL-1"].fields["TX"] == text
    assert GeoMap(raw).to_bytes() == raw


def test_lf_only_file_is_not_rewritten_to_crlf(map_builder):
    raw = map_builder(eol="\n").object(uid="LF-1").build()
    assert b"\r\n" not in raw
    assert GeoMap(raw).to_bytes() == raw


def test_missing_trailing_newline_is_preserved(map_builder):
    raw = map_builder().object(uid="E-1").build(trailing_newline=False)
    assert not raw.endswith(b"\r\n")
    assert GeoMap(raw).to_bytes() == raw


def test_polygon_area_uses_vertices(map_builder):
    raw = (map_builder()
           .object(uid="A-1", points=[(0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0)])
           .build())
    assert GeoMap(raw).by_id["A-1"].area_m2 == pytest.approx(12.0)


def test_open_polyline_is_not_closed(map_builder):
    raw = (map_builder()
           .object(uid="O-1", closed=False, points=[(0.0, 0.0), (5.0, 0.0), (5.0, 5.0)])
           .build())
    obj = GeoMap(raw).by_id["O-1"]
    assert obj.is_closed is False
    assert obj.area_m2 is None


def test_vertex_labels_are_read(map_builder):
    raw = (map_builder()
           .object(uid="V-1", closed=False,
                   points=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
                   labels=["101", "", "102"])
           .build())
    assert [p.label for p in GeoMap(raw).by_id["V-1"].points] == ["101", "", "102"]


def test_vertex_move_updates_both_ring_endpoints(map_builder):
    doc = GeoMap(map_builder().object(uid="M-1",
                                      points=[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]).build())
    doc.move_polygon_vertex("M-1", 0, 0.5, 0.5)
    obj = GeoMap(doc.to_bytes()).by_id["M-1"]
    assert (obj.points[0].x, obj.points[0].y) == (0.5, 0.5)
    assert (obj.points[-1].x, obj.points[-1].y) == (0.5, 0.5)


def test_deleting_one_object_leaves_the_other_intact(map_builder):
    raw = (map_builder()
           .object(uid="K-1", points=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)])
           .object(uid="K-2", points=[(5.0, 5.0), (6.0, 5.0), (6.0, 6.0)])
           .build())
    doc = GeoMap(raw)
    doc.delete_object("K-1")
    out = doc.to_bytes()
    assert b"K-1" not in out
    assert GeoMap(out).by_id["K-2"].area_m2 == pytest.approx(0.5)
    assert GeoMap(out).checksum_valid


def test_save_as_never_overwrites(map_file):
    doc = GeoMap.open(map_file)
    with pytest.raises(FileExistsError):
        doc.save_as(map_file)


def test_rejects_foreign_header():
    with pytest.raises(ValueError):
        GeoMap(b";# not a GEO-MAP file\r\n").to_bytes()


def test_field_values_cannot_inject_newlines(simple_map):
    doc = GeoMap(simple_map)
    with pytest.raises(ValueError):
        doc.update_field("DEMO-01", "A2", "zły\nrekord")
