# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Betopo contributors
"""Surface queries and mesh construction shared by Betopo tools."""
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import bmesh
import bpy
from bpy.app.handlers import persistent
from mathutils import Vector
from mathutils.bvhtree import BVHTree

TEMPLATES = json.loads(Path(__file__).with_name('templates.json').read_text(encoding='utf-8'))
SURFACES = {}


class SourceSurface:
    def __init__(self, source, depsgraph):
        self.mesh_pointer = source.data.as_pointer()
        evaluated = source.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            self.vertices = [tuple(evaluated.matrix_world @ v.co) for v in mesh.vertices]
            self.triangles = [tuple(t.vertices) for t in mesh.loop_triangles]
        finally:
            evaluated.to_mesh_clear()
        if not self.triangles:
            raise ValueError('Source needs a surface with faces')
        self.bvh = BVHTree.FromPolygons(self.vertices, self.triangles, all_triangles=True)
        coords = [Vector(v) for v in self.vertices]
        self.size = (Vector(tuple(max(v[i] for v in coords) for i in range(3))) -
                     Vector(tuple(min(v[i] for v in coords) for i in range(3)))).length
        self.dirty = False

    def hit(self, origin, direction, offset=0.0):
        co, normal, _index, _distance = self.bvh.ray_cast(origin, direction)
        return (co + normal * offset, normal) if co is not None else None

    def nearest(self, co, offset=0.0):
        point, normal, _index, _distance = self.bvh.find_nearest(Vector(co))
        if point is None:
            raise ValueError('No source surface near this point')
        return point + normal * offset, normal

    def project(self, co, offset=0.0):
        return self.nearest(co, offset)[0]


def surface(settings, context):
    source = settings.source
    if source is None or source.type != 'MESH' or source == settings.target:
        raise ValueError('Choose a mesh Source different from the retopology Target')
    key = source.as_pointer()
    cached = SURFACES.get(key)
    if cached is None or cached.dirty:
        cached = SURFACES[key] = SourceSurface(source, context.evaluated_depsgraph_get())
    return cached


@persistent
def mark_source_dirty(_scene, depsgraph):
    for update in depsgraph.updates:
        item = update.id.original
        for pointer, cached in list(SURFACES.items()):
            if isinstance(item, bpy.types.Object) and item.as_pointer() == pointer:
                cached.dirty = True
            elif isinstance(item, bpy.types.Mesh) and item.as_pointer() == cached.mesh_pointer:
                cached.dirty = True


def edit_mesh(context):
    settings = context.scene.betopo
    obj = context.active_object
    if context.mode != 'EDIT_MESH' or obj is None or obj != settings.target:
        raise ValueError('Enter Edit Mode on the Betopo Target')
    if len(context.objects_in_mode_unique_data) != 1:
        raise ValueError('Edit the retopology Target alone')
    if not obj.data.is_editable:
        raise ValueError('Target mesh is read-only')
    return obj, bmesh.from_edit_mesh(obj.data)


def refresh(obj, bm, destructive=True):
    bm.normal_update()
    bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=destructive)


def patch(points, faces=(), edges=(), existing=None):
    return {'points': [Vector(p) for p in points], 'faces': [tuple(f) for f in faces],
            'edges': [tuple(e) for e in edges], 'existing': existing or {}}


