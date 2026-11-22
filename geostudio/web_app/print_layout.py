"""Vector PDF print sheets for GeoStudio MAP, including A0/A1 and editable furniture.

Only view-derived feature geometry is used; never modify original MAP bytes.
Page size and map scale are in millimetres and real metres, respectively.
"""
from __future__ import annotations

from io import BytesIO
from math import isfinite, log10, floor
from pathlib import Path
from typing import Iterable
import re

from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas


MM = 72.0 / 25.4
PAPERS = {"A0": (841, 1189), "A1": (594, 841), "A2": (420, 594),
          "A3": (297, 420), "A4": (210, 297)}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _font() -> str:
    """Use an installed Unicode font; never bundle proprietary font bytes."""
    for path in (
        r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ):
        if Path(path).is_file():
            try:
                if "GeoStudioUnicode" not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont("GeoStudioUnicode", path))
                return "GeoStudioUnicode"
            except Exception:
                continue
    return "Helvetica"


def _rgb(value: str, default="#354b59"):
    return colors.HexColor(value if isinstance(value, str) and HEX.fullmatch(value)
                           else default)


def _text(value, length=120) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()[:length]


def _fit(c, label: str, x: float, y: float, width: float, size: float,
         font: str):
    if width <= 2 or not label:
        return
    if pdfmetrics.stringWidth(label,font,size)>width:
        suffix="…" if pdfmetrics.stringWidth("…",font,size)<width else ""
        while label and pdfmetrics.stringWidth(label+suffix,font,size)>width:
            label=label[:-1]
        label=label+suffix if label else ""
    if label:c.drawString(x,y,label)


def _setup(opts: dict):
    bounds = opts.get("bounds")
    if (not isinstance(bounds, list) or len(bounds) != 4 or
        any(type(v) not in (int, float) or not isfinite(v) for v in bounds) or
        bounds[2] <= bounds[0] or bounds[3] <= bounds[1]):
        raise ValueError("Nieprawidłowe granice arkusza.")
    denominator = opts.get("denominator")
    if type(denominator) not in (int, float) or not 10 <= denominator <= 100000000:
        raise ValueError("Skala poza dozwolonym zakresem.")
    paper = opts.get("paper", "A3")
    if paper not in ("auto", *PAPERS):
        raise ValueError("Nieznany format papieru.")
    orientation = opts.get("orientation", "landscape")
    if orientation not in ("landscape", "portrait"):
        raise ValueError("Nieznana orientacja arkusza.")
    frame_width = opts.get("frameWidthMm", 0.3)
    if type(frame_width) not in (int, float) or not isfinite(frame_width) or not 0.1 <= frame_width <= 2.5:
        raise ValueError("Grubość ramki: 0,1–2,5 mm.")
    frame_color = opts.get("frameColor", "#263c4d")
    if not isinstance(frame_color, str) or not HEX.fullmatch(frame_color):
        raise ValueError("Kolor ramki musi mieć postać #RRGGBB.")
    legend = opts.get("legendRows", [])
    table = opts.get("tableRows", [])
    if (not isinstance(legend, list) or len(legend) > 40 or
        not isinstance(table, list) or len(table) > 8):
        raise ValueError("Za dużo pozycji legendy lub tabeli.")
    for item in legend:
        if (not isinstance(item, dict) or len(_text(item.get("name"), 70)) > 0 and
            not HEX.fullmatch(str(item.get("color", "")))):
            raise ValueError("Legenda: oczekiwano nazwy i koloru #RRGGBB.")
    for item in table:
        if not isinstance(item, dict):
            raise ValueError("Tabela musi zawierać pary opis–wartość.")
    # Bez wpisanego tytułu arkusz nie ma nagłówka — nie wstawiamy domyślnego.
    title = _text(opts.get("title", ""), 100)
    show_legend = opts.get("showLegend", True) is True and len(legend) > 0
    legend_mm = 55 if show_legend else 0
    head_mm, footer_mm, margin_mm = 20, max(22, 9 + len(table)*8), 13
    map_w_mm = (bounds[2] - bounds[0]) * 1000 / denominator
    map_h_mm = (bounds[3] - bounds[1]) * 1000 / denominator
    needed_w = map_w_mm + margin_mm*2 + legend_mm
    needed_h = map_h_mm + head_mm + footer_mm
    if paper == "auto":
        page_w_mm = max(120, needed_w)
        page_h_mm = max(120, needed_h)
    else:
        a, b = PAPERS[paper]
        page_w_mm, page_h_mm = (max(a,b),min(a,b)) if orientation == "landscape" else (min(a,b),max(a,b))
        if needed_w > page_w_mm+0.01 or needed_h > page_h_mm+0.01:
            raise ValueError("Obszar mapy przy wybranej skali nie mieści się na " +
                paper + ". Zwiększ mianownik skali lub wybierz mniejszy zakres.")
    if page_w_mm > 1700 or page_h_mm > 1700:
        raise ValueError("Arkusz przekracza 1700 mm. Wybierz odpowiedni format/skale.")
    # Center the whole block, preserving map and print scale.
    extra_x = (page_w_mm - needed_w) / 2
    extra_y = (page_h_mm - needed_h) / 2
    return {
        "bounds": bounds, "denominator": denominator,
        "page": (page_w_mm*MM,page_h_mm*MM),
        "map": ((extra_x+margin_mm)*MM,(extra_y+footer_mm)*MM,
                map_w_mm*MM,map_h_mm*MM),
        "legendStart": (extra_x+margin_mm+map_w_mm+7)*MM,
        "legendWidth": max(0,(legend_mm-10)*MM),
        "top": (extra_y+footer_mm+map_h_mm)*MM,
        "footer": extra_y*MM, "extra_x":extra_x*MM,
        "margin":margin_mm*MM, "head_mm":head_mm,
        "title":title, "legend":legend if show_legend else [],
        "table":table, "frame":opts.get("frame",True) is True,
        "frameColor": frame_color, "frameWidth": frame_width*MM,
        "north":opts.get("north",True) is True,
        "scaleBar":opts.get("scaleBar",True) is True,
        "font":_font(),
    }



