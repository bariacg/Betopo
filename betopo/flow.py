# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Betopo contributors
"""Surface ribbons and safe in-place redrawing, independently implemented for Betopo."""
import math

from mathutils import Vector

from . import core


def validate(plan):
    """Reject collapsed or folded previews before touching the target mesh."""
    points = plan['points']
    if not points or any(not all(math.isfinite(c) for c in p) for p in points):
        raise ValueError('The preview contains invalid coordinates')
    size = max((max(p[i] for p in points) - min(p[i] for p in points) for i in range(3)), default=1)
    epsilon = max(size * 1e-8, 1e-10)
    for face in plan['faces']:
        coords = [points[i] for i in face]
        if any((a-b).length < epsilon for a, b in zip(coords, coords[1:]+coords[:1])):
            raise ValueError('The strip collapses here; draw farther or reduce its width')
        center = sum(coords, Vector()) / len(coords)
        normal = sum(((a-center).cross(b-center) for a, b in zip(coords, coords[1:]+coords[:1])), Vector())
        if normal.length < epsilon * epsilon:
            raise ValueError('The strip has a zero-area face; change the stroke')
        if min((coords[i]-coords[i-1]).cross(coords[(i+1) % 4]-coords[i]).dot(normal)
               for i in range(4)) < -1e-10 * normal.length_squared:
            raise ValueError('The strip folds here; reduce width or add segments')
    return plan


def ribbon_plan(stroke, segments, width, source, offset=0.0, smooth=.5,
                obj=None, start=None, end=None, closed=False, fixed_order=False):
    """Build a one-quad-wide ribbon, optionally reusing its boundary end edges."""
    if not all(math.isfinite(value) for value in (segments,width,offset,smooth)):
        raise ValueError('Flow settings must be finite numbers')
    if segments < (3 if closed else 1) or segments > 256 or width <= 0:
        raise ValueError('Flow needs a positive width and a valid segment count')
    path = [Vector(p).copy() for p in stroke]
    if any(not all(math.isfinite(c) for c in p) for p in path):
        raise ValueError('The Flow stroke contains invalid coordinates')
    if len(path) < 2:
        raise ValueError('Draw a longer Flow stroke')
    if closed and (start or end):
        raise ValueError('Closed Flow cannot attach to an end edge')
    if (start or end) and obj is None:
        raise ValueError('Flow attachment needs a Target')
    anchors = []
    for edge in (start, end):
        if edge:
            if len(edge) != 2 or any(not v.is_valid for v in edge):
                raise ValueError('The attachment changed; draw the stroke again')
            anchors.append([obj.matrix_world @ v.co for v in edge])
        else:
            anchors.append(None)
    if fixed_order and (start or end):
        first = sum(anchors[0],Vector())*.5 if start else None
        last = sum(anchors[1],Vector())*.5 if end else None
        forward = ((path[0]-first).length if first is not None else 0) + ((path[-1]-last).length if last is not None else 0)
        reverse = ((path[-1]-first).length if first is not None else 0) + ((path[0]-last).length if last is not None else 0)
        if reverse < forward:
            path.reverse()
    if start:
        path[0] = sum(anchors[0], Vector()) * .5
    if end:
        path[-1] = sum(anchors[1], Vector()) * .5
    if closed:
        if (path[-1]-path[0]).length > 1e-9:
            path.append(path[0].copy())
        # Periodic Chaikin smoothing avoids an artificial open-curve seam.
        raw = path[:-1]
        for _ in range(2 if smooth > 0 else 0):
            rounded = []
            for a, b in zip(raw, raw[1:]+raw[:1]):
                rounded.extend((a.lerp(b, .25*smooth), a.lerp(b, 1-.25*smooth)))
            raw = rounded
        curve = raw + [raw[0]]
    else:
        curve = path if smooth == 0 else core.smooth_path(path, max(8, min(32, segments)), smooth)
    centers = [source.project(p, offset) for p in core.sample_path(curve, segments+1)]
    if closed:
        centers.pop()
    points, existing = [], {}
    count = len(centers)
    column_sign = 1
    for i, center in enumerate(centers):
        previous = centers[(i-1) % count] if closed else centers[max(0, i-1)]
        following = centers[(i+1) % count] if closed else centers[min(count-1, i+1)]
        side = source.nearest(center)[1].cross(following-previous)
        if side.length < 1e-10:
            raise ValueError('Flow needs a stroke along the surface')
        side.normalize()
        if i == 0 and start:
            # Use one consistent column orientation for the entire ribbon.
            column_sign = 1 if side.dot(anchors[0][1]-anchors[0][0]) >= 0 else -1
        side *= column_sign
        row_width = width
        if start and i < 2:
            row_width = (anchors[0][1]-anchors[0][0]).length * (1-i/2) + width*(i/2)
        if end and i >= count-2:
            factor = (count-1-i)/2
            row_width = (anchors[1][1]-anchors[1][0]).length*(1-factor) + width*factor
        row = [source.project(center-side*row_width*.5, offset),
               source.project(center+side*row_width*.5, offset)]
        anchor = 0 if i == 0 and start else 1 if i == count-1 and end else None
        if anchor is not None:
            edge = list(start if anchor == 0 else end)
            coords = anchors[anchor]
            if not (fixed_order and anchor == 1) and anchor != 0 and sum((row[j]-coords[j]).length_squared for j in (0,1)) > sum(
                    (row[j]-coords[1-j]).length_squared for j in (0,1)):
                edge.reverse()
                coords = list(reversed(coords))
            row = coords
            existing.update({2*i+j: edge[j] for j in (0,1)})
        points.extend(row)
    faces = [(2*i, 2*((i+1) % count), 2*((i+1) % count)+1, 2*i+1)
             for i in range(segments)]
    plan = core.patch(points, faces, existing=existing)
    plan.update(curve=centers, flow_segments=segments, flow_closed=closed,
                flow_start=start, flow_end=end)
    return validate(plan)


