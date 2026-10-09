# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Betopo contributors
"""Local screen-space face picking; no mesh changes or Blender state."""
import math
from itertools import combinations


def cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def distance_sq(a, b):
    return (a[0]-b[0])**2+(a[1]-b[1])**2


def inside(point, polygon, strict=False):
    """Even-odd containment for arbitrary existing faces, including concave ngons."""
    contained = False
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        length = math.sqrt(distance_sq(a,b))
        if abs(cross(a,b,point)) <= .25*length and (
                min(a[0],b[0])-.25 <= point[0] <= max(a[0],b[0])+.25 and
                min(a[1],b[1])-.25 <= point[1] <= max(a[1],b[1])+.25):
            return not strict
        if (a[1]>point[1]) != (b[1]>point[1]):
            x = a[0]+(point[1]-a[1])*(b[0]-a[0])/(b[1]-a[1])
            if point[0] < x:
                contained = not contained
    return contained


def edges_conflict(a, b, c, d, shared_endpoint=False):
    """Reject crossings, T junctions and partial overlaps; allow a shared corner."""
    ab_c,ab_d,cd_a,cd_b = cross(a,b,c),cross(a,b,d),cross(c,d,a),cross(c,d,b)
    if ab_c*ab_d < -1e-8 and cd_a*cd_b < -1e-8:
        return True
    if max(abs(ab_c),abs(ab_d),abs(cd_a),abs(cd_b)) < 1e-6:
        axis = 0 if abs(b[0]-a[0]) >= abs(b[1]-a[1]) else 1
        overlap = min(max(a[axis],b[axis]),max(c[axis],d[axis]))-max(min(a[axis],b[axis]),min(c[axis],d[axis]))
        return overlap > .25 or (overlap >= -.25 and not shared_endpoint)
    if shared_endpoint:
        return False
    for p,u,v in ((a,c,d),(b,c,d),(c,a,b),(d,a,b)):
        if abs(cross(u,v,p)) < 1e-6 and (
                min(u[0],v[0])-.01 <= p[0] <= max(u[0],v[0])+.01 and
                min(u[1],v[1])-.01 <= p[1] <= max(u[1],v[1])+.01):
            return True
    return False


def choose_face(points, cursor, sides=4, edges=(), occupied=(), blockers=()):
    """Return ordered point IDs around the hovered cell, or None.

    points: [(ID, (x,y))], at most 12 nearest visible boundary/loose vertices.
    edges: [(ID_a, ID_b, (x,y)_a, (x,y)_b, incident_face_count)].
    occupied: visible existing polygons in screen coordinates.
    blockers: all nearby visible points, including those outside the 12-point pool.
    """
    if sides not in (3,4) or len(points)<sides:
        return None
    edge_counts = {frozenset((a,b)):count for a,b,_pa,_pb,count in edges}
    best,best_key = None,None
    for group in combinations(points[:12],sides):
        center = tuple(sum(p[1][i] for p in group)/sides for i in (0,1))
        ordered = sorted(group,key=lambda p:math.atan2(p[1][1]-center[1],p[1][0]-center[0]))
        ids = tuple(p[0] for p in ordered)
        polygon = [p[1] for p in ordered]
        if any(cross(polygon[i-1],polygon[i],polygon[(i+1)%sides]) <= 1e-6 for i in range(sides)):
            continue
        area = sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(polygon,polygon[1:]+polygon[:1]))*.5
        if area<16 or not inside(cursor,polygon):
            continue
        if any(point_id not in ids and inside(p,polygon,strict=True)
               for point_id,p in (blockers or points)):
            continue
        pairs = list(zip(ids,ids[1:]+ids[:1]))
        if any(edge_counts.get(frozenset(pair),0)>=2 for pair in pairs):
            continue
        conflict = False
        for (a,b),(pa,pb) in zip(pairs,zip(polygon,polygon[1:]+polygon[:1])):
            for c,d,pc,pd,_count in edges:
                if frozenset((a,b))==frozenset((c,d)):
                    continue
                if edges_conflict(pa,pb,pc,pd,a in (c,d) or b in (c,d)):
                    conflict = True
                    break
            if conflict:
                break
        if conflict:
            continue
        # Crossing checks handle adjacent faces; strict containment also handles identical
        # and completely enclosed faces whose perimeter does not cross a new edge.
        if any(inside(center,face,strict=True) or
               any(inside(p,face,strict=True) for p in polygon) or
               any(inside(p,polygon,strict=True) for p in face)
               for face in occupied):
            continue
        lengths = [math.sqrt(distance_sq(a,b)) for a,b in zip(polygon,polygon[1:]+polygon[:1])]
        if min(lengths)<2 or max(lengths)>min(lengths)*20:
            continue
        perimeter = sum(lengths)
        boundary_matches = sum(edge_counts.get(frozenset(pair))==1 for pair in pairs)
        score = distance_sq(cursor,center)/area+.02*perimeter**2/area
        key = (-boundary_matches,score,perimeter)
        if best_key is None or key<best_key:
            best,best_key = ids,key
    return best