def _bold_font() -> str:
    """Register a matching bold Unicode face when the system provides one."""
    for path in (
        r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ):
        if Path(path).is_file():
            try:
                if "GeoStudioUnicodeBold" not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont("GeoStudioUnicodeBold", path))
                return "GeoStudioUnicodeBold"
            except Exception:
                continue
    return _font()


def _pdf_label_size(label: dict, options: dict) -> float:
    """Match the map's world-sized captions at the selected print scale."""
    source = float(options.get("sourceCompilationScale") or 5000)
    compilation = float(options.get("compilationScale") or source)
    if not isfinite(source) or not isfinite(compilation) or source <= 0 or compilation <= 0:
        source = compilation = 5000
    ratio = max(.1, min(10, compilation / source))
    base = max(8, min(36, float(label.get("size") or 16)))
    styled = round(max(8, min(40, base * ratio)) * 10) / 10
    # Canvas: styled * 2500 * .0254 / 96 world metres.
    # PDF: page points per world metre = 72 / (.0254 * denominator).
    # Keep this conversion in physical points, not raster DPI.
    return max(1, min(40, styled * 2500 * 72 / (96 * options["denominator"])))


def _draw_pdf_labels(c, features: list[dict], options: dict, layout: dict, point) -> None:
    """Canvas-like centered, stacked, collision-aware vector annotations.

    Map labels are anchored at their native X/Y (including saved manual
    positions). A1 and A2 of 5310 are independent, mandatory descriptions;
    other captions are suppressed when their boxes collide with another
    feature, exactly as on the browser map. Collisions are indexed in cells
    to avoid comparing every text label with every previous label.
    """
    left, bottom, width, height = layout["map"]
    xmin, ymin, xmax, ymax = layout["bounds"]
    denominator = options["denominator"]
    pixels_per_metre = 300 / (.0254 * denominator)
    regular_font = layout["font"]
    bold_font = _bold_font()
    cell_size = 16.0
    collision_cells: dict[tuple[int, int], list[tuple[str, tuple[float, ...]]]] = {}
    painted = 0

    def cells(rect):
        x0 = max(0, floor((rect[0] - left) / cell_size))
        x1 = min(floor(width / cell_size), floor((rect[2] - left) / cell_size))
        y0 = max(0, floor((rect[1] - bottom) / cell_size))
        y1 = min(floor(height / cell_size), floor((rect[3] - bottom) / cell_size))
        for a in range(x0, x1 + 1):
            for b in range(y0, y1 + 1):
                yield a, b

    def collides(fid, rect):
        seen = set()
        for key in cells(rect):
            for other in collision_cells.get(key, ()):
                if id(other) in seen:
                    continue
                seen.add(id(other))
                other_fid, box = other
                if (fid != other_fid and box[0] < rect[2] and
                        box[2] > rect[0] and box[1] < rect[3] and
                        box[3] > rect[1]):
                    return True
        return False

    def register(fid, rect):
        entry = (fid, rect)
        for key in cells(rect):
            collision_cells.setdefault(key, []).append(entry)

    def priority(feature):
        code = feature.get("code")
        if code == "5310":
            return 0
        if code in ("7900", "6000", "6301", "6900"):
            return 1
        if code == "5216":
            return 2
        return 3

    for feature in sorted(features, key=priority):
        labels = feature.get("labels") or []
        if not labels:
            continue
        code = feature.get("code")
        sheet = code in ("7900", "6900", "6000", "6301")
        bbox = feature.get("bbox") or ()
        if len(bbox) == 4 and not sheet and code != "5310":
            box_w = abs(bbox[2] - bbox[0]) * pixels_per_metre
            box_h = abs(bbox[3] - bbox[1]) * pixels_per_metre
            if max(box_w, box_h) < 32 or min(box_w, box_h) < 8:
                continue
        sizes = {id(label): _pdf_label_size(label, options) for label in labels}
        stack = [label for label in labels
                 if code == "5310" and not label.get("manuallyPlaced")]
        stack_heights = {}
        total_height = 0.0
        for label in stack:
            line_count = len(str(label.get("text") or "").split("\n")[:6])
            item_height = line_count * sizes[id(label)] * 1.20
            stack_heights[id(label)] = (total_height + item_height / 2, item_height)
            total_height += item_height
        for label in labels:
            mandatory = code == "5310" and label.get("field") in ("A1", "A2")
            if not mandatory and painted >= 8000:
                continue
            value = str(label.get("text") or "").replace("\r", "")[:220]
            if not value:
                continue
            lines = [line[:100] for line in value.split("\n")[:6]]
            size = sizes[id(label)]
            label_font = bold_font if label.get("bold") else regular_font
            widths = [pdfmetrics.stringWidth(line, label_font, size) for line in lines]
            line_height = len(lines) * size * 1.20
            if id(label) in stack_heights:
                offset = stack_heights[id(label)][0] - total_height / 2
            elif label.get("manuallyPlaced"):
                offset = 0
            else:
                offset = float(label.get("offset") or 0) * (size / (float(label.get("size") or 16)))
            x, anchor_y = point((float(label.get("x") or 0), float(label.get("y") or 0)))
            cy = anchor_y - offset
            if x < left or x > left + width or anchor_y < bottom or anchor_y > bottom + height:
                continue
            padding = 3 * 72 / 300
            max_width = max(widths, default=0)
            rect = (x - max_width / 2 - padding, cy - line_height / 2 - padding,
                    x + max_width / 2 + padding, cy + line_height / 2 + padding)
            if (rect[2] < left or rect[0] > left + width or
                    rect[3] < bottom or rect[1] > bottom + height):
                continue
            if not mandatory and collides(str(feature.get("id")), rect):
                continue
            register(str(feature.get("id")), rect)
            c.setFillColor(_rgb(label.get("color", "#4A5056")))
            c.setFont(label_font, size)
            for index, line in enumerate(lines):
                baseline = cy + line_height / 2 - size - index * size * 1.20
                c.drawCentredString(x, baseline, line)
            painted += 1


