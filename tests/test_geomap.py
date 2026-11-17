from pathlib import Path
from geostudio.geomap import GeoMap, library_colors, library_layers, library_symbols
import hashlib
import pytest


def fixture_map():
    body=(
        b';# EXT 3500 0.000 0.000 100.000 100.000 #ST=0 CS=9 CM=21\r\n'
        b'*5216 8553090  15          0 \r\n'
        b':ID[DEMO-01]\r\n:A2[TEST]\r\n:A6[#POLE=0.0001;]\r\n'
        b'P 1   0.000   0.000\r\nP 1   1.000   0.000\r\n'
        b'P 1   1.000   1.000\r\nP 1   0.000   0.000\r\n'
        b':UNKNOWN[retain this]\r\n'
    )
    first=b';# Plik danych systemu GEO-MAP ver=[ 8.00]  N=[          11] CHK=['+hashlib.md5(body).hexdigest().encode()+b']\r\n'
    return first+body


def test_checksum_and_exact_roundtrip():
    raw=fixture_map(); doc=GeoMap(raw)
    assert doc.checksum_valid
    assert doc.to_bytes()==raw
    assert doc.objects[0].area_m2 == pytest.approx(0.5)
    assert doc.objects[0].fields['UNKNOWN']=='retain this'


def test_edit_preserves_unknown_records_and_updates_checksum():
    doc=GeoMap(fixture_map())
    doc.update_field('DEMO-01','A2','Nowa nazwa')
    data=doc.to_bytes();new=GeoMap(data)
    assert new.checksum_valid
    assert new.declared_lines == len(new.lines)
    assert new.objects[0].fields['A2']=='Nowa nazwa'
    assert b':UNKNOWN[retain this]' in data


def test_appending_polygon():
    doc=GeoMap(fixture_map())
    uid=doc.append_polygon([(0,0),(2,0),(0,2)],'5216','dodatkowy')
    raw=doc.to_bytes();verified=GeoMap(raw)
    assert verified.checksum_valid
    assert verified.declared_lines==len(verified.lines)
    assert verified.by_id[uid].area_m2==pytest.approx(2)
    assert verified.by_id[uid].fields['A2']=='dodatkowy'


def test_never_overwrite(tmp_path):
    doc=GeoMap(fixture_map()); dest=tmp_path/'mapa.MAP'
    doc.save_as(dest)
    with pytest.raises(FileExistsError):doc.save_as(dest)


def test_non_ascii_field_preserved():
    doc=GeoMap(fixture_map());doc.update_field('DEMO-01','TX','Łąka, część północna')
    got=GeoMap(doc.to_bytes())
    assert got.by_id['DEMO-01'].fields['TX']=='Łąka, część północna'


def test_layer_wildcards():
    from geostudio.geomap import resolve_layer
    catalog={'?246':'graniczniki','5216':'Działki','?9??':'Ważne'}
    assert resolve_layer(catalog,'1246')=='graniczniki'
    assert resolve_layer(catalog,'5216')=='Działki'
    assert resolve_layer(catalog,'7900')=='Ważne'
    assert resolve_layer(catalog,'0001')=='Inne / kod 0001'


def test_insert_polygon_vertex_preserves_attributes_and_checksum():
    doc = GeoMap(fixture_map())
    doc.insert_polygon_vertex('DEMO-01', 0, 0.5, 0)
    assert len(doc.by_id['DEMO-01'].points) == 5
    assert doc.by_id['DEMO-01'].area_m2 == pytest.approx(0.5)
    assert doc.by_id['DEMO-01'].points[1].x == 0.5
    saved = doc.to_bytes()
    assert b':UNKNOWN[retain this]' in saved
    assert b':A2[TEST]' in saved
    parsed = GeoMap(saved)
    assert parsed.checksum_valid
    assert parsed.declared_lines == len(parsed.lines)
    assert parsed.by_id['DEMO-01'].is_closed
    with pytest.raises(ValueError):
        parsed.insert_polygon_vertex('DEMO-01', 0, 0.001, 0.0)


def test_insert_polygon_vertex_on_last_closing_edge():
    doc = GeoMap(fixture_map())
    doc.insert_polygon_vertex('DEMO-01', 2, .5, .5)
    obj = doc.by_id['DEMO-01']
    assert obj.is_closed
    assert obj.points[-2].x == pytest.approx(.5)
    assert obj.points[-2].y == pytest.approx(.5)
    assert obj.area_m2 == pytest.approx(.5)

def test_new_polygon_has_full_editable_fields():
    doc = GeoMap(fixture_map())
    fields = {'A1':'105','A2':'RV','A3':'143411_5.0014','A4':'','A5':'',
              'A6':'','TX':'próba','MP':'0','DT':'','KR':''}
    uid = doc.append_polygon([(2,2),(4,2),(4,4)],'5220',fields=fields)
    again = GeoMap(doc.to_bytes())
    assert again.checksum_valid
    assert again.declared_lines == len(again.lines)
    assert again.by_id[uid].fields['A1'] == '105'
    assert again.by_id[uid].fields['A4'] == ''
    assert again.by_id[uid].fields['TX'] == 'próba'
    assert again.by_id[uid].is_closed


def test_delete_object_removes_record_not_neighbors():
    doc = GeoMap(fixture_map())
    original = doc.to_bytes()
    uid = doc.append_polygon([(2,2),(4,2),(4,4)],'5220','RV')
    assert len(doc.objects) == 2
    doc.delete_object(uid)
    verified = GeoMap(doc.to_bytes())
    assert verified.checksum_valid
    assert verified.declared_lines == len(verified.lines)
    assert verified.to_bytes() == original
    assert len(verified.objects) == 1
    with pytest.raises(KeyError):
        doc.delete_object(uid)


def test_multipart_p0_marks_breaks_without_changing_original_bytes():
    # A real GEO-MAP multipart object has P 0 after each component.
    body = (
        b';# EXT 3500 0 0 20 20\\r\\n'
        b'*5220 32768  16          0\\r\\n'
        b':ID[MULTI]\\r\\n:A1[105]\\r\\n:A2[RV]\\r\\n'
        b'P 1   0.000   0.000\\r\\n'
        b'P 1   1.000   0.000\\r\\n'
        b'P 1   1.000   1.000\\r\\n'
        b'P 0   0.000   0.000\\r\\n'
        b'P 1   10.000   10.000\\r\\n'
        b'P 1   11.000   10.000\\r\\n'
        b'P 1   11.000   11.000\\r\\n'
        b'P 0   10.000   10.000\\r\\n'
    )
    first = (b';# Plik danych systemu GEO-MAP ver=[ 8.00]  N=[          13] CHK=['
             + hashlib.md5(body).hexdigest().encode() + b']\\r\\n')
    data = first + body
    doc = GeoMap(data)
    assert doc.checksum_valid
    assert doc.to_bytes() == data
    obj = doc.by_id['MULTI']
    assert [len(part) for part in obj.display_parts] == [4, 4]
    assert obj.points[3].point_type == 0
    assert obj.points[4].point_type == 1
