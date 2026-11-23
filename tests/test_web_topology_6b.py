"""Stage 6B: true multipart merge, native hole export and reversible recovery."""
from __future__ import annotations

import json
from shapely.geometry import Polygon
import pytest

from conftest import MapBuilder
from geostudio.geomap import GeoMap
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.geometry_6a import geometry_of


def auth(w):
    status=w.editing_status()
    return {"document_token":status["documentToken"],
            "revision":status["revision"]}


def operation(w,action,ids):
    payload={"action":action,"ids":ids}
    preview=w.preview_geometry_operation(payload,**auth(w))
    assert preview["canApply"],preview
    return preview,w.apply_geometry_operation(
        payload,preview_key=preview["previewKey"],**auth(w))


def move(w,ids,dx,dy):
    preview=w.preview_move_polygons(ids,dx,dy,allow_detach=True,
        snap_distance=0,**auth(w))
    assert preview["canApply"],preview
    result=w.apply_move_polygons(ids,dx,dy,allow_detach=True,
        snap_distance=0,preview_key=preview["previewKey"],**auth(w))
    assert result["changed"]


def workspace(raw):
    ws=PreviewWorkspace()
    ws.load_map(raw,"WIEŚ.MAP")
    return ws


def source(a,b):
    fields={"A1":"b","A2":"dom"}
    return (MapBuilder()
      .object("5310","A",fields,[(0,0),(0,10),(10,10),(10,0)])
      .object("5310","B",fields,b)
      .object("5220","F",{"A1":"LsV"},[(30,0),(30,10),(40,10),(40,0)])
      .build())


@pytest.mark.parametrize("other",[
    [(10,10),(10,20),(20,20),(20,10)],  # single shared node
    [(20,0),(20,10),(30,10),(30,0)],    # completely disconnected
])
def test_merge_point_touching_or_disconnected_as_one_native_multipart(other):
    ws=workspace(source(None,other))
    original=ws.export_copy(auth(ws)["document_token"])[1]
    plan,result=operation(ws,"merge",["f0","f1"])
    assert plan["components"]==2
    assert plan["rings"]==2
    doc=GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    assert "A" in doc.by_id and "B" not in doc.by_id
    assert doc.by_id["A"].is_closed
    assert len(doc.by_id["A"].display_parts)==2
    assert any(p.point_type==0 for p in doc.by_id["A"].points)
    assert doc.by_id["A"].area_m2==pytest.approx(200)
    assert geometry_of(doc.by_id["A"]).area==pytest.approx(200)
    assert doc.checksum_valid and doc.declared_lines==len(doc.lines)
    original_doc=GeoMap(original)
    assert (original_doc.lines[original_doc.by_id["F"].start:
                              original_doc.by_id["F"].end] ==
            doc.lines[doc.by_id["F"].start:doc.by_id["F"].end])
    ws.step_history("undo",**auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1]==original
    ws.step_history("redo",**auth(ws))
    assert len(GeoMap(ws.export_copy(auth(ws)["document_token"])[1]).
               by_id["A"].display_parts)==2


def test_merge_four_bars_around_hole_keeps_inner_contour():
    fields={"A1":"b","A2":"ramka"}
    raw=(MapBuilder()
       .object("5310","BOTTOM",fields,[(0,0),(0,20),(5,20),(5,0)])
       .object("5310","TOP",fields,[(15,0),(15,20),(20,20),(20,0)])
       .object("5310","LEFT",fields,[(5,0),(5,5),(15,5),(15,0)])
       .object("5310","RIGHT",fields,[(5,15),(5,20),(15,20),(15,15)])
       .build())
    ws=workspace(raw)
    plan,result=operation(ws,"merge",["f0","f1","f2","f3"])
    assert plan["components"]==1 and plan["rings"]==2
    doc=GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    merged=doc.by_id["BOTTOM"]
    assert len(merged.display_parts)==2
    shape=geometry_of(merged)
    assert len(shape.interiors)==1
    assert merged.area_m2==pytest.approx(300)
    assert shape.area==pytest.approx(300)