def _sheet_font(family, bold, italic, default):
    if not family and not bold and not italic:
        return default
    families={
        "Arial": ("arial","LiberationSans","Helvetica"),
        "Verdana": ("verdana","DejaVuSans","Helvetica"),
        "Times New Roman": ("times","LiberationSerif","Times"),
        "Georgia": ("georgia","DejaVuSerif","Times"),
        "Courier New": ("cour","LiberationMono","Courier"),
    }
    win,linux,standard=families.get(family,families["Arial"])
    variant=("Bold" if bold else "")+("Italic" if italic else "")
    name="Sheet"+win+(variant or "Regular")
    if name in pdfmetrics.getRegisteredFontNames():return name
    suffix=("z" if bold and italic else "b" if bold else "i" if italic else "")
    if win=="arial":suffix={"b":"bd","z":"bi"}.get(suffix,suffix)
    if win=="cour":suffix={"b":"bd","z":"bi"}.get(suffix,suffix)
    if win in ("georgia","times","verdana") and bold and italic:suffix="z"
    if win=="times" and bold and italic:suffix="bi"
    if win=="times" and bold and not italic:suffix="bd"
    alt=(variant or "Regular")
    if linux=="DejaVuSans":alt=alt.replace("Italic","Oblique")
    files=[Path("C:/Windows/Fonts")/(win+suffix+".ttf"),
           Path("/usr/share/fonts/truetype/liberation2")/(linux+"-"+alt+".ttf"),
           Path("/usr/share/fonts/truetype/dejavu")/(linux+("-"+alt if variant else "")+".ttf")]
    for path in files:
        if path.is_file():
            pdfmetrics.registerFont(TTFont(name,str(path)))
            return name
    if standard=="Times":return "Times-"+(variant or "Roman")
    return standard+("-"+variant.replace("Italic","Oblique") if variant else "")