def default_controls(start, end):
    """Return initial cubic Bezier control points from start and end endpoints."""
    try:
        p0 = Vector(start).copy()
        p3 = Vector(end).copy()
    except Exception:
        raise ValueError('Endpoints must have finite 3D coordinates')
    if len(p0) != 3 or len(p3) != 3 or not (all(math.isfinite(c) for c in p0) and all(math.isfinite(c) for c in p3)):
        raise ValueError('Endpoints must have finite 3D coordinates')
    if (p3 - p0).length < 1e-9:
        raise ValueError('Endpoints must be distinct')
    return [p0, p0.lerp(p3, 1/3).copy(), p0.lerp(p3, 2/3).copy(), p3]


def bezier_plan(controls, segments, width, source, offset=0.0,
                obj=None, start=None, end=None, fixed_order=False):
    """Build a one-quad-wide ribbon along a cubic Bezier curve."""
    try:
        ctrls = [Vector(p).copy() for p in controls]
    except Exception:
        raise ValueError('Flow controls must be exactly 4 finite 3D coordinates')
    if len(ctrls) != 4 or any(len(p) != 3 or not all(math.isfinite(c) for c in p) for p in ctrls):
        raise ValueError('Flow controls must be exactly 4 finite 3D coordinates')
    if not all(math.isfinite(value) for value in (segments, width, offset)):
        raise ValueError('Flow settings must be finite numbers')
    if int(segments) != segments or segments < 1 or segments > 256 or width <= 0:
        raise ValueError('Flow needs a positive width and a valid segment count')
    segments = int(segments)
    p0, h0, h1, p3 = [p.copy() for p in ctrls]
    if (p3 - p0).length < 1e-9:
        raise ValueError('Endpoints must be distinct')
    if (start or end) and obj is None:
        raise ValueError('Flow attachment needs a Target')
    if start:
        if len(start) != 2 or any(not getattr(v, 'is_valid', False) for v in start):
            raise ValueError('The attachment changed; draw the stroke again')
        mid = sum((obj.matrix_world @ v.co for v in start), Vector()) * 0.5
        delta = mid - p0
        p0 = mid
        h0 = h0 + delta
    if end:
        if len(end) != 2 or any(not getattr(v, 'is_valid', False) for v in end):
            raise ValueError('The attachment changed; draw the stroke again')
        mid = sum((obj.matrix_world @ v.co for v in end), Vector()) * 0.5
        delta = mid - p3
        p3 = mid
        h1 = h1 + delta
    if (p3 - p0).length < 1e-9:
        raise ValueError('Endpoints must be distinct')
    subdivisions = min(2048, max(64, segments * 8))
    dense_curve = bezier_curve((p0,h0,h1,p3),source,offset,subdivisions)
    plan = ribbon_plan(dense_curve, segments, width, source, offset=offset,
                       smooth=0, obj=obj, start=start, end=end,
                       closed=False, fixed_order=fixed_order)
    plan['curve'] = dense_curve
    plan['flow_controls'] = [p0.copy(), h0.copy(), h1.copy(), p3.copy()]
    return plan


