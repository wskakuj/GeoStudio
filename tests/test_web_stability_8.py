"""Stage 8: GEO-MAP GMW 10.52 multipart closure, performance and safety."""
from __future__ import annotations

from hashlib import md5
from time import perf_counter
from pathlib import Path
import os
import pytest

from geostudio.geomap import GeoMap
from geostudio.web_app.geometry_6a import geometry_of, rings_from_shape
from geostudio.web_app.data import PreviewWorkspace


def _map_bytes(lines):
    body=b"\r\n".join(lines)+b"\r\n"
    header=(
        b";# Plik danych systemu GEO-MAP ver=[ 8.00]  N=["+
        f"{len(lines)+1:12d}".encode()+
        b"] CHK=["+md5(body).hexdigest().encode()+b"]\r\n"
    )
    return header+body


def _multipart_with_or_without_gmw_closure(global_closure):
    """Small actual GMW-style 5310 record with two disjoint islands."""
    lines=[
        b"*5310 255  24    5871579",
        b":ID[B705AB37-F1B5-4350-A2C5-A225BA840C21]",
        b":A1[l]",
        b":A2[So120|II-0.3]",
        b":MP[0]",
        b":FA[5871579]",
        b"L 2 5.647 -1.042 0.0000000 1.0000000 21",
        b"L 3 -15.107 -1.042 0.0015708 1.0000000 21",
        b"L 1 0.000 0.000 0.0015708 1.0000000 21",
        b"P 1   512885.290   669202.050",
        b"P 1   512883.590   669223.700",
        b"P 1   512873.880   669200.590",
        b"P 0   512885.290   669202.050",
        b"P 1   512897.853   669176.864",
        b"P 1   512899.233   669152.574",
        b"P 1   512908.453   669178.224",
        b"P 1   512897.853   669176.864",
    ]
    if global_closure:
        lines.append(b"P 1   512885.290   669202.050")
    return _map_bytes(lines)


def test_gmw_multipart_global_closure_is_not_an_extra_polygon_edge():
    original=GeoMap(_multipart_with_or_without_gmw_closure(False))
    corrected=GeoMap(_multipart_with_or_without_gmw_closure(True))
    uid="B705AB37-F1B5-4350-A2C5-A225BA840C21"
    assert corrected.checksum_valid
    assert corrected.declared_lines==len(corrected.lines)
    assert original.by_id[uid].is_closed and corrected.by_id[uid].is_closed
    assert len(original.by_id[uid].display_parts)==2
    assert len(corrected.by_id[uid].display_parts)==2
    shape_a=geometry_of(original.by_id[uid])
    shape_b=geometry_of(corrected.by_id[uid])
    assert shape_a.equals(shape_b)
    assert corrected.by_id[uid].area_m2==pytest.approx(original.by_id[uid].area_m2)


def test_every_native_multipart_export_ends_with_first_global_vertex():
    uid="B705AB37-F1B5-4350-A2C5-A225BA840C21"
    doc=GeoMap(_multipart_with_or_without_gmw_closure(False))
    geom=geometry_of(doc.by_id[uid])
    rings=rings_from_shape(geom,
        prefer_anchor=(512885.290,669202.050))
    doc.replace_polygon_components(uid,rings)
    out=GeoMap(doc.to_bytes())
    assert out.checksum_valid and out.declared_lines==len(out.lines)
    o=out.by_id[uid]
    assert o.points[-1].point_type==1
    assert (o.points[0].x,o.points[0].y)==(o.points[-1].x,o.points[-1].y)
    assert (o.points[-2].x,o.points[-2].y)!=(
        o.points[-1].x,o.points[-1].y)
    assert len(o.display_parts)==2
    assert geometry_of(o).equals_exact(geom,0.001)==False or (
        geom.symmetric_difference(geometry_of(o)).area<.002)
    assert geom.symmetric_difference(geometry_of(o)).area<.002
    assert b"L 2 5.647 -1.042" in out.to_bytes()
    assert b":A2[So120|II-0.3]" in out.to_bytes()


