"""Magnes przy kalibracji rastra: osie, przesuwanie punktów, podgląd węzła."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def test_snap_uses_world_axes():
    """Magnes porównuje punkt świata (wschód, -północ) z geometrią obiektów."""
    assert "function gcpSnapPoint(world,altKey){" in JS
    assert "const snapped=gcpSnapPoint(world,ev.altKey);" in JS
    # przeliczenie na współrzędne GCP: x = północ, y = wschód
    assert "x:-snapped.point.y,y:snapped.point.x" in JS


def test_dragging_a_point_defines_the_screen_point():
    """Wcześniej brakowało `p`, więc przeciąganie rzucało ReferenceError."""
    start = JS.index("function moveGcpMapPoint(ev){")
    block = JS[start:start + 900]
    assert "const p=eventCoords(ev);" in block
    assert "Object.assign(raster.gcps[drag.index]," in block


def test_hit_radius_is_generous():
    assert "best=18*18;" in JS


def test_snap_preview_is_drawn():
    assert "function gcpHoverSnap(ev){" in JS
    assert "gcpView.hoverSnap=target;" in JS
    assert 'ctx.strokeStyle="#ffbc57";ctx.lineWidth=1.8;ctx.stroke();' in JS


@pytest.mark.skipif(NODE is None, reason="brak node")
def test_snap_pulls_the_click_to_the_nearest_vertex():
    script = r"""
const state={scale:1.0,features:[{id:"a",code:"5310",bbox:[0,-1000,1000,0],
  geometry:[[[500,-500],[520,-500],[520,-520],[500,-520],[500,-500]]]}]};
const GCP_SNAP_PX=26;
function gcpSnapPoint(world,altKey){
  if(altKey)return {point:world,kind:null};
  const radius=GCP_SNAP_PX/state.scale;let best=null;
  for(const f of state.features){const b=f.bbox;
    if(world.x<b[0]-radius||world.x>b[2]+radius||
       world.y<b[1]-radius||world.y>b[3]+radius)continue;
    for(const part of f.geometry||[])for(const point of part){
      const dist=Math.hypot(point[0]-world.x,point[1]-world.y);
      if(dist<=radius&&(!best||dist<best.dist))
        best={dist,point:{x:point[0],y:point[1]},kind:"węzeł"};}}
  return best?{point:best.point,kind:best.kind}:{point:world,kind:null};}
const snapped=gcpSnapPoint({x:528,y:-512},false);
console.log(JSON.stringify({kind:snapped.kind,point:snapped.point,
  gcp:{x:-snapped.point.y,y:snapped.point.x},
  alt:gcpSnapPoint({x:528,y:-512},true).kind}));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["kind"] == "węzeł"
    assert data["point"] == {"x": 520, "y": -520}
    assert data["gcp"] == {"x": 520, "y": 520}
    assert data["alt"] is None            # Alt wyłącza magnes