def _sheet_inserts(c, inserts, point, per_m, font):
    if not isinstance(inserts,list) or len(inserts)>100:
        raise ValueError("Zbyt wiele elementów arkusza.")
    def number(value):
        if type(value) not in (float,int) or not isfinite(value) or abs(value)>1e9:
            raise ValueError("Nieprawidłowy wymiar elementu.")
        return value
    for item in inserts:
        if not isinstance(item,dict):
            raise ValueError("Nieprawidłowy element arkusza.")
        x,y=point([number(item.get(k)) for k in ("x","y")])
        size=item.get("size")
        if not isinstance(size,list) or len(size)!=2 or min(map(number,size))<=0:
            raise ValueError("Nieprawidłowe proporcje elementu.")
        shapes=item.get("shapes")
        if not isinstance(shapes,list) or len(shapes)>1800:
            raise ValueError("Nieprawidłowe oznaczenia w legendzie.")
        c.saveState()
        c.translate(x,y)
        c.scale(number(item.get("w"))*per_m/size[0],number(item.get("h"))*per_m/size[1])
        c.setLineWidth(.65)
        for s in shapes:
            if not isinstance(s,dict):
                raise ValueError("Nieprawidłowy znak.")
            if "text" in s:
                c.setFillColor(colors.HexColor("#202020"))
                c.setFont(_sheet_font(s.get("family"),s.get("bold"),s.get("italic"),font),number(s.get("size")))
                draw=c.drawCentredString if s.get("center") else c.drawString
                draw(number(s.get("x")),-number(s.get("y")),str(s.get("text",""))[:1500])
            else:
                pts=s.get("points")
                if not isinstance(pts,list) or not 2<=len(pts)<=32:
                    raise ValueError("Nieprawidłowy obrys znaku.")
                path=c.beginPath()
                for idx,pair in enumerate(pts):
                    if not isinstance(pair,list) or len(pair)!=2:
                        raise ValueError("Nieprawidłowy punkt znaku.")
                    (path.lineTo if idx else path.moveTo)(number(pair[0]),-number(pair[1]))
                if s.get("fill"):c.setFillColor(_rgb(s["fill"]))
                if s.get("stroke"):c.setStrokeColor(_rgb(s["stroke"]))
                c.drawPath(path,fill=int(bool(s.get("fill"))),stroke=int(bool(s.get("stroke"))))
        c.restoreState()


