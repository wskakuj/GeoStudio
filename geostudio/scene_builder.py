"""Builds the QGraphicsScene for a GEO-MAP document.

Extracted verbatim from ``GeoStudioWindow.rebuild_scene`` in v0.14.0 so that
scene construction can be tested and changed without touching the window
class. Nothing here knows about menus, docks or selection state: the caller
passes a :class:`RenderContext` describing which libraries and overrides to
use, and receives a :class:`SceneBuildResult` with every lookup table the
window needs afterwards.

Rendering is deliberately unchanged by this move. Order of item creation,
stacking values, pen and brush construction, label data keys and tooltip text
are byte-for-byte the same as before.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainterPath, QPen, QTextOption
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem,
                               QGraphicsPathItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsTextItem)

from .geomap import GeoMap, GeoObject, resolve_layer
from .geometry_index import GeometryIndex
from .library_render import (cdf_for_object, lay_for_code, native_fill_color,
                             object_sym_line_pattern, simple_point_circles,
                             simple_point_segments)
from .map_layout import label_ratio, text_line_offset

@dataclass(frozen=True)
class RenderContext:
    """Everything the renderer reads from the window, passed explicitly."""

    catalog: dict[str, str] = field(default_factory=dict)
    symbols: dict[str, str] = field(default_factory=dict)
    cdf_styles: dict[str, Any] = field(default_factory=dict)
    lay_pen_styles: dict[str, Any] = field(default_factory=dict)
    sym_primitives: dict[str, Any] = field(default_factory=dict)
    sym_line_patterns: dict[str, Any] = field(default_factory=dict)
    visual_styles: dict[str, Any] = field(default_factory=dict)
    default_fill_opacity: int = 100
    label_positions: dict[str, Any] = field(default_factory=dict)
    compilation_scale: float = 1000.0
    source_compilation_scale: float = 1000.0
    hide_multipart_connectors: bool = True

@dataclass
class SceneBuildResult:
    """Lookup tables the window keeps after a rebuild."""

    geometry_index: GeometryIndex
    layer_for_uid: dict[str, str] = field(default_factory=dict)
    graphics_for_uid: dict[str, Any] = field(default_factory=dict)
    fill_items_for_uid: dict[str, Any] = field(default_factory=dict)
    items_by_layer: dict[str, list] = field(default_factory=lambda: defaultdict(list))
    labels: list = field(default_factory=list)
    label_items: dict[tuple[str, str], Any] = field(default_factory=dict)
    label_world_span: dict[str, float] = field(default_factory=dict)

def object_path(obj: GeoObject, points_override=None, *, hide_connectors: bool = False) -> QPainterPath:
    points = points_override if points_override is not None else [(p.x, p.y) for p in obj.points]
    if not points:
        return QPainterPath()
    path = QPainterPath(QPointF(points[0][0], -points[0][1]))
    previous = obj.points[0] if obj.points else None
    for i, (x, y) in enumerate(points[1:], 1):
        if (hide_connectors and points_override is None and previous is not None
                and previous.point_type == 0):
            path.moveTo(x, -y)
        else:
            path.lineTo(x, -y)
        if points_override is None:
            previous = obj.points[i]
    return path

def label_anchor(obj: GeoObject):
    """Area centroid for closed geometry, midpoint for other paths."""
    pts = obj.points[:-1] if obj.is_closed else obj.points
    if not pts:
        return None
    if not obj.is_closed or len(pts) < 3:
        return (sum(p.x for p in pts)/len(pts), sum(p.y for p in pts)/len(pts))
    x0, y0 = pts[0].x, pts[0].y
    double_area, cx, cy = 0.0, 0.0, 0.0
    for i, a in enumerate(pts):
        b = pts[(i+1) % len(pts)]
        ax, ay, bx, by = a.x-x0, a.y-y0, b.x-x0, b.y-y0
        cross = ax*by - bx*ay
        double_area += cross
        cx += (ax+bx)*cross
        cy += (ay+by)*cross
    if abs(double_area) < 1e-10:
        return (sum(p.x for p in pts)/len(pts), sum(p.y for p in pts)/len(pts))
    return (x0 + cx/(3*double_area), y0 + cy/(3*double_area))

def object_fill_brush(obj: GeoObject, ctx: RenderContext, *, cdf=None) -> QBrush:
    """Resolve UID override > code override > natural fill, retaining hatch.

    Default alpha is 100% in the plain map, but the window passes 60% when
    an orthophoto/raster is beneath the vectors so imagery remains visible.
    The original source style/colour is never changed.
    """
    # Native land-use exception: 5230 with A1=dr/droga is a road and
    # must have no fill, even if a whole-code tint is configured. The
    # geometry and border remain visible, and original MAP is unchanged.
    land_use = obj.fields.get('A1', '').strip().casefold()
    if obj.code == '5230' and land_use in {'dr', 'droga'}:
        return QBrush(Qt.NoBrush)
    if cdf is None:
        cdf = cdf_for_object(ctx.cdf_styles, obj.code,
                             obj.fields.get('A1', ''), obj.fields.get('A2', ''))
    explicit = ctx.visual_styles.get(obj.uid)
    if explicit:
        color = QColor(explicit['fill'])
        color.setAlpha(round(explicit['opacity'] * 255 / 100))
        return QBrush(color)

    per_code = ctx.visual_styles.get('code:' + obj.code, {})
    opacity = per_code.get('opacity', ctx.default_fill_opacity)
    native = native_fill_color(obj.style)
    if 'fill' in per_code:
        color = QColor(per_code['fill'])
    elif obj.code == '5230' and land_use.startswith('ls'):
        color = QColor('#3D9A62')
        # Forest land-use stays translucent even without any WMS. A manual
        # per-code opacity override still has priority over this default.
        if 'opacity' not in per_code:
            opacity = 40
    elif native:
        color = QColor(*native)
    elif cdf:
        color = QColor(*cdf.fill)
    else:
        return QBrush(Qt.NoBrush)
    color.setAlpha(round(max(0, min(100, opacity)) * 255 / 100))

    if native or cdf is None or (obj.code == '5230' and land_use.startswith('ls')):
        return QBrush(color)
    hatch = {0: Qt.SolidPattern,
             1: Qt.Dense4Pattern, 2: Qt.Dense5Pattern,
             3: Qt.HorPattern, 4: Qt.VerPattern,
             5: Qt.CrossPattern, 6: Qt.BDiagPattern,
             7: Qt.FDiagPattern, 8: Qt.DiagCrossPattern}.get(
                 cdf.hatch, Qt.SolidPattern)
    return QBrush(color, hatch)


def build_scene(scene: QGraphicsScene, doc: GeoMap, ctx: RenderContext) -> SceneBuildResult:
    """Populate ``scene`` from ``doc`` exactly as v0.14.0 did, and return the tables."""
    result = SceneBuildResult(geometry_index=GeometryIndex(()))

    scene.clear()
    result.geometry_index = GeometryIndex(doc.objects, hide_connectors=ctx.hide_multipart_connectors)
    result.layer_for_uid = {}
    result.graphics_for_uid = {}
    result.fill_items_for_uid = {}
    result.items_by_layer = defaultdict(list)
    result.labels = []
    result.label_items = {}
    result.label_world_span = {}
    
    for obj in doc.objects:
        if not obj.points:
            continue
        layer = resolve_layer(ctx.catalog, obj.code)
        result.layer_for_uid[obj.uid] = layer
        # Preserve GEO-MAP COLORREF for stroke; CDF can override
        # fill and border on exact code/attribute variants.
        color = QColor(*obj.colorref)
        cdf = cdf_for_object(ctx.cdf_styles, obj.code,
                             obj.fields.get('A1',''), obj.fields.get('A2',''))
        if cdf:
            border = QColor(*cdf.border)
            if cdf.border != (0,0,0):
                color = border
        pen = QPen(color)
        pen.setCosmetic(True)
        lay_style = lay_for_code(ctx.lay_pen_styles, obj.code)
        # GEO-MAP's SYM macros define real dash/gap ratios:
        # *4002 (1,-1), *4003 (2,-1), O 4003 in 5220, O 4002 in 5230.
        # Resolve that definition first, then approximate LAY fallback.
        sym_dash = object_sym_line_pattern(
            ctx.sym_primitives, ctx.sym_line_patterns, obj.code)
        if sym_dash:
            pen.setStyle(Qt.CustomDashLine)
            pen.setDashPattern([max(.5, sym_dash[0]*3),
                                max(.5, sym_dash[1]*3)])
        elif sym_dash is None and lay_style and lay_style.line_id.endswith('.008'):
            pen.setStyle(Qt.DashLine)
        # Device-pixel width is independent from the map's zoom.
        # Use the CDF border weight when present; protect against
        # excessively wide vendor pen settings.
        pen.setWidthF(min(3.0, max(0.8, cdf.width)) if cdf and cdf.width > 0 else 1.0)
        fill_brush = object_fill_brush(obj, ctx, cdf=cdf)

        if len(obj.points) == 1:
            # SYM full-circle A instructions describe boundary markers.
            # Draw actual double rings instead of thousands of generic,
            # oversized black dots on every surveyed boundary.
            primitives = ctx.sym_primitives.get(obj.code, [])
            segments = simple_point_segments(primitives)
            circles = simple_point_circles(primitives)
            if segments or circles:
                point_path = QPainterPath()
                for x1,y1,x2,y2 in segments:
                    point_path.moveTo(x1 * 5, -y1 * 5)
                    point_path.lineTo(x2 * 5, -y2 * 5)
                for cx,cy,radius in circles:
                    radius_px=radius*5
                    point_path.addEllipse(QPointF(cx*5,-cy*5),
                                          radius_px,radius_px)
                item = QGraphicsPathItem(point_path)
            else:
                # Fallback is deliberately smaller than the old 5 px disc.
                item = QGraphicsEllipseItem(-1.0,-1.0,2.0,2.0)
                item.setBrush(QBrush(color))
            item.setPos(obj.points[0].x, -obj.points[0].y)
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
            item.setZValue(250)
        else:
            path = object_path(obj,hide_connectors=ctx.hide_multipart_connectors)
            item = QGraphicsPathItem(path)
            item.setBrush(QBrush(Qt.NoBrush))
            # All boundary lines are placed ABOVE every filled polygon.
            # Parcel boundaries must stay visible even under opaque
            # forestry / land-use polygons, irrespective of object order.
            item.setZValue(220 if obj.code=='5214' else
                           180 if obj.code=='5216' else
                           130 if obj.code in {'5220','5230'} else 100)
            parts = obj.display_parts
            is_multipart_area = bool(parts) and all(
                len(part) >= 4 and (part[0].x,part[0].y) ==
                (part[-1].x,part[-1].y) for part in parts)
            if obj.is_closed or is_multipart_area:
                # The 5200 triangular objects with FA=0 form the black
                # quarters of the map's compass rose. Do not fill all
                # 5200 legends/boxes: only the explicit source triangles.
                if (obj.code == '5200' and len(obj.points)==4
                        and obj.fields.get('FA')=='0'):
                    fill_brush=QBrush(QColor('#111111'))
                fill_item = QGraphicsPathItem(path)
                fill_item.setBrush(fill_brush)
                fill_item.setPen(QPen(Qt.NoPen))
                # Independent fill stage; never paint parcel strokes over
                # the wrong RGB just because a later feature comes next.
                fill_item.setZValue(-100)
                fill_item.setAcceptedMouseButtons(Qt.NoButton)
                fill_item.setData(0,obj.uid or f'index:{obj.start}')
                scene.addItem(fill_item)
                result.items_by_layer[layer].append(fill_item)
                if obj.uid:
                    result.fill_items_for_uid[obj.uid] = fill_item
        # Text-only map annotation codes carry a P-to-P baseline,
        # not a printed line. Drawing that baseline caused long black
        # strokes through the title, legend and agency captions.
        if obj.code in {'6900','7900','6000','6301'} and obj.fields.get('TX'):
            pen=QPen(Qt.NoPen)
        item.setPen(pen)
        # We handle picking ourselves; Qt's default selection draws an
        # unwanted bounding RECTANGLE instead of the exact contour.
        item.setAcceptedMouseButtons(Qt.NoButton)
        item.setData(0, obj.uid or f'index:{obj.start}')
        item.setToolTip(
            f'Kod {obj.code} • {ctx.symbols.get(obj.code,layer)}\\n'
            f'{obj.fields.get("A2","")}')
        scene.addItem(item)
        result.items_by_layer[layer].append(item)
        if obj.uid:
            result.graphics_for_uid[obj.uid] = item
        # Compose annotations only from source records. 6900 stores
        # directional letters / map-sheet numbers (N/S/E/W/1/2/3).
        # 7900 stores map title, legend headings and agency names;
        # 6000/6301 store the textual legend. These objects provide two
        # P anchors, NOT strokes: render the text, not their baseline.
        labels = []
        if obj.code == '5310':
            labels = [(field,obj.fields[field]) for field in ('A1','A2')
                      if obj.fields.get(field)]
        elif obj.code in {'5216','5220','5230'} and obj.fields.get('A2'):
            labels = [('A2',obj.fields['A2'])]
        elif obj.code == '5214' and obj.fields.get('A3'):
            # The precinct title is a source attribute, not invented text.
            labels = [('A3',obj.fields['A3'])]
        elif obj.code in {'6900','7900','6000','6301'} and obj.fields.get('TX'):
            texts = [v.strip() for v in obj.fields['TX'].split('||') if v.strip()]
            labels = [(f'TX{index}',line) for index,line in enumerate(texts)]
        elif obj.code.startswith('7') and obj.fields.get('TX'):
            labels = [('TX',obj.fields['TX'].replace('||',' '))]
        custom_config = ctx.visual_styles.get("labels:code:" + obj.code)
        if isinstance(custom_config, dict) and isinstance(
                custom_config.get("fields"), dict):
            custom_fields = custom_config["fields"]
            labels = [
                (field, obj.fields[field].replace("||", "\n"))
                for field, opts in custom_fields.items()
                if opts.get("visible") and obj.fields.get(field)
            ]
        if not labels:
            continue
        anchor = label_anchor(obj)
        if anchor is None:
            continue
        if obj.uid and obj.points:
            xs = [pt.x for pt in obj.points]
            ys = [pt.y for pt in obj.points]
            result.label_world_span[obj.uid] = max(
                max(xs) - min(xs), max(ys) - min(ys))
        line_count=len(labels)
        for line_index, (field,content) in enumerate(labels):
            # GEO-MAP uses a vertical bar in building A2 to separate lines:
            # e.g. "Ol75|II-0.5" is two stacked rows, not literal text.
            # Keep the whole A2 as *one* graphics item so dragging it and
            # storing a sidecar position move both rows together.
            multiline_a2 = obj.code == '5310' and field == 'A2' and '|' in content
            if multiline_a2:
                label = QGraphicsTextItem()
                label.setPlainText(content.replace('|', '\n'))
                label.document().setDocumentMargin(0)
                label.document().setDefaultTextOption(QTextOption(Qt.AlignHCenter))
            else:
                label = QGraphicsSimpleTextItem(content)
            font = QFont('Segoe UI')
            ratio = .55
            if obj.code == '5310':
                font.setPixelSize(16)
                font.setBold(True)
                color=QColor('#CC202C')
            elif obj.code == '5216':
                font.setPixelSize(12)
                color=QColor('#4A5056')
            elif obj.code in {'5220','5230'}:
                font.setPixelSize(11)
                color=QColor('#35753A')
                color.setAlpha(190)
            elif obj.code == '5214':
                font.setPixelSize(14)
                color=QColor('#213B8F')
            elif obj.code in {'6900','7900','6000','6301'}:
                font.setPixelSize(24)
                if obj.code in {'7900','6900'}:
                    font.setFamily('Times New Roman')
                    font.setBold(True)
                else:
                    font.setFamily('Segoe UI')
                color=QColor('#111111')
                # A1 height is in the map's coordinate units. In v0.13
                # it was MULTIPLIED by 2.1, so independent title rows
                # overlapped even though their geographic P anchors
                # were correct. Set the drawn glyph's actual height to
                # A1 instead; compilation scale controls an independent
                # magnification factor for map presentation.
            else:
                font.setPixelSize(11)
                color=QColor('#58686F')
                color.setAlpha(180)
            if custom_config:
                specific = custom_config.get("fields", {}).get(field, {})
                if specific:
                    font.setFamily(specific.get("font", "Segoe UI"))
                    font.setPixelSize(max(6, min(96, int(specific.get("size", 16)))))
                    font.setBold(bool(specific.get("bold", False)))
                    color = QColor(specific.get("color", "#243A45"))
                    if not color.isValid():
                        color = QColor("#243A45")
            label.setFont(font)
            if multiline_a2:
                label.setDefaultTextColor(color)
            else:
                label.setBrush(QBrush(color))
            label.setAcceptedMouseButtons(Qt.NoButton)
            bounds=label.boundingRect()
            ratio=label_ratio(obj.code,obj.fields,bounds.height(),
                              ctx.compilation_scale,
                              ctx.source_compilation_scale)
            if custom_config and custom_config.get("fields", {}).get(field):
                # Use a fixed map ratio so custom font pixel sizes remain
                # visible even on 6000/7900 texts where native A1 size is fixed.
                ratio = .55 * ctx.compilation_scale / ctx.source_compilation_scale
            custom=ctx.label_positions.get(obj.uid,{}).get(field)
            x,y = custom if custom else anchor
            label.setPos(x,-y)
            # Screen-direction offsets are expressed in font pixels.
            # Their real-world displacement scales with the map.
            offset=0.
            if not custom and obj.code=='5310':
                offset= (-bounds.height()*.6 if field=='A1'
                         else bounds.height()*.6)
            elif obj.code in {'7900','6000','6301'} and not custom:
                offset=text_line_offset(line_index,line_count,bounds.height())
            label.setData(0,obj.uid)
            label.setData(1,field)
            label.setData(2,offset)
            label.setData(3,ratio)
            label.setData(4,ratio/(ctx.compilation_scale/ctx.source_compilation_scale))
            label.setZValue(1300)
            scene.addItem(label)
            result.items_by_layer[layer].append(label)
            result.labels.append(label)
            result.label_items[(obj.uid,field)] = label
    return result