def add_patch(obj, bm, plan, source, weld_distance=0.0):
    """Apply an already previewed patch, rolling back only new elements on failure."""
    points, faces, edges = plan['points'], plan['faces'], plan['edges']
    inverse = obj.matrix_world.inverted_safe()
    old_edges = set(bm.edges)
    added, created, vertices = [], [], []
    existing = plan['existing']
    old_verts = list(bm.verts)
    try:
        for i, co in enumerate(points):
            v = existing.get(i)
            if v is not None and not v.is_valid:
                raise ValueError('Selection changed; rebuild the preview')
            if v is None:
                nearest = min(old_verts, key=lambda v: (obj.matrix_world @ v.co - co).length_squared,
                              default=None)
                if nearest and (obj.matrix_world @ nearest.co - co).length <= max(weld_distance,1e-8):
                    v = nearest
            if v is None:
                v = bm.verts.new(inverse @ co)
                added.append(v)
            vertices.append(v)
        oriented, uses = [], Counter()
        for indices in faces:
            verts = [vertices[i] for i in indices]
            if len(set(verts)) != len(verts) or len(verts) < 3:
                raise ValueError('Weld would collapse a face; lower Weld Distance')
            coords = [obj.matrix_world @ v.co for v in verts]
            center = sum(coords, Vector()) / len(coords)
            normal = sum(((a - center).cross(b - center) for a, b in
                          zip(coords, coords[1:] + coords[:1])), Vector())
            if normal.length < 1e-12:
                raise ValueError('Patch contains a zero-area face')
            if len(coords)==4:
                turns = [(coords[i]-coords[i-1]).cross(coords[(i+1)%4]-coords[i]).dot(normal)
                         for i in range(4)]
                if min(turns)<-1e-10*normal.length_squared:
                    raise ValueError('Patch contains a folded quad; reduce size or change Grid Span')
            if source and normal.dot(source.nearest(center)[1]) < 0:
                verts.reverse()
            if bm.faces.get(verts):
                raise ValueError('A face already occupies this patch')
            oriented.append(verts)
            for a, b in zip(verts, verts[1:] + verts[:1]):
                uses[frozenset((a, b))] += 1
        for pair, count in uses.items():
            edge = bm.edges.get(tuple(pair))
            if count + (len(edge.link_faces) if edge else 0) > 2:
                raise ValueError('Patch would create a non-manifold edge')
        for verts in oriented:
            face = bm.faces.new(verts)
            face.smooth = True
            created.append(face)
        for a, b in edges:
            if vertices[a] == vertices[b]:
                raise ValueError('Loop contains collapsed edges')
            if not bm.edges.get((vertices[a], vertices[b])):
                bm.edges.new((vertices[a], vertices[b]))
    except Exception:
        for face in reversed(created):
            if face.is_valid:
                bm.faces.remove(face)
        for edge in list(bm.edges):
            if edge not in old_edges and not edge.link_faces:
                bm.edges.remove(edge)
        for v in reversed(added):
            if v.is_valid:
                bm.verts.remove(v)
        refresh(obj, bm)
        raise
    for seq in (bm.verts, bm.edges, bm.faces):
        for element in seq:
            element.select_set(False)
    for v in vertices:
        v.select_set(True)
    for f in created:
        f.select_set(True)
    for a, b in edges:
        edge = bm.edges.get((vertices[a], vertices[b]))
        if edge:
            edge.select_set(True)
    bm.select_history.clear()
    bm.select_flush_mode()
    refresh(obj, bm)
    return vertices, created


def selected_boundaries(bm):
    selected = [e for e in bm.edges if e.select and not e.hide]
    if not selected or any(len(e.link_faces) > 1 for e in selected):
        raise ValueError('Select only open boundary or loose edges')
    neighbors = defaultdict(list)
    for edge in selected:
        a, b = edge.verts
        neighbors[a].append(b)
        neighbors[b].append(a)
    if any(len(n) > 2 for n in neighbors.values()):
        raise ValueError('Boundary selection must not branch')
    remaining, result = set(neighbors), []
    while remaining:
        first = min(remaining, key=lambda v: tuple(v.co))
        component, stack = set(), [first]
        while stack:
            v = stack.pop()
            if v not in component:
                component.add(v)
                stack.extend(neighbors[v])
        ends = [v for v in component if len(neighbors[v]) == 1]
        closed = not ends
        current = min(ends or component, key=lambda v: tuple(v.co))
        previous, chain = None, []
        while current not in chain:
            chain.append(current)
            following = [v for v in neighbors[current] if v != previous]
            if not following:
                break
            previous, current = current, min(following, key=lambda v: tuple(v.co))
        remaining -= component
        result.append((chain, closed))
    return result


