# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Betopo contributors
"""Bridge two open edge chains with a small set of quad transition patches."""
from collections import Counter, defaultdict

import bmesh
import bpy
from mathutils import Vector

UNEQUAL_PAIRS = {(5, 3), (4, 2), (4, 1), (3, 2), (3, 1), (2, 1)}
MAX_EQUAL_EDGES = 49
EPS = 1e-7


def selection(context):
    if (context.area is None or context.area.type != "VIEW_3D" or context.mode != "EDIT_MESH"
            or tuple(context.tool_settings.mesh_select_mode) != (False, True, False)):
        raise ValueError("Use Edge selection in Mesh Edit Mode")
    candidates = [obj for obj in context.objects_in_mode_unique_data if obj.data.total_edge_sel]
    if len(candidates) != 1:
        raise ValueError("Select two open edge chains in one mesh")
    obj = candidates[0]
    bm = bmesh.from_edit_mesh(obj.data)
    edges = [e for e in bm.edges if e.select]
    if not edges or any(e.hide or any(v.hide for v in e.verts) or len(e.link_faces) > 1 for e in edges):
        raise ValueError("Select visible boundary or loose edges only")
    neighbors = defaultdict(list)
    for e in edges:
        a, b = e.verts
        neighbors[a].append(b)
        neighbors[b].append(a)
    if any(len(adjacent) > 2 for adjacent in neighbors.values()):
        raise ValueError("The selected chains must not branch or touch each other")
    remaining, chains = set(neighbors), []
    while remaining:
        component, stack = set(), [next(iter(remaining))]
        while stack:
            v = stack.pop()
            if v not in component:
                component.add(v)
                stack.extend(neighbors[v])
        remaining -= component
        ends = [v for v in component if len(neighbors[v]) == 1]
        if len(ends) != 2:
            raise ValueError("Closed rings use Cap or Grid Fill; Quad Fill needs two open chains")
        current = min(ends, key=lambda v: tuple(v.co))
        chain, previous = [], None
        while current is not None:
            chain.append(current)
            following = next((v for v in neighbors[current] if v != previous), None)
            previous, current = current, following
        chains.append(chain)
    if len(chains) != 2:
        raise ValueError("Select exactly two separate open edge chains")
    a, b = sorted(chains, key=lambda chain: (-len(chain), tuple(chain[0].co)))
    n, m = len(a) - 1, len(b) - 1
    if n == m and n > MAX_EQUAL_EDGES:
        raise ValueError("Equal chains support 1-49 edges each; use Bridge for longer chains")
    if n != m and (n, m) not in UNEQUAL_PAIRS:
        raise ValueError("Supported: equal counts, 5:3, 4:2, 4:1, 3:2, 3:1 and 2:1")
    return obj, bm, a, b


def cross(a, b, c):
    return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)


def on_segment(a, b, p):
    return (abs(cross(a, b, p)) < EPS and min(a.x, b.x) - EPS <= p.x <= max(a.x, b.x) + EPS
            and min(a.y, b.y) - EPS <= p.y <= max(a.y, b.y) + EPS)


def intersects(a, b, c, d):
    ab_c, ab_d, cd_a, cd_b = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
    return ((ab_c * ab_d < -EPS ** 2 and cd_a * cd_b < -EPS ** 2)
            or on_segment(a, b, c) or on_segment(a, b, d)
            or on_segment(c, d, a) or on_segment(c, d, b))


def area2(points):
    return sum(a.x * b.y - a.y * b.x for a, b in zip(points, points[1:] + points[:1]))


def project(coords, boundary):
    center = sum((coords[i] for i in boundary), Vector()) / len(boundary)
    normal = sum(((coords[i] - center).cross(coords[j] - center)
                  for i, j in zip(boundary, boundary[1:] + boundary[:1])), Vector())
    span = max((coords[i] - center).length for i in boundary)
    if span == 0 or normal.length < span * span * EPS:
        raise ValueError("The chains cannot form a nonzero surface")
    u = (coords[boundary[1]] - coords[boundary[0]]).normalized()
    v = normal.normalized().cross(u).normalized()
    return [Vector(((co - center).dot(u) / span, (co - center).dot(v) / span)) for co in coords]


