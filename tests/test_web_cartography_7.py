"""Stage 7 native labels, safe library rendering and default baked export."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile
import json
import sys

import pytest

from conftest import MapBuilder
from geostudio.geomap import GeoMap
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.native_picker import NativeMapPicker
from geostudio.web_app.server import create_app
from geostudio.web_app.geometry_6a import geometry_of


def auth(ws):
    status=ws.editing_status()
    return {"document_token":status["documentToken"],
            "revision":status["revision"]}


def map_with_overlay():
    return (MapBuilder()
      .object("5310","BASE",{"A1":"l","A2":"So120|II-0.3"},
              [(0,0),(0,20),(20,20),(20,0)])
      .object("5310","TOP",{"A1":"l","A2":"So120|II-0.3"},
              [(5,5),(5,10),(10,10),(10,5)])
      .object("5220","FOREST",{"A1":"LsV"},[(30,0),(30,10),(40,10),(40,0)])
      .build())


def populated_workspace():
    ws=PreviewWorkspace()
    ws.load_map(map_with_overlay(),"MOKRA WIEŚ.MAP")
    plan=ws.preview_move_polygons(["f1"],1,0,allow_detach=True,
                                   snap_distance=0,**auth(ws))
    assert plan["canApply"]
    ws.apply_move_polygons(["f1"],1,0,allow_detach=True,
                           snap_distance=0,preview_key=plan["previewKey"],
                           **auth(ws))
    return ws


def test_new_5310_polygon_has_native_L_descriptor_records_and_positive_area():
    doc=GeoMap(map_with_overlay())
    keep=doc.lines[doc.by_id["FOREST"].start:doc.by_id["FOREST"].end]
    uid=doc.append_polygon([(50,0),(50,10),(60,10),(60,0)],
                           code="5310",fields={"A1":"xd","A2":"So03"})
    obj=doc.by_id[uid]
    raws=doc.lines[obj.start:obj.end]
    assert sum(raw.startswith(b"L 1 ") for raw in raws)==1
    assert sum(raw.startswith(b"L 2 ") for raw in raws)==1
    assert sum(raw.startswith(b"L 3 ") for raw in raws)==1
    assert max(i for i,x in enumerate(raws) if x.startswith(b"L ")) < min(
        i for i,x in enumerate(raws) if x.startswith(b"P "))
    assert doc.signed_area([(p.x,p.y) for p in obj.points[:-1]])>0
    assert doc.lines[doc.by_id["FOREST"].start:doc.by_id["FOREST"].end]==keep
    assert GeoMap(doc.to_bytes()).checksum_valid


def test_merge_donor_native_label_L_records_survive_and_keep_first_anchor():
    builder=MapBuilder()
    builder.object("5310","BASE",{"A1":"l","A2":"So120|II-0.3"},
                   [(0,0),(0,10),(10,10),(10,0)])
    builder.raw("*5310 255  24    5871579")
    builder.raw(":ID[DONOR]")
    builder.raw(":A1[l]")
    builder.raw(":A2[So120|II-0.3]")
    native=[
        "L 2 5.647 -1.042 0.0000000 1.0000000 21",
        "L 3 -15.107 -1.042 0.0015708 1.0000000 21",
        "L 1 0.000 0.000 0.0015708 1.0000000 21",
    ]
    for line in native:builder.raw(line)
    for x,y in [(20,0),(20,10),(30,10),(30,0),(20,0)]:
        builder.raw(f"P 1   {x:.3f}   {y:.3f}")
    ws=PreviewWorkspace()
    ws.load_map(builder.build(),"mapa.MAP")
    preview=ws.preview_geometry_operation({"action":"merge","ids":["f0","f1"]},**auth(ws))
    assert preview["canApply"]
    ws.apply_geometry_operation({"action":"merge","ids":["f0","f1"]},
            preview_key=preview["previewKey"],**auth(ws))
    doc=GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    obj=doc.by_id["BASE"]
    raw=b"".join(doc.lines[obj.start:obj.end]).decode("cp1250")
    for label in native:assert label in raw
    assert obj.points[0].x==0 and obj.points[0].y==0
    assert len(obj.display_parts)==2
    assert doc.checksum_valid


def test_merge_keeper_native_L_not_overwritten():
    builder=MapBuilder()
    builder.raw("*5310 255  24    5871579")
    builder.raw(":ID[BASE]")
    builder.raw(":A1[l]")
    builder.raw(":A2[So120|II-0.3]")
    anchor="L 2 17.000 2.000 0.0000000 1.0000000 21"
    builder.raw(anchor)
    for x,y in [(0,0),(0,10),(10,10),(10,0),(0,0)]:
        builder.raw(f"P 1   {x:.3f}   {y:.3f}")
    builder.object("5310","DONOR",{"A1":"l","A2":"So120|II-0.3"},
                   [(20,0),(20,10),(30,10),(30,0)])
    ws=PreviewWorkspace()
    ws.load_map(builder.build(),"mapa.MAP")
    preview=ws.preview_geometry_operation({"action":"merge","ids":["f0","f1"]},**auth(ws))
    ws.apply_geometry_operation({"action":"merge","ids":["f0","f1"]},
        preview_key=preview["previewKey"],**auth(ws))
    doc=GeoMap(ws.export_copy(auth(ws)["document_token"])[1])
    raws=b"".join(doc.lines[doc.by_id["BASE"].start:doc.by_id["BASE"].end]).decode("cp1250")
    assert anchor in raws
    assert raws.count("L 2 ")==1 and "L 3 " in raws and "L 1 " in raws


def test_default_windows_save_bakes_overlays_instead_of_requiring_6b_button(
        tmp_path,monkeypatch):
    ws=populated_workspace()
    dst=tmp_path/"domyslnie_wyciecia.MAP"
    class Root:
        def withdraw(self):pass
        def attributes(self,*args):pass
        def update(self):pass
        def destroy(self):pass
    tkinter=SimpleNamespace(Tk=Root, filedialog=SimpleNamespace(
        asksaveasfilename=lambda **kwargs:str(dst)))
    monkeypatch.setitem(sys.modules,"tkinter",tkinter)
    saved=NativeMapPicker(ws,settings=tmp_path/"preferences.json").save_map()
    assert saved["nativeCutouts"] is True
    assert saved["topologyPath"]
    baked=GeoMap(dst.read_bytes())
    assert len(geometry_of(baked.by_id["BASE"]).interiors)==1
    companion=Path(saved["topologyPath"])
    meta=json.loads(companion.read_text(encoding="utf-8"))
    assert meta["format"]=="geostudio-topology-v2"
    assert "BASE" in meta["originalP"]
    reopened=PreviewWorkspace()
    reopened.load_map(dst.read_bytes(),dst.name)
    reopened.import_topology_metadata(companion.read_bytes(),dst.read_bytes())
    assert geometry_of(reopened._doc.by_id["BASE"]).area==pytest.approx(400)


def test_default_browser_zip_contains_both_baked_MAP_and_recovery():
    from fastapi.testclient import TestClient
    ws=populated_workspace()
    app=create_app(ws)
    token=ws.editing_status()["documentToken"]
    with TestClient(app) as client:
        response=client.get("/api/export/package",params={"documentToken":token},
                            headers={"X-GeoStudio-Token":app.state.api_token})
    assert response.status_code==200
    assert response.headers["content-type"].startswith("application/zip")
    archive=ZipFile(BytesIO(response.content))
    names=archive.namelist()
    assert len(names)==2
    assert names[0].endswith(".MAP") and names[1].endswith(".geostudio-topology.json")
    exported=archive.read(names[0])
    meta=json.loads(archive.read(names[1]))
    assert meta["format"]=="geostudio-topology-v2"
    assert GeoMap(exported).checksum_valid
    assert len(geometry_of(GeoMap(exported).by_id["BASE"]).interiors)==1


def test_library_bytes_CDF_LAY_SYM_add_in_memory_styles_without_changing_MAP():
    ws=PreviewWorkspace()
    raw=map_with_overlay()
    ws.load_map(raw,"mapa.MAP")
    before=ws.export_copy(auth(ws)["document_token"])[1]
    cdf=b"5310 22 33 44 3 88 99 100 1.2\r\n"
    lay=b"5310 32768 2.008 1 standard 2.5 0\r\n"
    sym=(b"*5310 building\r\n O 4003 0 0 0 0 0\r\n"
         b"*4003 dashed\r\n2 2 -1 0 0\r\n")
    for name,data in [("KOLORY.CDF",cdf),("LINIE.LAY",lay),("ZNAKI.SYM",sym)]:
        result=ws.set_cartographic_library(name,data)
        assert result["loaded"] and result["definitions"]>=1
    assert set(ws.cartography_status()["libraries"])=={"CDF","LAY","SYM"}
    rendered=ws.viewport((-1e3,-1e3,1e3,1e3))
    building=next(x for x in rendered["features"] if x["code"]=="5310")
    assert building["style"]["fill"]=="#16212C"
    assert building["style"]["stroke"]=="#586364"
    assert building["style"]["hatch"]==3
    assert building["style"]["dash"]==[6,3]
    assert building["style"]["strokeWidth"]==1.2
    assert ws.export_copy(auth(ws)["document_token"])[1]==before
    ws.load_map(raw,"mapa2.MAP")
    assert set(ws.cartography_status()["libraries"])=={"CDF","LAY","SYM"}


def test_invalid_library_path_name_and_parser_never_replace_existing():
    ws=PreviewWorkspace()
    ws.set_cartographic_library("lines.LAY",b"5310 32768 2.008 1 standard 2.5")
    for name,data in [("../evil.LAY",b"x"),("lines.exe",b"x"),
                      ("colors.CDF",b"garbage")]:
        with pytest.raises(ValueError):
            ws.set_cartographic_library(name,data)
    assert set(ws.cartography_status()["libraries"])=={"LAY"}


def test_stage7_native_picker_browser_controls_exist():
    root=Path(__file__).resolve().parents[1]/"geostudio/web_app"
    h=(root/"static/index.html").read_text(encoding="utf-8")
    j=(root/"static/map.js").read_text(encoding="utf-8")
    assert 'id="tool-cartography"' in h
    assert 'id="file-library"' in h
    for item in ["function hatchPattern(","function chooseCartographicLibraries(",
                 "async function openCartographicFiles(","/api/export/package",
                 "hasReversibleMasks"]:
        assert item in j
