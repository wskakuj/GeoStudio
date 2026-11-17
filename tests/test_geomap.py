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