def bezier_curve(controls,source,offset=0.0,subdivisions=64):
    """Surface preview also remains editable when the ribbon is too wide or folded."""
    p0,h0,h1,p3 = controls
    curve = []
    for i in range(subdivisions+1):
        t = i/subdivisions
        u = 1.0-t
        p = p0*(u*u*u)+h0*(3*u*u*t)+h1*(3*u*t*t)+p3*(t*t*t)
        curve.append(source.project(p,offset))
    return curve


def record(obj, vertices, faces, plan):
    anchors = set(plan['existing'].values())
    rec = {'obj': obj, 'vertices': list(vertices), 'faces': set(faces), 'anchors': anchors,
           'coordinates': [v.co.copy() for v in vertices],
           'segments': plan['flow_segments'], 'closed': plan['flow_closed'],
           'start': tuple(vertices[:2]) if plan['flow_start'] else None,
           'end': tuple(vertices[-2:]) if plan['flow_end'] else None}
    if plan.get('flow_controls') is not None:
        rec['controls'] = [c.copy() for c in plan['flow_controls']]
    return rec


def check_attachment(obj, bm, plan, source):
    """An open border must grow away from its existing face, not over it."""
    existing = plan['existing']
    for face in plan['faces']:
        center = sum((plan['points'][i] for i in face),Vector())/len(face)
        for i,j in zip(face,face[1:]+face[:1]):
            if i not in existing or j not in existing:
                continue
            edge = bm.edges.get((existing[i],existing[j]))
            if edge is None or len(edge.link_faces) != 1:
                continue
            middle = (plan['points'][i]+plan['points'][j])*.5
            inside = obj.matrix_world@edge.link_faces[0].calc_center_median()-middle
            normal = source.nearest(middle)[1]
            inside -= normal*inside.dot(normal)
            if (center-middle).dot(inside) > max(1e-12,inside.length_squared*1e-6):
                raise ValueError('Draw outward from the open border, away from its existing face')
    return plan


def check_record(state, obj):
    if not state or state['obj'] != obj:
        raise ValueError('Create a Flow strip first; Redraw Last works within this tool session')
    if any(not v.is_valid for v in state['vertices']) or any(not f.is_valid for f in state['faces']):
        raise ValueError('The last Flow strip changed; create a new strip instead')
    if len(set(state['vertices'])) != len(state['vertices']):
        raise ValueError('This strip has merged rows; use Tweak instead of Redraw Last')
    edges = {e for f in state['faces'] for e in f.edges}
    for v, co in zip(state['vertices'], state['coordinates']):
        if (v.co-co).length > 1e-7:
            raise ValueError('The last strip was edited; redraw it with Tweak instead')
        if v not in state['anchors'] and any(f not in state['faces'] for f in v.link_faces):
            raise ValueError('The last strip is attached to other faces; use Tweak instead')
        if v not in state['anchors'] and any(e not in edges for e in v.link_edges):
            raise ValueError('The last strip is connected to other edges; use Tweak instead')
    return state


def apply_redraw(obj, bm, state, plan):
    check_record(state, obj)
    validate(plan)
    if len(plan['points']) != len(state['vertices']):
        raise ValueError('Redraw Last keeps the original segment count')
    if any(v in state['anchors'] and (obj.matrix_world@v.co-point).length > 1e-6
           for v,point in zip(state['vertices'],plan['points'])):
        raise ValueError('Redraw must preserve the existing attachment vertices')
    pin = bm.verts.layers.int.get('betopo_pin')
    if pin and any(v[pin] and v not in state['anchors'] for v in state['vertices']):
        raise ValueError('The last strip contains pinned vertices; unpin before redrawing')
    inverse = obj.matrix_world.inverted_safe()
    before = [v.co.copy() for v in state['vertices']]
    try:
        for v, point in zip(state['vertices'], plan['points']):
            if v not in state['anchors']:
                v.co = inverse @ point
        core.refresh(obj, bm, False)
    except Exception:
        for v, co in zip(state['vertices'], before):
            v.co = co
        core.refresh(obj, bm, False)
        raise
    state['coordinates'] = [v.co.copy() for v in state['vertices']]
    if plan.get('flow_controls') is not None:
        state['controls'] = [c.copy() for c in plan['flow_controls']]
    return state['vertices'], list(state['faces'])