def test_true_hole_has_gmw_global_closure_and_preserves_area():
    uid="B705AB37-F1B5-4350-A2C5-A225BA840C21"
    doc=GeoMap(_multipart_with_or_without_gmw_closure(False))
    shell=[(0,0),(0,40),(40,40),(40,0),(0,0)]
    hole=[(10,10),(10,20),(20,20),(20,10),(10,10)]
    doc.replace_polygon_components(uid,[shell,hole])
    result=GeoMap(doc.to_bytes())
    obj=result.by_id[uid]
    assert obj.is_closed and len(obj.display_parts)==2
    assert (obj.points[0].x,obj.points[0].y)==(
        obj.points[-1].x,obj.points[-1].y)
    assert geometry_of(obj).area==pytest.approx(1500.)
    assert result.checksum_valid


def test_unmodified_map_is_byte_exact_after_parsing_gmw_closure():
    original=_multipart_with_or_without_gmw_closure(True)
    doc=GeoMap(original)
    assert doc.to_bytes()==original
    assert doc.checksum_valid


def test_100k_line_map_roundtrip_with_valid_checksum_is_bounded():
    # Regression on large maps without committing user source files.
    # The benchmark cap is intentionally generous for slow CI hardware.
    lines=[]
    for i in range(16000):
        x=510000+i*.001
        y=670000+i*.001
        lines.extend([
            b"*5216 8553090  15          0",
            (":ID[PERF-%05d]"%i).encode(),
            ("P 1   %.3f   %.3f"%(x,y)).encode(),
            ("P 1   %.3f   %.3f"%(x,y+1)).encode(),
            ("P 1   %.3f   %.3f"%(x+1,y+1)).encode(),
            ("P 1   %.3f   %.3f"%(x+1,y)).encode(),
            ("P 1   %.3f   %.3f"%(x,y)).encode(),
        ])
    source=_map_bytes(lines)
    start=perf_counter()
    doc=GeoMap(source)
    assert len(doc.objects)==16000
    assert doc.checksum_valid
    assert doc.to_bytes()==source
    assert perf_counter()-start<45



def test_recovery_snapshot_is_atomic_bound_to_source_and_tamper_detected(tmp_path):
    from hashlib import sha256
    from geostudio.web_app.recovery import LocalRecoveryStore
    source=tmp_path/"source.MAP"
    source.write_bytes(_multipart_with_or_without_gmw_closure(False))
    orig=source.read_bytes()
    store=LocalRecoveryStore(tmp_path/"user_recovery")
    initial=sha256(orig).hexdigest()
    changed=_multipart_with_or_without_gmw_closure(True)
    topo=b'{"format":"test-only-topology"}'
    saved=store.save(source,initial,changed,topo,revision=3)
    assert saved["saved"] and saved["revision"]==3
    assert store.candidate(source,initial)["available"]
    assert store.load(source,initial)[1:]==(changed,topo)
    assert source.read_bytes()==orig
    assert store.candidate(source,sha256(changed).hexdigest()) is None
    # Damage just the stored MAP. The manifest can no longer validate it.
    manifest=store._metadata(source)
    (store.directory/manifest["mapFile"]).write_bytes(b"bad")
    assert store.candidate(source,initial) is None
    assert store.load(source,initial) is None
    assert source.read_bytes()==orig


def test_crash_during_new_recovery_keeps_previous_complete_snapshot(tmp_path,
                                                                     monkeypatch):
    from hashlib import sha256
    import geostudio.web_app.recovery as rec
    source=tmp_path/"source.MAP"
    orig=_multipart_with_or_without_gmw_closure(False)
    source.write_bytes(orig)
    store=rec.LocalRecoveryStore(tmp_path/"recovery")
    digest=sha256(orig).hexdigest()
    original=store.save(source,digest,orig,b"{}",revision=1)
    real=rec._atomic_new
    def interrupt(path,data):
        if Path(path)==store._index(source):
            raise OSError("simulated disk full at manifest stage")
        return real(path,data)
    monkeypatch.setattr(rec,"_atomic_new",interrupt)
    with pytest.raises(OSError,match="disk full"):
        store.save(source,digest,_multipart_with_or_without_gmw_closure(True),
                   b'{"format":"new"}',revision=2)
    manifest,raw,meta=store.load(source,digest)
    assert manifest["revision"]==1
    assert raw==orig and meta==b"{}"
    assert len(list(store.directory.glob("*.MAP")))==1
    assert source.read_bytes()==orig