def check_edges(edges, points):
    edges = list(edges)
    for index, (a, b) in enumerate(edges):
        if (points[a] - points[b]).length < EPS:
            raise ValueError("The patch contains overlapping points")
        for c, d in edges[index + 1:]:
            shared = {a, b} & {c, d}
            if shared:
                s = next(iter(shared))
                x, y = next(i for i in (a, b) if i != s), next(i for i in (c, d) if i != s)
                if on_segment(points[s], points[x], points[y]) or on_segment(points[s], points[y], points[x]):
                    raise ValueError("The patch contains overlapping edges")
            elif intersects(points[a], points[b], points[c], points[d]):
                raise ValueError("The chains or new faces cross; select a simpler pair of chains")


def plan(obj, bm, a, b):
    # Pair corresponding ends. All topology validation happens before mutation.
    if ((a[0].co - b[-1].co).length_squared + (a[-1].co - b[0].co).length_squared
            < (a[0].co - b[0].co).length_squared + (a[-1].co - b[-1].co).length_squared):
        b = list(reversed(b))
    originals = a + b
    coords = [v.co.copy() for v in originals]
    n, m, offset = len(a) - 1, len(b) - 1, len(a)
    A, B = list(range(len(a))), list(range(offset, len(originals)))
    faces, sources = [], []
    difference = n - m
    start = (m - 1) // 2 if difference else m

    def quad(i, j):
        faces.append((A[i], A[i + 1], B[j + 1], B[j]))

    for i in range(start):
        quad(i, i)
    if (n, m) == (4, 2):
        # Reduce one edge on each side of the middle edge. Routing both extra
        # edges through one 3:1 patch makes a 4:2 transition visibly lopsided.
        c, d, e = range(len(coords), len(coords) + 3)
        for i, j, k, factor in ((A[1], B[0], B[1], .5),
                                (A[2], B[1], B[1], .5),
                                (A[3], B[1], B[2], .5)):
            coords.append(coords[i].lerp(coords[j].lerp(coords[k], factor), .5))
            sources.append((i, j, k, factor))
        faces.extend(((A[0], A[1], c, B[0]),
                      (A[1], A[2], d, c),
                      (A[2], A[3], e, d),
                      (A[3], A[4], B[2], e),
                      (B[0], c, d, B[1]),
                      (B[1], d, e, B[2])))
    elif difference == 1:
        # One triangle accommodates the extra edge without splitting old edges.
        faces.extend(((A[start], A[start + 1], B[start]),
                      (A[start + 1], A[start + 2], B[start + 1], B[start])))
    elif difference in (2, 3):
        # Two interior points create a smooth 3:1 quad transition. The 4:1
        # variant keeps its middle five-sided face rather than adding triangles.
        last = start + difference + 1
        c, d = len(coords), len(coords) + 1
        for i, factor in ((A[start + 1], 1 / (difference + 1)),
                          (A[last - 1], difference / (difference + 1))):
            j, k = B[start], B[start + 1]
            coords.append(coords[i].lerp(coords[j].lerp(coords[k], factor), .5))
            sources.append((i, j, k, factor))
        faces.extend(((A[start], A[start + 1], c, B[start]),
                      (*A[start + 1:last], d, c),
                      (A[last - 1], A[last], B[start + 1], d),
                      (B[start], c, d, B[start + 1])))
    if difference and (n, m) != (4, 2):
        for j in range(start + 1, m):
            quad(j + difference, j)
    boundary = A + list(reversed(B))
    points = project(coords, boundary)
    uses = Counter(tuple(sorted((i, j))) for face in faces for i, j in zip(face, face[1:] + face[:1]))
    check_edges(uses, points)
    expected_area = area2([points[i] for i in boundary])
    total = 0
    for face in faces:
        polygon = [points[i] for i in face]
        signed = area2(polygon)
        if signed < EPS:
            raise ValueError("The patch would contain inverted or zero-area faces")
        if len(face) == 4 and any(cross(polygon[i - 1], polygon[i], polygon[(i + 1) % 4]) < -EPS for i in range(4)):
            raise ValueError("The patch would contain a folded quad; use simpler chains")
        total += signed
    if abs(total - expected_area) > EPS * max(1, expected_area):
        raise ValueError("The patch would not cover the selected gap")
    reversal, templates = set(), []
    for face in faces:
        template = None
        if all(i < len(originals) for i in face) and bm.faces.get(tuple(originals[i] for i in face)):
            raise ValueError("A face already occupies the selected gap")
        for i, j in zip(face, face[1:] + face[:1]):
            if i >= len(originals) or j >= len(originals):
                continue
            edge = bm.edges.get((originals[i], originals[j]))
            if edge is None:
                continue
            if len(edge.link_faces) + uses[tuple(sorted((i, j)))] > 2:
                raise ValueError("The patch would overlap existing faces")
            if edge.link_faces:
                template = template or edge.link_faces[0]
                loop = next(loop for loop in edge.link_faces[0].loops if loop.edge == edge)
                reversal.add(loop.vert == originals[i])
        templates.append(template)
    if len(reversal) > 1:
        raise ValueError("Boundary faces have conflicting directions; correct their normals first")
    if reversal == {True}:
        faces = [tuple(reversed(face)) for face in faces]
    return originals, coords, sources, faces, points, templates


