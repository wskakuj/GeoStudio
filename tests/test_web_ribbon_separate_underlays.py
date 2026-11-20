"""GeoStudio Stage 12 interface: no horizontally scrolling tool shelf.

Every existing action remains in the DOM exactly once, but the user sees
only the controls belonging to the selected ribbon tab. Keyboard navigation
is accessible; WMS, local raster and CRS have separate dialogs.
"""
from __future__ import annotations

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess

import pytest

STATIC=Path(__file__).resolve().parents[1]/"geostudio/web_app/static"


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.records=[]
    def handle_starttag(self,tag,attrs):
        self.records.append((tag,dict(attrs)))


def test_ribbon_contains_all_existing_tools_without_duplicate_ids():
    html=(STATIC/"index.html").read_text("utf-8")
    parser=Tags()
    parser.feed(html)
    records=parser.records
    ids=[attrs["id"] for tag,attrs in records if attrs.get("id")]
    duplicates=[name for name,count in Counter(ids).items() if count>1]
    assert duplicates==[]
    previous_tools={
        "tool-open","tool-sidecar","tool-cartography","tool-topology",
        "tool-undo","tool-redo","tool-export-baked","tool-select","tool-pan",
        "tool-move","tool-move-offset","tool-nodes","tool-clear-selection",
        "tool-advanced-select","tool-find","tool-replace-phrase",
        "tool-bulk-edit","tool-delete-node","tool-copy",
        "tool-delete-objects","tool-new-polygon","tool-draw-snap",
        "tool-merge","tool-split","tool-winding","tool-line","tool-fit",
        "tool-labels","tool-label-move","tool-label-config","tool-grid",
        "tool-underlay"
    }
    assert previous_tools<=set(ids)
    assert {"tool-raster","tool-crs","tool-layout-ribbon","tool-map-copy-ribbon"}<=set(ids)
    assert {"opt-snap","opt-shared","cartography-status"}<=set(ids)

    expected={"start","select","edit","draw","cartography","underlay","export"}
    tabs={attrs.get("data-ribbon-tab"):attrs for tag,attrs in records
          if tag=="button" and "data-ribbon-tab" in attrs}
    panels={attrs.get("data-ribbon-panel"):attrs for tag,attrs in records
            if "data-ribbon-panel" in attrs}
    assert set(tabs)==set(panels)==expected
    for name,tab in tabs.items():
        assert tab["role"]=="tab"
        assert tab["aria-controls"]=="ribbon-panel-"+name
        assert panels[name]["role"]=="tabpanel"
        assert panels[name]["aria-labelledby"]=="ribbon-tab-"+name
    assert sum(t["aria-selected"]=="true" for t in tabs.values())==1
    assert sum(t["tabindex"]=="0" for t in tabs.values())==1


def test_wms_raster_crs_have_independent_task_dialogs():
    html=(STATIC/"index.html").read_text("utf-8")
    # Boundaries ensure raster and GCP are not crammed into the WMS window.
    start=html.index('<dialog id="underlay-dialog"')
    raster=html.index('<dialog id="raster-dialog"')
    crs=html.index('<dialog id="crs-dialog"')
    end=html.index('<dialog id="command-dialog"')
    assert start<raster<crs<end
    wms_block=html[start:raster]
    raster_block=html[raster:crs]
    crs_block=html[crs:end]
    assert 'id="underlay-preset"' in wms_block
    assert 'id="underlay-url"' in wms_block
    assert 'id="underlay-layer"' in wms_block
    assert 'id="underlay-opacity"' in wms_block
    assert 'id="raster-gcp"' not in wms_block
    assert 'id="underlay-raster-file"' in raster_block
    assert 'id="underlay-world-file"' in raster_block
    assert 'id="raster-opacity"' in raster_block
    assert 'id="raster-gcp-canvas"' in raster_block
    assert 'id="raster-gcp-apply"' in raster_block
    assert '<textarea id="raster-gcp"' not in raster_block
    assert 'id="underlay-crs-target"' in crs_block
    assert 'id="underlay-prj-file"' in crs_block
    assert 'id="underlay-crs-convert"' in crs_block


def test_toolbar_no_horizontal_scroll_and_tab_event_binding():
    css=(STATIC/"styles.css").read_text("utf-8")
    js=(STATIC/"map.js").read_text("utf-8")
    assert 'overflow-x:auto;' not in css
    assert '#main-ribbon.toolbar' in css
    assert '.ribbon-panel[hidden] {display:none!important;}' in css
    assert 'setupRibbon();' in js
    assert 'event.key==="ArrowRight"' in js
    assert 'item.setAttribute("aria-selected",String(active));' in js
    assert 'link("tool-raster",openRasterDialog);' in js
    assert 'link("tool-crs",openCrsDialog);' in js
    assert 'link("tool-layout-ribbon",openLayoutDialog);' in js
    assert 'link("tool-map-copy-ribbon",downloadMapCopy);' in js
    assert 'setMapEPSG(String(result.epsg));' in js
    assert 'for(const id of ["underlay-epsg","raster-epsg","crs-epsg"])' in js


def test_shared_epsg_sync_keeps_native_map_calibrated_raster():
    node=shutil.which("node")
    if node is None: pytest.skip("Node required for JS UI regression")
    script=r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const source=fs.readFileSync('map.js','utf8');
const start=source.indexOf('  function setMapEPSG(');
const end=source.indexOf('  const wmsPresetUrls',start);
assert.ok(start>=0&&end>start);
const inputs=Object.fromEntries(['underlay-epsg','raster-epsg','crs-epsg']
    .map(id=>[id,{value:''}]));
let removed=0, redraw=0, info='';
const state={mapEPSG:'',previewActive:true,geometrySnapshotValid:true};
const underlay={enabled:true};
const raster={image:{},affine:[0,1,2,3,4,5],layers:[],boundEPSG:'',epsg:null};
const select=new Function('state','underlay','raster','$',
  'removeUnderlay','rasterInfo','requestDraw',
  source.slice(start,end)+';return setMapEPSG;')(
    state,underlay,raster,id=>inputs[id],
    ()=>{removed++;underlay.enabled=false;},
    msg=>{info=msg;},
    ()=>{redraw++});
select('2180');
assert.equal(state.mapEPSG,'2180');
assert.ok(Object.values(inputs).every(x=>x.value==='2180'));
assert.equal(removed,1);
assert.match(info,/Rastry z wizualną/);
assert.equal(raster.boundEPSG,'2180');
select('2180');
assert.equal(redraw,1);
select('9999');
assert.equal(state.mapEPSG,'2180');
select('2177');
assert.equal(state.mapEPSG,'2177');
assert.equal(raster.boundEPSG,'2177');
assert.ok(Object.values(inputs).every(x=>x.value==='2177'));
"""
    output=subprocess.run([node,"-e",script],cwd=STATIC,
       capture_output=True,text=True,timeout=20)
    assert output.returncode==0,output.stdout+output.stderr
