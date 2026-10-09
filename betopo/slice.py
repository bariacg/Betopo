# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Betopo contributors
"""One-click quad strip cut; preview never mutates the editable BMesh."""
import bmesh
from bpy_extras import view3d_utils
from mathutils import Vector

from . import core,holes


def strip(start,zero,selected=None):
    if len(start.link_faces)>2:
        raise ValueError('Edge Slice stops at non-manifold edges')
    orientation = {start:zero}
    cells,visited = [],set()
    for first in start.link_faces:
        edge,face = start,first
        while face not in visited:
            if face.hide or any(v.hide for v in face.verts) or len(face.verts)!=4:
                break
            opposite = next(e for e in face.edges if not any(v in edge.verts for v in e.verts))
            if opposite.hide or len(opposite.link_faces)>2 or (selected is not None and opposite not in selected):
                break
            aligned = next(v for v in opposite.verts if any(orientation[edge] in e.verts and v in e.verts
                                                          for e in face.edges))
            if opposite in orientation and orientation[opposite]!=aligned:
                raise ValueError('Twisted quad strip; choose another edge')
            orientation[opposite] = aligned
            visited.add(face)
            cells.append((face,edge,opposite))
            following = [f for f in opposite.link_faces if f!=face]
            if not following:
                break
            edge,face = opposite,following[0]
    if not cells:
        raise ValueError('Hover a quad edge; selected-only needs an edge ring')
    return orientation,cells


def make_plan(obj,start,zero,factor,source,offset=0.0,selected=None):
    orientation,cells = strip(start,zero,selected)
    factor = min(.98,max(.02,factor))
    edges = list(orientation)
    index = {e:i for i,e in enumerate(edges)}
    points = [source.project(obj.matrix_world @ orientation[e].co.lerp(e.other_vert(orientation[e]).co,factor),offset)
              for e in edges]
    plan = core.patch(points,edges=[(index[a],index[b]) for _face,a,b in cells])
    plan.update(slice_edges=edges,slice_zero=orientation,slice_cells=cells,slice_factor=factor)
    return plan


def pick(obj,bm,region,rv3d,cursor,source,offset=0.0,radius=20,selected_only=False):
    chosen = None
    distance = radius**2
    selected = {e for e in bm.edges if e.select and not e.hide} if selected_only else None
    for edge in bm.edges:
        if edge.hide or any(v.hide for v in edge.verts) or len(edge.link_faces)>2 or not any(
                len(f.verts)==4 and not f.hide for f in edge.link_faces):
            continue
        if selected is not None and edge not in selected:
            continue
        a,b = [obj.matrix_world @ v.co for v in edge.verts]
        sa,sb = [view3d_utils.location_3d_to_region_2d(region,rv3d,p) for p in (a,b)]
        if sa is None or sb is None or (sb-sa).length_squared<1:
            continue
        factor = min(1,max(0,(cursor-sa).dot(sb-sa)/(sb-sa).length_squared))
        screen = sa.lerp(sb,factor)
        ds = (screen-cursor).length_squared
        if ds>=distance:
            continue
        origin = view3d_utils.region_2d_to_origin_3d(region,rv3d,screen)
        direction = view3d_utils.region_2d_to_vector_3d(region,rv3d,screen)
        hit = source.hit(origin,direction,offset)
        point = a.lerp(b,factor)
        if hit is None or (hit[0]-point).length>max(source.size*.005,(b-a).length*.3,abs(offset)*2):
            continue
        if source.nearest(point,offset)[1].dot(hit[1])<-.1 or not any(
                holes.visible_on_source(p,region,rv3d,source,offset) for p in (a,b)):
            continue
        chosen,distance = (edge,edge.verts[0],factor),ds
    return make_plan(obj,*chosen,source,offset,selected) if chosen else None


def apply(obj,bm,plan):
    edges,cells = plan['slice_edges'],plan['slice_cells']
    if any(not e.is_valid for e in edges) or any(not f.is_valid for f,_a,_b in cells):
        raise ValueError('Mesh changed; move the cursor to rebuild Edge Slice')
    inverse = obj.matrix_world.inverted_safe()
    positions = {e:inverse @ p for e,p in zip(edges,plan['points'])}
    # Verify the exact utility operations in an isolated copy before touching live data.
    bm.verts.index_update()
    bm.edges.index_update()
    bm.faces.index_update()
    copy = bm.copy()
    copy.verts.ensure_lookup_table()
    copy.edges.ensure_lookup_table()
    copy.faces.ensure_lookup_table()
    copy_edges = {e:copy.edges[e.index] for e in edges}
    copy_cells = [(copy.faces[f.index],copy_edges[a],copy_edges[b]) for f,a,b in cells]
    copy_zero = {copy_edges[e]:copy.verts[plan['slice_zero'][e].index] for e in edges}
    try:
        _vertices,new_edges = _split(copy_edges.values(),copy_cells,copy_zero,plan['slice_factor'],
                                   {copy_edges[e]:p for e,p in positions.items()})
        for face in {f for e in new_edges for f in e.link_faces}:
            coords = [obj.matrix_world @ v.co for v in face.verts]
            center = sum(coords,Vector())/len(coords)
            normal = sum(((a-center).cross(b-center) for a,b in zip(coords,coords[1:]+coords[:1])),Vector())
            turns = [(coords[i]-coords[i-1]).cross(coords[(i+1)%4]-coords[i]).dot(normal) for i in range(4)]
            if normal.length<1e-12 or min(turns)<-1e-10*normal.length_squared or any(
                    (a-b).length_squared<1e-16 for a,b in zip(coords,coords[1:]+coords[:1])):
                raise ValueError('Source projection would collapse or fold the cut; move the cut or use Magnet first')
    finally:
        copy.free()
    vertices,new_edges = _split(edges,cells,plan['slice_zero'],plan['slice_factor'],positions)
    for f in bm.faces:
        f.select_set(False)
    for e in bm.edges:
        e.select_set(e in new_edges)
    for v in bm.verts:
        v.select_set(v in vertices)
    core.refresh(obj,bm)
    return vertices,new_edges


def _split(edges,cells,zero,factor,positions):
    split_vertices = {}
    for edge in edges:
        _new_edge,vert = bmesh.utils.edge_split(edge,zero[edge],factor)
        vert.co = positions[edge]
        split_vertices[edge] = vert
    new_edges = []
    for face,a,b in cells:
        _new_face,loop = bmesh.utils.face_split(face,split_vertices[a],split_vertices[b])
        if loop is None:
            raise ValueError('Cannot split this face')
        new_edges.append(loop.edge)
    return list(split_vertices.values()),new_edges