def apply_patch(obj, bm, patch):
    originals, coords, sources, faces, points, templates = patch
    verts, created, added = list(originals), [], []
    old_edges = set(bm.edges)
    fallback = next((face for face in templates if face is not None), None)
    try:
        for co, (i, j, k, factor) in zip(coords[len(originals):], sources):
            vert = bm.verts.new(co)
            added.append(vert)
            if j == k:
                # The middle point lies directly between two existing verts.
                vert.copy_from_vert_interp((verts[i], verts[j]), .5)
            else:
                vert.copy_from_vert_interp((verts[j], verts[k]), factor)
                vert.copy_from_vert_interp((verts[i], vert), .5)
            verts.append(vert)
        low = Vector((min(p.x for p in points), min(p.y for p in points)))
        size = Vector((max(p.x for p in points), max(p.y for p in points))) - low
        layers = list(bm.loops.layers.uv.values())
        for indices, template in zip(faces, templates):
            face = bm.faces.new(tuple(verts[i] for i in indices))
            created.append(face)
            template = template if template is not None else fallback
            face.material_index = template.material_index if template is not None else obj.active_material_index
            face.smooth = template.smooth if template is not None else False
            for loop, index in zip(face.loops, indices):
                uv = points[index] - low
                for layer in layers:
                    loop[layer].uv = (uv.x / max(size.x, EPS), uv.y / max(size.y, EPS))
    except Exception:
        # Remove only geometry created by this operation, leaving the original
        # topology, custom data and selection intact on a failed construction.
        for face in reversed(created):
            bm.faces.remove(face)
        for edge in list(bm.edges):
            if edge not in old_edges and not edge.link_faces:
                bm.edges.remove(edge)
        for vert in reversed(added):
            bm.verts.remove(vert)
        bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)
        raise
    for elements in (bm.verts, bm.edges, bm.faces):
        for element in elements:
            element.select = False
    bm.select_history.clear()
    for face in created:
        face.select_set(True)
    bm.faces.active = created[-1]
    bm.select_flush_mode()
    bm.normal_update()
    bmesh.update_edit_mesh(obj.data, loop_triangles=True, destructive=True)
    return created