def test_automatic_positive_winding_in_native_save_keeps_source_unchanged():
    raw=source(None,[(20,0),(20,10),(30,10),(30,0)])
    ws=workspace(raw)
    before=ws.export_copy(auth(ws)["document_token"])[1]
    _,positive=ws.export_positive_copy(auth(ws)["document_token"])
    assert ws.export_copy(auth(ws)["document_token"])[1]==before
    doc=GeoMap(positive)
    assert doc.checksum_valid
    for uid in ("A","B","F"):
        obj=doc.by_id[uid]
        assert GeoMap.signed_area(
            [(p.x,p.y) for p in obj.points[:-1]])>0
    assert positive!=before


def test_native_cutout_bakes_an_actual_hole_and_can_recover_original():
    fields={"A1":"b","A2":"dom"}
    raw=(MapBuilder()
        .object("5310","BASE",fields,[(0,0),(0,20),(20,20),(20,0)])
        .object("5310","TOP",fields,[(5,5),(5,10),(10,10),(10,5)])
        .object("5220","FOREST",{"A1":"LsV"},
                [(0,0),(0,20),(20,20),(20,0)])
        .build())
    ws=workspace(raw)
    move(ws,["f1"],1,0)
    before=ws.export_copy(auth(ws)["document_token"])[1]
    name,baked_bytes,companion=ws.export_native_cutouts(
        auth(ws)["document_token"])
    assert name.endswith("_GeoStudio2_wyciecia.MAP")
    meta=json.loads(companion)
    assert meta["format"]=="geostudio-topology-v2"
    assert "BASE" in meta["originalP"]
    output=GeoMap(baked_bytes)
    assert output.checksum_valid and output.declared_lines==len(output.lines)
    base=output.by_id["BASE"]
    assert base.is_closed and len(base.display_parts)==2
    assert any(p.point_type==0 for p in base.points)
    assert len(geometry_of(base).interiors)==1
    assert geometry_of(base).area==pytest.approx(375)
    assert geometry_of(output.by_id["TOP"]).area==pytest.approx(25)
    assert geometry_of(output.by_id["FOREST"]).area==pytest.approx(400)
    restored=workspace(baked_bytes)
    restored.import_topology_metadata(companion,baked_bytes)
    _,after=restored.export_copy(auth(restored)["document_token"])
    assert GeoMap(after).by_id["BASE"].area_m2==400
    assert len(GeoMap(after).by_id["BASE"].display_parts)==1
    assert restored.editing_status()["hasReversibleMasks"]
    again=restored.export_native_cutouts(auth(restored)["document_token"])[1]
    assert again==baked_bytes
    ws.step_history("undo",**auth(ws))
    assert ws.export_copy(auth(ws)["document_token"])[1]!=before


def test_baked_companion_rejects_tampering_without_mutating_document():
    raw=(MapBuilder()
         .object("5310","A",{"A1":"b"},[(0,0),(0,20),(20,20),(20,0)])
         .object("5310","B",{"A1":"b"},[(5,5),(5,10),(10,10),(10,5)])
         .build())
    ws=workspace(raw)
    move(ws,["f1"],1,0)
    _,baked,companion=ws.export_native_cutouts(
        auth(ws)["documentToken"] if "documentToken" in auth(ws)
        else auth(ws)["document_token"])
    altered=bytearray(baked)
    altered[-5]^=1
    reopened=workspace(baked)
    before=reopened.export_copy(auth(reopened)["document_token"])[1]
    with pytest.raises(ValueError,match="nie pasuje"):
        reopened.import_topology_metadata(companion,bytes(altered))
    assert reopened.export_copy(auth(reopened)["document_token"])[1]==before
    broken=json.loads(companion)
    broken["baseSha256"]="0"*64
    with pytest.raises(ValueError,match="odtworzyć"):
        reopened.import_topology_metadata(json.dumps(broken).encode(),baked)
    assert reopened.export_copy(auth(reopened)["document_token"])[1]==before


