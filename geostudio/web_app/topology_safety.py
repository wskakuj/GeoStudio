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
    """Closest native vertex to any stationary edge within tolerance.

    Returns snapped (dx, dy) and distance. Caller must still validate overlap
    and new topology; snapping never grants permission to break a shared edge.
    """
    best=None
    for obj in moving:
        candidates=[p for p in obj.points[:-1]]
        for neighbor in fixed:
            if neighbor.code!=obj.code:
                continue
            boundary=ring_of(neighbor)
            for p in candidates:
                position=(p.x+dx,p.y+dy)
                for a,b in _segments(boundary):
                    dist,target=_segment_distance(position,a,b)
                    if dist<=tolerance and (best is None or dist<best[0]):
                        proposed=(round(target[0]-p.x,3),round(target[1]-p.y,3))
                        if proposed!=(0.0,0.0) or dx==0.0 and dy==0.0:
                            best=(dist,*proposed)
    return (best[1],best[2],best[0]) if best else (dx,dy,None)