def grid_fill_plan(obj, boundary, source, offset=0.0, span=0):
    """Coons patch interpolates four boundary sides, preserving every boundary vertex."""
    count = len(boundary)
    if count < 4 or count % 2:
        raise ValueError('Quad Fill needs an even boundary count; subdivide one edge first')
    n = span or max(1, count // 4)
    m = count // 2 - n
    if n < 1 or m < 1:
        raise ValueError('Grid Span must be between 1 and half the boundary count minus 1')
    ring = [obj.matrix_world @ v.co for v in boundary]
    points, existing, grid = [], {}, {}
    for j in range(m + 1):
        for i in range(n + 1):
            index = len(points)
            grid[i, j] = index
            boundary_index = None
            if j == 0:
                boundary_index = i
            elif i == n:
                boundary_index = n + j
            elif j == m:
                boundary_index = 2 * n + m - i
            elif i == 0:
                boundary_index = (count - j) % count
            if boundary_index is not None:
                co = ring[boundary_index]
                existing[index] = boundary[boundary_index]
            else:
                s, t = i / n, j / m
                bottom, top = ring[i], ring[2 * n + m - i]
                left, right = ring[(count - j) % count], ring[n + j]
                bilinear = ((1-s)*(1-t)*ring[0] + s*(1-t)*ring[n] +
                            s*t*ring[n+m] + (1-s)*t*ring[2*n+m])
                co = (1-t)*bottom + t*top + (1-s)*left + s*right - bilinear
                co = source.project(co, offset) if source else co
            points.append(co)
    faces = [(grid[i,j], grid[i+1,j], grid[i+1,j+1], grid[i,j+1])
             for j in range(m) for i in range(n)]
    return patch(points, faces, existing=existing)


def native_grid_fill_plan(obj, boundary, source, offset=0.0, span=0, grid_offset=0, simple=False):
    """Blender's BMesh Grid Fill on a temporary rim; project only new vertices."""
    count = len(boundary)
    if count<4 or count%2:
        raise ValueError('GFill needs an even number of boundary edges; use Fill for triangles')
    n = span or max(1,count//4)
    m = count//2-n
    if n<1 or m<1:
        raise ValueError('Span must be between 1 and half the boundary count minus 1')
    start = grid_offset%count
    boundary = list(boundary[start:])+list(boundary[:start])
    temp = bmesh.new()
    try:
        rim = [temp.verts.new(v.co) for v in boundary]
        edges = [temp.edges.new((a,b)) for a,b in zip(rim,rim[1:]+rim[:1])]
        result = bmesh.ops.grid_fill(temp,edges=edges[:n]+edges[n+m:2*n+m],use_interp_simple=simple)
        faces = result['faces']
        if not faces or any(len(f.verts)!=4 for f in faces):
            raise ValueError('GFill cannot fit a quad grid here; adjust Span or Grid Offset')
        return temporary_fill_plan(obj,temp,rim,boundary,faces,source,offset)
    finally:
        temp.free()


def triangle_fill_plan(obj, boundary, source, offset=0.0):
    """A triangle cap for odd rims, without creating an invisible ngon fallback."""
    if len(boundary)<3:
        raise ValueError('A closed hole needs at least three boundary points')
    temp = bmesh.new()
    try:
        rim = [temp.verts.new(v.co) for v in boundary]
        edges = [temp.edges.new((a,b)) for a,b in zip(rim,rim[1:]+rim[:1])]
        bmesh.ops.triangle_fill(temp,edges=edges,use_beauty=True)
        if not temp.faces:
            raise ValueError('Could not triangulate this hole')
        return temporary_fill_plan(obj,temp,rim,boundary,list(temp.faces),source,offset)
    finally:
        temp.free()


def temporary_fill_plan(obj, temp, rim, boundary, faces, source, offset):
    rim_set = set(rim)
    vertices = list(rim)+[v for v in temp.verts if v not in rim_set]
    index = {v:i for i,v in enumerate(vertices)}
    points = [obj.matrix_world @ v.co for v in vertices]
    for i in range(len(rim),len(points)):
        if source:
            points[i] = source.project(points[i],offset)
    return patch(points,[[index[v] for v in f.verts] for f in faces],
                 existing=dict(enumerate(boundary)))


def bridge_plan(obj, a, b, closed, source, offset=0.0, cuts=0):
    if len(a) != len(b):
        raise ValueError('Bridge loops need matching counts; use Transition Fill for unequal open chains')
    if closed:
        from .contours import align_ring
        ac = [tuple(obj.matrix_world @ v.co) for v in a]
        bc = [tuple(obj.matrix_world @ v.co) for v in b]
        order = align_ring(ac, bc)
        b = [b[bc.index(p)] for p in order]
    elif (a[0].co - b[-1].co).length_squared + (a[-1].co - b[0].co).length_squared < (
            (a[0].co - b[0].co).length_squared + (a[-1].co - b[-1].co).length_squared):
        b = list(reversed(b))
    size, points, existing = len(a), [], {}
    for row in range(cuts + 2):
        t = row / (cuts + 1)
        for i, (v, w) in enumerate(zip(a, b)):
            index = len(points)
            co = (obj.matrix_world @ v.co).lerp(obj.matrix_world @ w.co, t)
            if row in (0, cuts + 1):
                existing[index] = v if row == 0 else w
            elif source:
                co = source.project(co, offset)
            points.append(co)
    faces = []
    for row in range(cuts + 1):
        for i in range(size if closed else size - 1):
            j = (i + 1) % size
            faces.append((row*size+i, row*size+j, (row+1)*size+j, (row+1)*size+i))
    return patch(points, faces, existing=existing)


def sample_path(points, count):
    coords = [Vector(p) for p in points]
    if len(coords) < 2:
        raise ValueError('Draw a longer stroke')
    lengths = [0.0]
    for a, b in zip(coords, coords[1:]):
        lengths.append(lengths[-1] + (b-a).length)
    if lengths[-1] < 1e-10:
        raise ValueError('Stroke is too short')
    result, segment = [], 0
    for i in range(count):
        position = lengths[-1] * i / (count-1)
        while segment < len(coords)-2 and lengths[segment+1] < position:
            segment += 1
        width = lengths[segment+1] - lengths[segment]
        result.append(coords[segment].lerp(coords[segment+1], (position-lengths[segment])/width)
                      if width > 1e-12 else coords[segment].copy())
    return result


def stroke_plan(points, segments, width, source, offset=0.0):
    centers = [source.project(p, offset) for p in sample_path(points, segments + 1)]
    coords = []
    for i, center in enumerate(centers):
        tangent = centers[min(i+1, segments)] - centers[max(0, i-1)]
        normal = source.nearest(center)[1]
        side = normal.cross(tangent).normalized() * width * .5
        if side.length < 1e-10:
            raise ValueError('Stroke direction does not define a surface strip')
        coords.extend((source.project(center-side, offset), source.project(center+side, offset)))
    return patch(coords, [(2*i, 2*i+2, 2*i+3, 2*i+1) for i in range(segments)])


def smooth_path(points, steps=16, amount=1.0):
    """Open centripetal Catmull-Rom through clicked anchors, with safe end tangents."""
    cleaned = []
    for point in points:
        point = Vector(point)
        if not cleaned or (point-cleaned[-1]).length>1e-9:
            cleaned.append(point)
    if len(cleaned)<2:
        raise ValueError('Dot needs at least two different points')
    steps = max(4,int(steps))
    amount = min(1.0,max(0.0,amount))
    pts = [cleaned[0]*2-cleaned[1]]+cleaned+[cleaned[-1]*2-cleaned[-2]]
    result = []
    for i in range(1,len(pts)-2):
        p0,p1,p2,p3 = pts[i-1:i+3]
        t0 = 0.0
        t1 = (p1-p0).length**.5
        t2 = t1+(p2-p1).length**.5
        t3 = t2+(p3-p2).length**.5
        result.append(p1)
        for step in range(1,steps):
            u = step/steps
            t = t1+u*(t2-t1)
            a1 = p0*((t1-t)/(t1-t0))+p1*((t-t0)/(t1-t0))
            a2 = p1*((t2-t)/(t2-t1))+p2*((t-t1)/(t2-t1))
            a3 = p2*((t3-t)/(t3-t2))+p3*((t-t2)/(t3-t2))
            b1 = a1*((t2-t)/(t2-t0))+a2*((t-t0)/(t2-t0))
            b2 = a2*((t3-t)/(t3-t1))+a3*((t-t1)/(t3-t1))
            curve = b1*((t2-t)/(t2-t1))+b2*((t-t1)/(t2-t1))
            result.append(p1.lerp(p2,u).lerp(curve,amount))
    result.append(cleaned[-1])
    return result


def dot_plan(points, segments, width, source, offset=0.0, smooth=1.0):
    density = max(16,min(64,math.ceil(segments*4/max(1,len(points)-1))))
    curve = smooth_path(points,density,smooth)
    plan = stroke_plan(curve,segments,width,source,offset)
    plan['curve'] = [source.project(p,offset) for p in sample_path(curve,segments*4+1)]
    return plan


def template_plan(name, center, normal, direction, size, angle, source, offset=0.0):
    data = TEMPLATES[name]
    coords = [Vector(v) for v in data['vertices']]
    centroid = sum(coords, Vector()) / len(coords)
    # FBX assets are near-planar; select their two broadest axes instead of assuming XY.
    extents = [max(v[i] for v in coords) - min(v[i] for v in coords) for i in range(3)]
    axes = sorted(range(3), key=lambda i: extents[i], reverse=True)[:2]
    axes.sort()
    norm = max(extents[i] for i in axes)
    u = direction - normal * direction.dot(normal)
    if u.length < 1e-8:
        u = normal.cross(Vector((0,1,0)))
    if u.length < 1e-8:
        u = normal.cross(Vector((1,0,0)))
    u.normalize()
    v = normal.cross(u).normalized()
    rotated_u, rotated_v = u*math.cos(angle)+v*math.sin(angle), -u*math.sin(angle)+v*math.cos(angle)
    points = []
    for co in coords:
        delta = co-centroid
        placed = Vector(center) + size/norm*(rotated_u*delta[axes[0]]+rotated_v*delta[axes[1]])
        projected = source.project(placed, offset)
        if (projected-placed).length > size:
            raise ValueError('Template is too far from the surface; reduce its size')
        points.append(projected)
    return patch(points, data['faces'])


def relax_vertices(obj, bm, source, vertices, strength=.5, iterations=3,
                   keep_boundary=True, offset=0.0, weights=None):
    layer = bm.verts.layers.int.get('betopo_pin')
    inverse = obj.matrix_world.inverted_safe()
    moved = 0
    for _iteration in range(iterations):
        updates = {}
        for vert in vertices:
            if vert.hide or (layer and vert[layer]) or (keep_boundary and vert.is_boundary):
                continue
            neighbors = [edge.other_vert(vert) for edge in vert.link_edges]
            if not neighbors:
                continue
            co = obj.matrix_world @ vert.co
            average = sum((obj.matrix_world @ n.co for n in neighbors), Vector()) / len(neighbors)
            normal = source.nearest(co)[1]
            movement = average - co
            movement -= normal * movement.dot(normal)
            amount = strength * (weights.get(vert, 1) if weights else 1)
            updates[vert] = inverse @ source.project(co + movement * amount, offset)
        for vert, co in updates.items():
            vert.co = co
        moved = len(updates)
    refresh(obj, bm, False)
    return moved


def ensure_symmetry(settings):
    obj = settings.target
    if obj is None or obj.type != 'MESH':
        return
    name = 'Betopo Symmetry'
    mod = obj.modifiers.get(name)
    if not settings.symmetry:
        if mod and mod.type == 'MIRROR':
            mod.show_viewport = mod.show_render = False
        return
    if mod is None:
        mod = obj.modifiers.new(name, 'MIRROR')
    if mod.type != 'MIRROR':
        raise ValueError('Rename the existing non-Mirror modifier called Betopo Symmetry')
    axis = 'XYZ'.index(settings.symmetry_axis)
    mod.use_axis = tuple(i == axis for i in range(3))
    mod.use_bisect_axis = tuple(i == axis for i in range(3))
    mod.use_clip = True
    mod.use_mirror_merge = True
    mod.merge_threshold = settings.weld_distance / max(abs(obj.scale[axis]),1e-8)
    mod.show_viewport = mod.show_render = True