def test_completely_occluded_polygon_fails_closed_not_disappears():
    raw=(MapBuilder()
         .object("5310","SMALL",{"A1":"b"},[(5,5),(5,10),(10,10),(10,5)])
         .object("5310","BIG",{"A1":"b"},[(0,0),(0,20),(20,20),(20,0)])
         .build())
    ws=workspace(raw)
    move(ws,["f1"],1,0)
    old=ws.export_copy(auth(ws)["document_token"])[1]
    with pytest.raises(ValueError,match="całkowicie przykryty"):
        ws.export_native_cutouts(auth(ws)["document_token"])
    assert ws.export_copy(auth(ws)["document_token"])[1]==old


def test_stage_6b_browser_and_native_picker_hooks_present():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]/"geostudio/web_app"
    html=(root/"static/index.html").read_text(encoding="utf8")
    js=(root/"static/map.js").read_text(encoding="utf8")
    native=(root/"native_picker.py").read_text(encoding="utf8")
    # Przycisk „Zapisz wycięcie” usunięty z zakładki Eksport (na życzenie),
    # ale natywny zapis wycięć i tak musi istnieć w kodzie.
    assert "save_baked_map" in js and "def save_baked_map(" in native


def test_native_baked_save_reopens_with_reversible_original(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace
    from geostudio.web_app.native_picker import NativeMapPicker
    fields={"A1":"b","A2":"dom"}
    raw=(MapBuilder()
        .object("5310","BASE",fields,[(0,0),(0,20),(20,20),(20,0)])
        .object("5310","TOP",fields,[(5,5),(5,10),(10,10),(10,5)])
        .build())
    ws=workspace(raw)
    move(ws,["f1"],1,0)
    destination=tmp_path/"WIEŚ_GeoStudio2_wyciecia.MAP"
    class Root:
        def withdraw(self):pass
        def attributes(self,*a):pass
        def update(self):pass
        def destroy(self):pass
    fake=SimpleNamespace(Tk=Root,
        filedialog=SimpleNamespace(asksaveasfilename=lambda **k:str(destination)))
    monkeypatch.setitem(sys.modules,"tkinter",fake)
    picker=NativeMapPicker(ws,settings=tmp_path/"settings.json")
    saved=picker.save_baked_map()
    assert saved["nativeCutouts"] is True
    assert destination.is_file()
    companion=destination.with_suffix(".geostudio-topology.json")
    assert companion.is_file()
    assert GeoMap(destination.read_bytes()).checksum_valid
    assert len(geometry_of(GeoMap(destination.read_bytes()).by_id["BASE"]).interiors)==1
    reopened=PreviewWorkspace()
    loader=NativeMapPicker(reopened,settings=tmp_path/"settings2.json")
    monkeypatch.setattr(NativeMapPicker,"_choose_path",lambda self:str(destination))
    meta=loader.open_map()
    assert meta["metadata"]["topologyImported"]
    assert geometry_of(reopened._doc.by_id["BASE"]).area==pytest.approx(400)
    assert next(f for f in reopened.viewport((-1,-1,30,30))["features"]
                if f["id"]=="f0")["visibleAreaM2"]==pytest.approx(375)


def test_native_baked_save_cleans_companion_if_map_commit_fails(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace
    import geostudio.web_app.native_picker as picker_module
    from geostudio.web_app.native_picker import NativeMapPicker
    ws=workspace(source(None,[(20,0),(20,10),(30,10),(30,0)]))
    destination=tmp_path/"out.MAP"
    class Root:
        def withdraw(self):pass
        def attributes(self,*a):pass
        def update(self):pass
        def destroy(self):pass
    monkeypatch.setitem(sys.modules,"tkinter",SimpleNamespace(
        Tk=Root, filedialog=SimpleNamespace(
            asksaveasfilename=lambda **kwargs:str(destination))))
    real_replace=picker_module.os.replace
    def deny_map_commit(src,dst):
        if str(dst)==str(destination):
            raise OSError("Simulated MAP commit error")
        return real_replace(src,dst)
    monkeypatch.setattr(picker_module.os,"replace",deny_map_commit)
    picker=NativeMapPicker(ws,settings=tmp_path/"settings.json")
    with pytest.raises(OSError,match="Simulated"):
        picker.save_baked_map()
    assert not destination.exists()
    assert not destination.with_suffix(".geostudio-topology.json").exists()
