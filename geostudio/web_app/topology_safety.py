"""Pure-Python polygon contact/overlap predicates for safe GEO-MAP edits.

All coordinates are native (X northing, Y easting). A boundary touch is valid,
but positive interior overlap of the same polygon code is not. No dependencies.
"""
from __future__ import annotations

from math import hypot

EPS = 0.000001


def _close(a, b, tol=EPS):
    return hypot(a[0] - b[0], a[1] - b[1]) <= tol


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segment_distance(p, a, b):
    u, v = b[0]-a[0], b[1]-a[1]
    size = u*u + v*v
    t = max(0.0, min(1.0, ((p[0]-a[0])*u+(p[1]-a[1])*v)/size)) if size else 0.
    closest = (a[0]+u*t, a[1]+v*t)
    return hypot(p[0]-closest[0], p[1]-closest[1]), closest


def _segments(points):
    return zip(points, points[1:] + points[:1])


def _on_boundary(point, polygon, tolerance=EPS):
    return any(_segment_distance(point,a,b)[0] <= tolerance
               for a,b in _segments(polygon))


def _inside(point, polygon):
    """Strict interior: points on edges are explicitly NOT inside."""
    if _on_boundary(point, polygon):
        return False
    x,y=point
    hit=False
    for a,b in _segments(polygon):
        if (a[1]>y)!=(b[1]>y):
            at_x=a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1])
            if x<at_x:
                hit=not hit
    return hit


def _interior_point(polygon):
    """A point strictly inside a simple polygon, including concave rings."""
    n=len(polygon)
    if n<3:
        return None
    for k in range(n):
        a,b,c=(polygon[k],polygon[(k+1)%n],polygon[(k+2)%n])
        if abs(_cross(a,b,c))<=EPS:
            continue
        p=((a[0]+b[0]+c[0])/3,(a[1]+b[1]+c[1])/3)
        if _inside(p,polygon):
            return p
    return None


def _proper_intersection(a,b,c,d):
    # Touching endpoints and collinear shared edges are NOT area overlaps.
    a1=_cross(a,b,c);a2=_cross(a,b,d)
    b1=_cross(c,d,a);b2=_cross(c,d,b)
    return ((a1>EPS and a2 < -EPS or a1 < -EPS and a2>EPS) and
            (b1>EPS and b2 < -EPS or b1 < -EPS and b2>EPS))


def rings_overlap(a,b):
    """True for overlapping interiors; false for adjacent shared boundaries."""
    if len(a)<3 or len(b)<3:
        return False
    ax0=min(x for x,y in a);ax1=max(x for x,y in a)
    ay0=min(y for x,y in a);ay1=max(y for x,y in a)
    if ax1<=min(x for x,y in b)+EPS or max(x for x,y in b)<=ax0+EPS:
        return False
    if ay1<=min(y for x,y in b)+EPS or max(y for x,y in b)<=ay0+EPS:
        return False
    for s,t in _segments(a):
        for u,v in _segments(b):
            if _proper_intersection(s,t,u,v):
                return True
    if any(_inside(p,b) for p in a) or any(_inside(p,a) for p in b):
        return True
    # Coincident polygons and partly coincident boundaries: their vertices
    # can lie exclusively on the other ring, while interiors still overlap.
    p=_interior_point(a)
    if p and _inside(p,b):
        return True
    p=_interior_point(b)
    return bool(p and _inside(p,a))


def rings_contact(a,b,tolerance=0.0015):
    if len(a)<2 or len(b)<2:
        return False
    if any(_on_boundary(p,b,tolerance) for p in a):
        return True
    if any(_on_boundary(p,a,tolerance) for p in b):
        return True
    for s,t in _segments(a):
        for u,v in _segments(b):
            if _proper_intersection(s,t,u,v):
                return True
    return False


def ring_of(obj, dx=0.0, dy=0.0):
    """Only simple, single-piece, closed polygons can be translated here."""
    return [(round(p.x+dx,3),round(p.y+dy,3)) for p in obj.points[:-1]]


def nearest_boundary_snap(moving, fixed, dx, dy, tolerance):
    """Translate the WHOLE group to a close same-code edge, without overlap.

    Prefer candidates creating a shared EDGE (rather than a single-point
    touch). Never return a snap that would place any moved polygon inside
    another polygon of the same code.
    """
    fixed=[obj for obj in fixed if obj.is_closed]
    if not fixed or not moving:
        return dx,dy,None
    candidates={(round(dx,3),round(dy,3)):0.0}
    for obj in moving:
        for neighbor in fixed:
            if neighbor.code!=obj.code:
                continue
            ring=ring_of(neighbor)
            # Only search objects near the desired moved location.
            changed=ring_of(obj,dx,dy)
            if (max(x for x,y in changed)<min(x for x,y in ring)-tolerance or
                min(x for x,y in changed)>max(x for x,y in ring)+tolerance or
                max(y for x,y in changed)<min(y for x,y in ring)-tolerance or
                min(y for x,y in changed)>max(y for x,y in ring)+tolerance):
                continue
            for p in obj.points[:-1]:
                position=(p.x+dx,p.y+dy)
                for a,b in _segments(ring):
                    dist,target=_segment_distance(position,a,b)
                    if dist<=tolerance:
                        offset=(round(target[0]-p.x,3),
                                round(target[1]-p.y,3))
                        if offset not in candidates or dist<candidates[offset]:
                            candidates[offset]=dist
    def valid(offset):
        for source in moving:
            new=ring_of(source,*offset)
            for target in fixed:
                if target.code==source.code and rings_overlap(new,ring_of(target)):
                    return False
        return True

    def common_edge(offset):
        """Length of aligned collinear edge shared by moved and fixed rings."""
        amount=0.0
        for source in moving:
            moved=ring_of(source,*offset)
            for target in fixed:
                if target.code!=source.code:
                    continue
                other=ring_of(target)
                for a,b in _segments(moved):
                    for c,d in _segments(other):
                        if (abs(_cross(a,b,c))>0.002 or
                            abs(_cross(a,b,d))>0.002):
                            continue
                        length=hypot(b[0]-a[0],b[1]-a[1])
                        if length<EPS:
                            continue
                        ux=(b[0]-a[0])/length
                        uy=(b[1]-a[1])/length
                        project=lambda p:p[0]*ux+p[1]*uy
                        overlap=min(max(project(a),project(b)),
                                    max(project(c),project(d)))-max(
                                    min(project(a),project(b)),
                                    min(project(c),project(d)))
                        amount=max(amount,overlap)
        return amount

    good=[(offset,dist) for offset,dist in candidates.items() if valid(offset)]
    if not good:
        return dx,dy,None
    # If the requested position is already valid and nowhere near a shared
    # edge, an exact match is not a snap and should not be advertised as one.
    good.sort(key=lambda item:(-common_edge(item[0]),item[1]))
    result,distance=good[0]
    if result==(round(dx,3),round(dy,3)):
        return dx,dy,None
    return result[0],result[1],distance