def test_native_restore_requires_user_consent_and_marks_unsaved(tmp_path,
                                                                 monkeypatch):
    from hashlib import sha256
    from conftest import MapBuilder
    from geostudio.web_app.native_picker import NativeMapPicker
    raw=(MapBuilder()
      .object("5310","B1",{"A1":"l","A2":"So120|II-0.3"},
              [(0,0),(0,10),(10,10),(10,0)])
      .object("5310","B2",{"A1":"l","A2":"So120|II-0.3"},
              [(10,0),(10,10),(20,10),(20,0)])
      .build())
    src=tmp_path/"Mapa.MAP"
    src.write_bytes(raw)
    monkeypatch.setattr(NativeMapPicker,"_choose_path",lambda self:str(src))
    first=PreviewWorkspace()
    bridge=NativeMapPicker(first,settings=tmp_path/"settings"/"preferences.json")
    opened=bridge.open_map()
    assert opened["metadata"]["objectCount"]==2
    auth={"document_token":first.editing_status()["documentToken"],
          "revision":first.editing_status()["revision"]}
    preview=first.preview_move_polygons(["f1"],5,0,allow_detach=True,
                                        snap_distance=0,**auth)
    assert preview["canApply"]
    first.apply_move_polygons(["f1"],5,0,allow_detach=True,
        preview_key=preview["previewKey"],snap_distance=0,**auth)
    edited=first.export_copy(first.editing_status()["documentToken"])[1]
    assert bridge.save_recovery()["saved"]
    assert src.read_bytes()==raw
    second=PreviewWorkspace()
    reopened=NativeMapPicker(second,settings=tmp_path/"settings"/"preferences.json")
    info=reopened.open_map()
    assert info["metadata"]["recoveryAvailable"]["revision"]==1
    assert second.export_copy(second.editing_status()["documentToken"])[1]==raw
    result=reopened.restore_recovery()
    assert result["restored"]
    assert second.export_copy(second.editing_status()["documentToken"])[1]==edited
    assert second.editing_status()["dirty"]
    assert not second.editing_status()["canUndo"]
    assert src.read_bytes()==raw
    # If an external program replaces the source file, the recovery is blocked.
    src.write_bytes(raw+b"garbage")
    with pytest.raises(ValueError,match="zmienił"):
        reopened.restore_recovery()


def test_dragging_moves_multiple_polygons_directly_without_showing_dialog():
    src=(Path(__file__).resolve().parents[1]/
         "geostudio/web_app/static/map.js").read_text(encoding="utf-8")
    assert "async function commitDraggedMove(" in src
    section=src.split("if(d.moveIds){",1)[1].split("if(d.node){",1)[0]
    assert "commitDraggedMove(d.moveIds,ghost)" in section
    assert "openMoveEditor(" not in section
    assert "previewMoveChanges()" not in section
    quick=src.split("async function commitDraggedMove(",1)[1].split(
        "function drawMoveGhost(",1)[0]
    assert "allowDetach:true" in quick
    assert "snapDistance:" in quick
    assert '"/api/move/preview"' in quick
    assert '"/api/move/apply"' in quick


def test_recovery_exposes_only_local_native_bridge_and_no_source_overwrite():
    from geostudio.web_app.native_picker import NativeMapPicker
    assert hasattr(NativeMapPicker,"save_recovery")
    assert hasattr(NativeMapPicker,"restore_recovery")
    source=(Path(__file__).resolve().parents[1]/
            "geostudio/web_app/native_picker.py").read_text(encoding="utf-8")
    assert 'self._settings.parent/"recovery"' in source
    assert 'self._workspace.mark_recovered_unsaved()' in source
    assert 'if sha256(path.read_bytes()).hexdigest()!=identity:' in source
