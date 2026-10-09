# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Betopo contributors
"""Visible Target boundary picking without changing mesh or selection."""
from collections import defaultdict

from bpy_extras import view3d_utils
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from . import point_faces


def visible_on_source(point,region,rv3d,source,offset=0.0):
    screen = view3d_utils.location_3d_to_region_2d(region,rv3d,point)
    if screen is None:
        return False
    origin = view3d_utils.region_2d_to_origin_3d(region,rv3d,screen)
    direction = view3d_utils.region_2d_to_vector_3d(region,rv3d,screen)
    hit = source.hit(origin,direction,offset)
    return bool(hit and (hit[0]-point).length<=max(source.size*.005,abs(offset)*2,1e-7)
                and source.nearest(point,offset)[1].dot(hit[1])>=-.1)


def boundary_cycles(bm):
    neighbors = defaultdict(list)
    for edge in bm.edges:
        if not edge.hide and len(edge.link_faces)<2 and not any(v.hide for v in edge.verts):
            a,b = edge.verts
            neighbors[a].append(b)
            neighbors[b].append(a)
    remaining,cycles = set(neighbors),[]
    while remaining:
        first = min(remaining,key=lambda v:tuple(v.co))
        component,stack = set(),[first]
        while stack:
            vert = stack.pop()
            if vert not in component:
                component.add(vert)
                stack.extend(neighbors[vert])
        remaining -= component
        if len(component)<3 or any(len(neighbors[v])!=2 for v in component):
            continue
        ring,previous,current = [],None,first
        while current not in ring:
            ring.append(current)
            following = [v for v in neighbors[current] if v!=previous]
            previous,current = current,min(following,key=lambda v:tuple(v.co))
        if current==first and len(ring)==len(component):
            cycles.append(ring)
    return cycles


class HolePicker:
    def __init__(self,obj,bm):
        self.obj,self.bm = obj,bm
        self.dirty = True
        self.cycles = []
        self.tree = None
        self.faces = []
        self.signature = None

    def refresh(self):
        self.cycles = boundary_cycles(self.bm)
        self.faces = [f for f in self.bm.faces if not f.hide]
        verts = list(self.bm.verts)
        index = {v:i for i,v in enumerate(verts)}
        self.tree = BVHTree.FromPolygons([self.obj.matrix_world @ v.co for v in verts],
                       [[index[v] for v in f.verts] for f in self.faces]) if self.faces else None
        self.signature = (len(self.bm.verts),len(self.bm.edges),len(self.bm.faces),
                          tuple(x for row in self.obj.matrix_world for x in row))
        self.dirty = False

    def pick(self,region,rv3d,cursor,source,offset=0.0):
        signature = (len(self.bm.verts),len(self.bm.edges),len(self.bm.faces),
                     tuple(x for row in self.obj.matrix_world for x in row))
        if self.dirty or signature!=self.signature:
            self.refresh()
        origin = view3d_utils.region_2d_to_origin_3d(region,rv3d,cursor)
        direction = view3d_utils.region_2d_to_vector_3d(region,rv3d,cursor)
        hit = source.hit(origin,direction,offset)
        if hit is None:
            return None
        tolerance = max(source.size*.001,abs(offset)*2,1e-7)
        if self.tree:
            co,_normal,index,_distance = self.tree.ray_cast(origin,direction)
            if co is not None:
                face = self.faces[index]
                mean_edge = sum((self.obj.matrix_world @ e.verts[0].co-
                                 self.obj.matrix_world @ e.verts[1].co).length for e in face.edges)/len(face.edges)
                # A low-poly face may sit behind a curved high-poly surface by its chord sag.
                same_side = source.nearest(co,offset)[1].dot(hit[1])>=-.1
                if same_side and (
                        (co-origin).dot(direction)<=(hit[0]-origin).dot(direction)+max(tolerance,mean_edge*.25)):
                    return None
        best,best_area = None,float('inf')
        for ring in self.cycles:
            world = [self.obj.matrix_world @ v.co for v in ring]
            projected = [view3d_utils.location_3d_to_region_2d(region,rv3d,p) for p in world]
            if any(p is None for p in projected):
                continue
            polygon = [tuple(p) for p in projected]
            if not point_faces.inside(cursor,polygon):
                continue
            area = abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(polygon,polygon[1:]+polygon[:1]))*.5)
            if area<4 or area>=best_area:
                continue
            # Ambiguous, self-crossing projections are not a safely selectable hole.
            crossing = any(point_faces.edges_conflict(polygon[i],polygon[(i+1)%len(ring)],
                           polygon[j],polygon[(j+1)%len(ring)])
                           for i in range(len(ring)) for j in range(i+2,len(ring))
                           if not (i==0 and j==len(ring)-1))
            if crossing:
                continue
            visible = sum(visible_on_source(p,region,rv3d,source,offset) for p in world)
            if visible<len(ring)*.75:
                continue
            best,best_area = ring,area
        return best