def render_vector_pdf(features: Iterable[dict], options: dict) -> bytes:
    """Render a true vector A0–A4/automatic layout; no 40MP Canvas limit."""
    o = _setup(options)
    features = list(features)
    if len(features) > 100000:
        raise ValueError("PDF obsługuje maksymalnie 100 000 obiektów na arkusz.")
    output=BytesIO()
    c=pdf_canvas.Canvas(output,pagesize=o["page"],pageCompression=1)
    c.setTitle(o["title"]);c.setAuthor("GeoStudio")
    font=o["font"]
    left,bottom,w,h=o["map"]
    xmin,ymin,xmax,ymax=o["bounds"]
    per_m=w/(xmax-xmin)
    point=lambda p:(left+(p[0]-xmin)*per_m,bottom+(ymax-p[1])*per_m)
    c.setFillColor(colors.white);c.rect(0,0,*o["page"],fill=1,stroke=0)
    c.saveState()
    clip=c.beginPath();clip.rect(left,bottom,w,h);c.clipPath(clip,stroke=0,fill=0)
    # Fill ALL polygons before drawing ANY border so adjoining parcel
    # outlines are not painted over by a later opaque polygon.
    for pass_ in ("fill","stroke","labels"):
        if pass_ == "labels":
            _draw_pdf_labels(c, features, options, o, point)
            continue
        for feature in features:
            style=feature.get("style") or {}
            closed=feature.get("closed") is True
            if pass_=="fill" and (not closed or not style.get("hasFill") or
                                   float(style.get("opacity",0)) <= 0):
                continue
            if pass_=="stroke" and not style.get("drawStroke",True):
                continue
            c.saveState()
            if pass_=="stroke":
                c.setStrokeColor(_rgb(style.get("stroke")))
                c.setLineWidth(max(.1,min(6,float(style.get("strokeWidth",1))*.75)))
                c.setLineCap(1);c.setLineJoin(1)
                dash=style.get("dash") or []
                if dash and all(isinstance(x,(int,float)) and x>0 for x in dash):
                    c.setDash([float(x)*.75 for x in dash[:8]])
            else:
                c.setFillColor(_rgb(style.get("fill")))
                if hasattr(c,"setFillAlpha"):
                    c.setFillAlpha(max(0,min(1,float(style.get("opacity",1)))))
            for part in feature.get("geometry") or []:
                if not part:continue
                if len(part)==1 and pass_=="stroke":
                    x,y=point(part[0]);c.circle(x,y,max(.3,float(style.get("pointSize",1))),fill=1,stroke=0)
                    continue
                p=c.beginPath()
                x,y=point(part[0]);p.moveTo(x,y)
                for coordinate in part[1:]:
                    x,y=point(coordinate);p.lineTo(x,y)
                if closed:p.close()
                c.drawPath(p,fill=1 if pass_=="fill" else 0,
                           stroke=1 if pass_=="stroke" else 0,fillMode=0)
            c.restoreState()
    _sheet_inserts(c, options.get("inserts",[]), point, per_m, font)
    c.restoreState()
    # Map and outer sheet frames are individually configurable.
    if o["frame"]:
        c.setStrokeColor(_rgb(o["frameColor"]))
        c.setLineWidth(o["frameWidth"]);c.rect(left,bottom,w,h,fill=0,stroke=1)
        c.setLineWidth(max(.3,o["frameWidth"]*.65))
        c.rect(o["margin"],o["margin"],
               o["page"][0]-2*o["margin"],o["page"][1]-2*o["margin"],
               fill=0,stroke=1)
    c.setFillColor(_rgb("#172c40"))
    c.setFont(font,14)
    _fit(c,o["title"],left,o["top"]+8*MM,w*.88,14,font)
    if o["north"]:
        nx=left+w-9*MM;ny=o["top"]+9*MM
        c.setFont(font,10);c.drawCentredString(nx,ny+5,"N")
        p=c.beginPath();p.moveTo(nx,ny+4);p.lineTo(nx-5,ny-8)
        p.lineTo(nx+5,ny-8);p.close()
        c.drawPath(p,fill=1,stroke=0)
    # Editable legend: labels and swatch colors are authored in the UI.
    if o["legend"]:
        lx=o["legendStart"]
        c.setFont(font,11);c.drawString(lx,o["top"]-14, "LEGENDA")
        for i,item in enumerate(o["legend"]):
            y=o["top"]-31-i*18
            if y<bottom+12:break
            c.setFillColor(_rgb(item["color"]))
            c.rect(lx,y-4,9,9,fill=1,stroke=0)
            c.setFillColor(_rgb("#22394c"))
            c.setFont(font,8)
            _fit(c,_text(item.get("name"),70),lx+13,y,o["legendWidth"]-15,8,font)
    if o["scaleBar"]:
        distance=(xmax-xmin)*.17
        magnitude=10**floor(log10(max(1e-8,distance)))
        dist=(next((v for v in (10,5,2,1) if v*magnitude<=distance),1))*magnitude
        length=dist*per_m
        cx=left+w/2-length/2; y=bottom-12
        c.setStrokeColor(_rgb("#263c4d"));c.setLineWidth(.5)
        for i in range(2):
            c.setFillColor(colors.black if i==0 else colors.white)
            c.rect(cx+i*length/2,y,length/2,5,stroke=1,fill=1)
        c.setFillColor(colors.black);c.setFont(font,7)
        c.drawString(cx,y+8,"0")
        c.drawCentredString(cx+length/2,y+8,f"{dist/2:g}")
        c.drawRightString(cx+length,y+8,f"{dist:g} m")
    # A simple editable title block table below the map, sized for A0-A4.
    table=o["table"]
    if table:
        x=left+w*.55;cell_w=w*.45;row_h=7*MM
        start=bottom-32
        for i,item in enumerate(table):
            yy=start-i*row_h
            if yy<o["margin"]+4:break
            c.setStrokeColor(_rgb("#6a7987"));c.setLineWidth(.4)
            c.rect(x,yy-row_h,cell_w,row_h,fill=0,stroke=1)
            split=x+cell_w*.35;c.line(split,yy-row_h,split,yy)
            c.setFillColor(_rgb("#22394c"));c.setFont(font,8)
            _fit(c,_text(item.get("label"),80),x+4,yy-row_h+6,cell_w*.33,8,font)
            _fit(c,_text(item.get("value"),120),split+4,yy-row_h+6,cell_w*.62,8,font)
    c.showPage();c.save()
    return output.getvalue()
