# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Betopo contributors
"""Button-activated viewport tools. No global keymaps are installed."""
import math
import time

import bmesh
import bpy
import gpu
from bpy.props import EnumProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from bpy.app.handlers import persistent

from . import core, contours, point_faces, holes, slice, dock

TOOL_NAMES = [('PEN','Add'),('DRAW','Draw'),('CONTOUR','Contours'),
              ('FILL','Fill / Bridge'),('STAMP','Templates'),('RELAX','Relax'),('TWEAK','Tweak'),
              ('POINTS','Points / Faces'),('GFILL','GFill'),('SLICE','Edge Slice'),('DOT','Dot')]
SESSION = None


@persistent
def mark_target_dirty(_scene,depsgraph):
    if SESSION is None or SESSION._closed:
        return
    for update in depsgraph.updates:
        if update.id.original in {SESSION.obj,SESSION.obj.data}:
            SESSION._hole_picker.dirty = True
            SESSION._fill_signature = None


def stop_session():
    if SESSION is not None:
        SESSION.finish(rollback=True)


class BETOPO_OT_tool(bpy.types.Operator):
    bl_idname = 'betopo.tool'
    bl_label = 'Betopo: Activate Tool'
    tool: EnumProperty(items=[(v,label,'') for v,label in TOOL_NAMES])

    def invoke(self,context,_event):
        try:
            core.edit_mesh(context)
            core.surface(context.scene.betopo,context)
        except ValueError as error:
            self.report({'WARNING'},str(error))
            return {'CANCELLED'}
        context.scene.betopo.tool = self.tool
        region = context.region if context.region and context.region.type == 'WINDOW' else next(
            r for r in context.area.regions if r.type == 'WINDOW')
        if SESSION is not None:
            if SESSION.window != context.window or SESSION.area != context.area or SESSION.region != region:
                stop_session()
            else:
                SESSION.change_tool(self.tool)
                return {'FINISHED'}
        with context.temp_override(region=region):
            result = bpy.ops.betopo.session('INVOKE_DEFAULT')
            return {'FINISHED'} if 'RUNNING_MODAL' in result else result


class BETOPO_OT_exit(bpy.types.Operator):
    bl_idname = 'betopo.exit'
    bl_label = 'Betopo: Exit Tool'

    def execute(self,_context):
        stop_session()
        return {'FINISHED'}


class BETOPO_OT_session(bpy.types.Operator):
    bl_idname = 'betopo.session'
    bl_label = 'Betopo Viewport Session'

    def invoke(self,context,event):
        global SESSION
        if SESSION is not None or context.area.type != 'VIEW_3D':
            return {'CANCELLED'}
        if not context.workspace.get('betopo_workspace'):
            self.report({'WARNING'},'Open the Betopo workspace first')
            return {'CANCELLED'}
        try:
            self.obj,self.bm = core.edit_mesh(context)
            self.source = core.surface(context.scene.betopo,context)
        except ValueError as error:
            self.report({'WARNING'},str(error))
            return {'CANCELLED'}
        self.settings = context.scene.betopo
        self.window,self.area,self.region = context.window,context.area,context.region
        self.workspace = context.workspace
        self.rv3d = context.region_data
        self._closed = False
        self._handle = None
        self._timer = None
        self._plan = None
        self._stroke = []
        self._dot_signature = None
        self.reset_stroke_cache()
        self._drawing = False
        self._brush_before = {}
        self._pen = []
        self._pen_refs = {}
        self._placed_points = []
        self._visible_points = []
        self._last_face_preview = 0.0
        self._cursor = None
        self._hit = None
        self._last_hit = None
        self._last_brush = 0.0
        self._fill_signature = None
        self._hole_picker = holes.HolePicker(self.obj,self.bm)
        self._hole_outline = []
        self._contour_count = 0
        self._preview_cancelled = False
        self._rotation = None
        self._tool = self.settings.tool
        self._overlay_before = {}
        overlay = self.area.spaces.active.overlay
        for name,value in (('show_retopology',True),('retopology_offset',.02)):
            if hasattr(overlay,name):
                self._overlay_before[name] = (getattr(overlay,name),value)
                setattr(overlay,name,value)
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_overlay,(),'WINDOW','POST_VIEW')
        self._timer = context.window_manager.event_timer_add(.15,window=context.window)
        context.window_manager.modal_handler_add(self)
        SESSION = self
        if bpy.ops.ed.undo_push.poll():
            bpy.ops.ed.undo_push(message='Betopo: start tool')
        self.change_tool(self._tool)
        return {'RUNNING_MODAL'}

    def change_tool(self,tool):
        self.rollback_brush()
        self.end_rotation(cancel=True)
        self._tool = tool
        self._plan = None
        self._stroke = []
        self._dot_signature = None
        self.reset_stroke_cache()
        self._drawing = False
        self._pen = []
        self._pen_refs = {}
        self._placed_points = []
        self._visible_points = []
        self._hole_outline = []
        self._fill_signature = None
        self._preview_cancelled = False
        self.settings.tool = tool
        if tool == 'PEN':
            selected = [e for e in self.bm.edges if e.select and not e.hide and len(e.link_faces)<2]
            if len(selected)==1:
                self._pen = [self.obj.matrix_world @ v.co for v in selected[0].verts]
                self._pen_refs = dict(enumerate(selected[0].verts))
        if tool in {'FILL','GFILL'}:
            try:
                self.build_fill()
            except ValueError as error:
                self.settings.status = str(error)
        elif tool == 'POINTS':
            self.settings.status = 'Points / Faces: Left click adds points; hover a cell; right click creates its face'
        elif tool == 'SLICE':
            self.settings.status = 'Edge Slice: hover along an edge to position the loop; click to create'
        elif tool == 'DOT':
            self.settings.status = 'Dot: click points on Source; Enter creates the smooth strip; Backspace removes last'
        else:
            self.settings.status = dict(TOOL_NAMES)[tool]+': Left mouse to use; Esc to exit'
        self.area.tag_redraw()

    def build_fill(self):
        try:
            boundaries = core.selected_boundaries(self.bm)
        except ValueError:
            boundaries = []
        bridge = self._tool=='FILL' and len(boundaries)==2 and boundaries[0][1]==boundaries[1][1]
        ring = None
        if not bridge and self.settings.hole_hover and self._cursor is not None:
            ring = self._hole_picker.pick(self.region,self.rv3d,self._cursor,self.source,self.settings.offset)
        if ring is None and not bridge and len(boundaries)==1 and boundaries[0][1] and (
                not self.settings.hole_hover or self._cursor is None):
            candidate = boundaries[0][0]
            if self.bm.faces.get(candidate) is None:
                ring = candidate
        self._hole_outline = [self.obj.matrix_world @ v.co for v in ring] if ring else []
        if not bridge and ring is None:
            self._plan = None
            self._fill_signature = None
            self.settings.status = 'Hover a hole and click; select two boundary chains for Bridge'
            return
        vertices = [v for chain,_closed in boundaries for v in chain] if bridge else ring
        signature = (self._tool,tuple(vertices),tuple(tuple(v.co) for v in vertices),id(self.source),
                     self.settings.offset,self.settings.grid_span,self.settings.bridge_cuts,
                     self.settings.gfill_span,self.settings.gfill_offset,self.settings.gfill_simple)
        if signature==self._fill_signature and self._plan is not None:
            return
        self._plan = None
        self._fill_signature = signature
        if bridge:
            self._plan = core.bridge_plan(self.obj,boundaries[0][0],boundaries[1][0],boundaries[0][1],
                                         self.source,self.settings.offset,self.settings.bridge_cuts)
        elif self._tool=='GFILL':
            self._plan = core.native_grid_fill_plan(self.obj,ring,self.source,self.settings.offset,
                             self.settings.gfill_span,self.settings.gfill_offset,self.settings.gfill_simple)
        elif len(ring)%2:
            self._plan = core.triangle_fill_plan(self.obj,ring,self.source,self.settings.offset)
        else:
            self._plan = core.grid_fill_plan(self.obj,ring,self.source,self.settings.offset,self.settings.grid_span)
        kind = 'triangles (odd rim)' if ring and len(ring)%2 else 'faces'
        self.settings.status = f'Preview: {len(self._plan["faces"])} {kind}; click or Enter to apply'

    def coordinates(self,event):
        return Vector((event.mouse_x-self.region.x,event.mouse_y-self.region.y))

    def release_drawing(self):
        if not self._drawing:
            return
        self._drawing = False
        if self._tool == 'DRAW':
            self.build_draw()
        elif self._tool == 'CONTOUR':
            self.build_contour()
        elif self._brush_before:
            core.refresh(self.obj,self.bm,False)
            if bpy.ops.ed.undo_push.poll():
                bpy.ops.ed.undo_push(message='Betopo: '+self._tool.title())
            self._brush_before = {}

    def hit_at(self,coordinates):
        origin = view3d_utils.region_2d_to_origin_3d(self.region,self.rv3d,coordinates)
        direction = view3d_utils.region_2d_to_vector_3d(self.region,self.rv3d,coordinates)
        return self.source.hit(origin,direction,self.settings.offset)

    def snap_point(self,point):
        nearest,distance = None,self.settings.snap_pixels
        for v in self.bm.verts:
            if v.hide:
                continue
            world = self.obj.matrix_world @ v.co
            screen = view3d_utils.location_3d_to_region_2d(self.region,self.rv3d,world)
            if screen is not None and (screen-self._cursor).length<distance:
                if (world-point).length < max(self.source.size*.05,self.settings.weld_distance):
                    nearest,distance = v,(screen-self._cursor).length
        return (self.obj.matrix_world @ nearest.co,nearest) if nearest else (point,None)

    def pen_click(self):
        if self._hit is None:
            return
        point,vert = self.snap_point(self._hit[0])
        if any((point-p).length<1e-8 for p in self._pen):
            self.settings.status = 'Choose another face corner'
            return
        self._pen_refs[len(self._pen)] = vert
        self._pen.append(point)
        sides = int(self.settings.face_sides)
        if len(self._pen)==sides:
            plan = core.patch(self._pen,[tuple(range(sides))],existing={i:v for i,v in self._pen_refs.items() if v})
            vertices,_faces = self.commit(plan)
            self._pen = [self.obj.matrix_world @ vertices[-1].co,self.obj.matrix_world @ vertices[-2].co]
            self._pen_refs = {0:vertices[-1],1:vertices[-2]}
        else:
            self.settings.status = f'Add: {len(self._pen)}/{sides} corners; Backspace removes last'

    def points_click(self):
        point,vert = self.snap_point(self._hit[0])
        if vert is None:
            point = self.source.project(point,self.settings.offset)
            vertices,_faces = self.commit(core.patch([point]))
            self._placed_points.append(vertices[0])
            self.settings.status = 'Point added; hover between points and right click the preview to make a face'
        else:
            self.settings.status = 'Existing point; hover between points to preview a face'
        self.build_points_face()

    def remove_last_point(self):
        self._placed_points = [v for v in self._placed_points if v.is_valid]
        if not self._placed_points:
            self.settings.status = 'No new loose point to remove; use Ctrl+Z to undo a face'
            return
        vert = self._placed_points[-1]
        if vert.link_edges or vert.link_faces:
            self.settings.status = 'Last point belongs to a face; use Ctrl+Z to undo'
            return
        self._placed_points.pop()
        self.bm.verts.remove(vert)
        core.refresh(self.obj,self.bm)
        if bpy.ops.ed.undo_push.poll():
            bpy.ops.ed.undo_push(message='Betopo: remove loose point')
        self.build_points_face()

    def build_points_face(self):
        self._plan = None
        self._visible_points = []
        if self._cursor is None or self._hit is None:
            return
        radius = self.settings.face_search_radius
        tolerance = max(self.source.size*.005,abs(self.settings.offset)*2,self.settings.weld_distance*2,1e-7)
        screen,world,visible = {},{},{}
        for vert in self.bm.verts:
            if vert.hide:
                continue
            co = self.obj.matrix_world @ vert.co
            projected = view3d_utils.location_3d_to_region_2d(self.region,self.rv3d,co)
            if projected is None:
                continue
            screen[vert],world[vert] = tuple(projected),co
            if (projected-self._cursor).length_squared<=radius**2:
                hit = self.hit_at(projected)
                if hit is not None and (hit[0]-co).length<=tolerance:
                    visible[vert] = tuple(projected)
                    if not vert.link_edges:
                        self._visible_points.append(co)
        eligible = [(v,p) for v,p in visible.items()
                    if not v.link_edges or any(len(e.link_faces)<2 and not e.hide for e in v.link_edges)]
        eligible.sort(key=lambda vp:point_faces.distance_sq(vp[1],self._cursor))
        if len(eligible)<int(self.settings.points_sides):
            return
        def nearby(polygon):
            return (min(p[0] for p in polygon)<=self._cursor.x+radius and
                    max(p[0] for p in polygon)>=self._cursor.x-radius and
                    min(p[1] for p in polygon)<=self._cursor.y+radius and
                    max(p[1] for p in polygon)>=self._cursor.y-radius)
        def surface_visible(vertices,polygon):
            if any(v in visible for v in vertices):
                return True
            middle = sum((Vector(p) for p in polygon),Vector((0,0)))/len(polygon)
            hit = self.hit_at(middle)
            center = sum((world[v] for v in vertices),Vector())/len(vertices)
            return hit is not None and (hit[0]-center).length<=tolerance
        edges = []
        for edge in self.bm.edges:
            a,b = edge.verts
            if edge.hide or a not in screen or b not in screen:
                continue
            polygon = [screen[a],screen[b]]
            if nearby(polygon) and surface_visible((a,b),polygon):
                edges.append((a,b,screen[a],screen[b],len(edge.link_faces)))
        occupied = []
        for face in self.bm.faces:
            if face.hide or any(v not in screen for v in face.verts):
                continue
            polygon = [screen[v] for v in face.verts]
            if nearby(polygon) and surface_visible(face.verts,polygon):
                occupied.append(polygon)
        chosen = point_faces.choose_face(eligible,self._cursor,int(self.settings.points_sides),
                                        edges,occupied,list(visible.items()))
        if chosen:
            self._plan = core.patch([world[v] for v in chosen],[tuple(range(len(chosen)))],
                                    existing=dict(enumerate(chosen)))

    def commit(self,plan):
        if self._tool=='SLICE':
            vertices,edges = slice.apply(self.obj,self.bm,plan)
            result = vertices,[]
            message = f'Edge Slice: {len(edges)} edges'
        else:
            result = core.add_patch(self.obj,self.bm,plan,self.source,self.settings.weld_distance)
            message = f'Applied: {len(plan["faces"])} faces'
        if bpy.ops.ed.undo_push.poll():
            bpy.ops.ed.undo_push(message='Betopo: '+dict(TOOL_NAMES)[self._tool])
        self.settings.status = message
        self._plan = None
        self._stroke = []
        self._dot_signature = None
        self.reset_stroke_cache()
        self._hole_outline = []
        self._fill_signature = None
        self._hole_picker.dirty = True
        return result

    def dot_click(self):
        point = self.source.project(self._hit[0])
        if self._stroke and (point-self._stroke[-1]).length<max(self.source.size*1e-7,1e-9):
            self.settings.status = 'Dot: choose a different point; Backspace removes the last point'
            return
        self._stroke.append(point)
        self._preview_cancelled = False
        self.build_dot()

    def build_dot(self):
        if len(self._stroke)<2:
            self._plan = None
            self._dot_signature = None
            self.settings.status = f'Dot: {len(self._stroke)} points; click another point to preview the strip'
            return
        signature = (tuple(tuple(p) for p in self._stroke),self.settings.segments,self.settings.strip_width,
                     self.settings.dot_smooth,self.settings.offset,id(self.source))
        if self._plan is not None and signature==self._dot_signature:
            return
        self._plan = None
        self._dot_signature = signature
        self._plan = core.dot_plan(self._stroke,self.settings.segments,self.settings.strip_width,self.source,
                                   self.settings.offset,self.settings.dot_smooth)
        self.settings.status = f'Dot: {len(self._stroke)} points / {self.settings.segments} quads; Enter to apply'

    def reset_stroke_cache(self):
        self._stroke_signature = None
        self._contour_plane = None
        self._contour_ring = None
        self._contour_source = None

    def build_draw(self):
        signature = (tuple(tuple(p) for p in self._stroke),self.settings.segments,
                     self.settings.strip_width,self.settings.offset,id(self.source))
        if signature==self._stroke_signature and self._plan is not None:
            return
        self._stroke_signature = signature
        self._plan = None
        self._plan = core.stroke_plan(self._stroke,self.settings.segments,self.settings.strip_width,
                                      self.source,self.settings.offset)
        self.settings.status = f'Strip preview: {self.settings.segments} quads; Enter to apply; Esc cancels'

    def build_contour(self):
        if len(self._stroke)<2:
            raise ValueError('Draw across the source surface')
        if self._contour_plane is None:
            first,last = self._stroke[0],self._stroke[-1]
            tangent = last-first
            view = self.rv3d.view_rotation @ Vector((0,0,-1))
            normal = tangent.cross(view)
            if normal.length<1e-8:
                raise ValueError('Cut stroke is too short; draw across the model')
            self._contour_plane = ((first+last)*.5,normal)
        selected = []
        try:
            boundaries = core.selected_boundaries(self.bm)
            if len(boundaries)==1 and boundaries[0][1]:
                selected = boundaries[0][0]
        except ValueError:
            pass
        count = len(selected) if selected else self.settings.contour_vertices
        signature = (count,self.settings.offset,id(self.source),
                     tuple((v,tuple(v.co)) for v in selected),
                     tuple(x for row in self.obj.matrix_world for x in row))
        if signature==self._stroke_signature and self._plan is not None:
            return
        self._stroke_signature = signature
        self._plan = None
        if self._contour_source is not self.source:
            self._contour_source = self.source
            self._contour_ring = None
            origin,normal = self._contour_plane
            cut = contours.cut_mesh(self.source.vertices,self.source.triangles,origin,normal,
                                    max(self.source.size*1e-7,1e-8))
            if cut['loops']:
                self._contour_ring = min(cut['loops'],key=lambda points:min(
                                        (Vector(p)-origin).length_squared for p in points))
        if self._contour_ring is None:
            raise ValueError('No closed contour found; the source may be open at this cut')
        self._contour_count = count
        ring = [self.source.project(p,self.settings.offset) for p in contours.resample_ring(self._contour_ring,count)]
        if selected:
            previous = [tuple(self.obj.matrix_world @ v.co) for v in selected]
            ring = [Vector(p) for p in contours.align_ring(previous,[tuple(p) for p in ring])]
            coords = [Vector(p) for p in previous]+ring
            faces = [(i,(i+1)%count,count+(i+1)%count,count+i) for i in range(count)]
            self._plan = core.patch(coords,faces,existing=dict(enumerate(selected)),
                                    edges=[(count+i,count+(i+1)%count) for i in range(count)])
        else:
            self._plan = core.patch(ring,edges=[(i,(i+1)%count) for i in range(count)])
        matched = ' (matches selected boundary)' if selected else ''
        self.settings.status = f'Contour preview: {count} points{matched}; Enter to apply'

    def brush_weights(self):
        weights = {}
        pins = self.bm.verts.layers.int.get('betopo_pin')
        for v in self.bm.verts:
            if v.hide or (pins and v[pins]) or (self.settings.selected_only and not v.select):
                continue
            world = self.obj.matrix_world @ v.co
            screen = view3d_utils.location_3d_to_region_2d(self.region,self.rv3d,world)
            if screen is None:
                continue
            distance = (screen-self._cursor).length
            if distance>=self.settings.brush_radius:
                continue
            hit = self.hit_at(screen)
            if hit is None or (hit[0]-world).length>max(self.source.size*.01,abs(self.settings.offset)*2):
                continue
            weights[v] = (1-distance/self.settings.brush_radius)**2
        return weights

    def apply_brush(self):
        if self._hit is None:
            return
        weights = self.brush_weights()
        for v in weights:
            self._brush_before.setdefault(v,v.co.copy())
        if self._tool=='RELAX':
            core.relax_vertices(self.obj,self.bm,self.source,list(weights),self.settings.strength,
                                self.settings.iterations,self.settings.keep_boundary,self.settings.offset,weights)
        elif self._last_hit is not None:
            delta = self._hit[0]-self._last_hit
            inverse = self.obj.matrix_world.inverted_safe()
            for v,weight in weights.items():
                world = self.obj.matrix_world @ v.co
                v.co = inverse @ self.source.project(world+delta*weight*self.settings.tweak_strength,self.settings.offset)
            core.refresh(self.obj,self.bm,False)
        self._last_hit = self._hit[0].copy()

    def rollback_brush(self):
        if self._brush_before:
            for v,co in self._brush_before.items():
                if v.is_valid:
                    v.co = co
            if self.obj.data.is_editmode:
                core.refresh(self.obj,self.bm,False)
        self._brush_before = {}

    def end_rotation(self,cancel=False):
        if self._rotation is not None:
            if cancel:
                self.settings.template_angle = self._rotation[1]
            self._rotation = None

    def finish(self,rollback=False):
        global SESSION
        if self._closed:
            return
        if rollback:
            self.rollback_brush()
        self.end_rotation(cancel=True)
        self._closed = True
        if self._handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._handle,'WINDOW')
            self._handle = None
        if self._timer is not None:
            bpy.context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        try:
            overlay = self.area.spaces.active.overlay
            for name,(old,owned) in self._overlay_before.items():
                if getattr(overlay,name)==owned:
                    setattr(overlay,name,old)
            self.area.tag_redraw()
        except (ReferenceError,AttributeError):
            pass
        if SESSION is self:
            SESSION = None

    def cancel(self,_context):
        self.finish(rollback=True)

    def modal(self,context,event):
        if self._closed:
            return {'CANCELLED'}
        if (context.window!=self.window or self.window.workspace!=self.workspace or
            context.active_object!=self.obj or context.mode!='EDIT_MESH' or self.area.type!='VIEW_3D'):
            self.finish(rollback=True)
            return {'CANCELLED','PASS_THROUGH'}
        if event.type=='TIMER':
            try:
                self.source = core.surface(self.settings,context)
                if self.settings.tool!=self._tool:
                    self.change_tool(self.settings.tool)
                if self._tool=='STAMP' and self._hit and not self._preview_cancelled:
                    self.build_stamp()
                if self._tool=='POINTS' and self._cursor is not None:
                    self._hit = self.hit_at(self._cursor)
                    self.build_points_face()
                if self._tool in {'FILL','GFILL'} and not self._preview_cancelled:
                    self.build_fill()
                if self._tool=='SLICE' and self._cursor is not None and not self._preview_cancelled:
                    self.build_slice()
                if self._tool=='DOT' and self._stroke and not self._preview_cancelled:
                    self.build_dot()
                if self._tool in {'DRAW','CONTOUR'} and self._stroke and not self._drawing and not self._preview_cancelled:
                    if self._tool=='DRAW':
                        self.build_draw()
                    else:
                        self.build_contour()
            except (ValueError,RuntimeError) as error:
                self._plan = None
                self.settings.status = str(error)
            self.area.tag_redraw()
            return {'PASS_THROUGH'}
        coordinates = self.coordinates(event)
        # Capture the whole drag, including release outside the viewport or after Ctrl is released.
        if self._rotation is not None:
            try:
                if event.type=='ESC' and event.value=='PRESS':
                    self.end_rotation(cancel=True)
                    self.build_stamp()
                    self.settings.status = 'Rotation cancelled; move cursor to place'
                elif event.type=='RIGHTMOUSE' and event.value=='RELEASE':
                    self.end_rotation()
                    self.settings.status = 'Rotation set; move cursor to place'
                elif event.type=='MOUSEMOVE':
                    self.settings.template_angle = self._rotation[1]+math.radians(event.mouse_x-self._rotation[0])
                    self.build_stamp()
                elif event.type in {'WHEELUPMOUSE','WHEELDOWNMOUSE'} and event.ctrl and not event.alt:
                    factor = 1.1 if event.type=='WHEELUPMOUSE' else 1/1.1
                    self.settings.template_size *= factor
                    self.build_stamp()
                elif event.type in {'W','E','R','ONE','TWO','THREE','FOUR','FIVE','TAB','DEL','SPACE'} or (
                        event.ctrl and event.type in {'Z','Y'}):
                    if event.value=='PRESS':
                        self.finish(rollback=True)
                        return {'CANCELLED','PASS_THROUGH'}
                self.area.tag_redraw()
            except (ValueError,RuntimeError) as error:
                self.end_rotation(cancel=True)
                self._plan = None
                self.settings.status = str(error)
            return {'RUNNING_MODAL'}
        # Native UI and our bottom buttons own their mouse area, even with region overlap.
        over_ui = dock.native_region_hit(self.area,event)
        over_dock = event.type in dock.MOUSE_EVENTS and dock.dock_hit(context,self.area,self.region,event)
        if over_ui or over_dock:
            if self._drawing and event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
                try:
                    self.release_drawing()
                except (ValueError,RuntimeError) as error:
                    self.settings.status = str(error)
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}
        inside = 0<=coordinates.x<self.region.width and 0<=coordinates.y<self.region.height
        if not inside:
            return {'PASS_THROUGH'}
        self._cursor = coordinates
        if self._tool=='STAMP' and event.type=='RIGHTMOUSE' and event.value=='PRESS' and event.ctrl and not event.alt:
            self._hit = self.hit_at(coordinates)
            if self._hit is not None:
                self._rotation = (event.mouse_x,self.settings.template_angle)
                self._preview_cancelled = False
                self.build_stamp()
                self.settings.status = 'Drag right mouse to rotate; release to keep; Esc to undo rotation'
                self.area.tag_redraw()
            return {'RUNNING_MODAL'}
        # Existing keyboard actions leave the session before normal Blender dispatch.
        if event.type in {'W','E','R','ONE','TWO','THREE','FOUR','FIVE','TAB','DEL','SPACE'} or (
                event.ctrl and event.type in {'Z','Y'}):
            if event.value=='PRESS':
                self.finish(rollback=True)
                return {'CANCELLED','PASS_THROUGH'}
        if event.type in {'MIDDLEMOUSE','LEFT_ALT','RIGHT_ALT'}:
            if event.type=='MIDDLEMOUSE' and event.value=='PRESS' and self._drawing:
                self.rollback_brush()
                self._drawing = False
                self._stroke = []
                self._plan = None
                self.reset_stroke_cache()
            return {'PASS_THROUGH'}
        if event.type in {'WHEELUPMOUSE','WHEELDOWNMOUSE'}:
            if self._tool=='STAMP' and event.ctrl and not event.alt:
                factor = 1.1 if event.type=='WHEELUPMOUSE' else 1/1.1
                self.settings.template_size *= factor
                self.build_stamp()
                self.area.tag_redraw()
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}
        if self._tool=='POINTS' and event.type=='RIGHTMOUSE':
            if event.ctrl or event.alt or event.shift:
                return {'PASS_THROUGH'}
            if event.value=='PRESS':
                try:
                    self._hit = self.hit_at(coordinates)
                    self.build_points_face()
                    if self._plan:
                        self.commit(self._plan)
                        self.build_points_face()
                    else:
                        self.settings.status = 'No valid face here; hover inside the points or increase Face Search'
                except (ValueError,RuntimeError) as error:
                    self._plan = None
                    self.settings.status = str(error)
                    self.report({'WARNING'},str(error))
                self.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if self._tool=='POINTS' and event.type=='ESC' and event.value=='PRESS':
            self.finish(rollback=True)
            return {'CANCELLED'}
        if event.type in {'ESC','RIGHTMOUSE'} and event.value=='PRESS':
            if self._plan is not None or self._pen or self._drawing or (self._tool=='DOT' and self._stroke):
                self.rollback_brush()
                self._plan,self._pen,self._pen_refs,self._stroke,self._drawing = None,[],{},[],False
                self._hole_outline = []
                self._dot_signature = None
                self.reset_stroke_cache()
                self._preview_cancelled = True
                self.settings.status = 'Preview cancelled; Esc again exits tool'
                self.area.tag_redraw()
                return {'RUNNING_MODAL'}
            self.finish(rollback=True)
            return {'CANCELLED'}
        try:
            if event.type=='BACK_SPACE' and event.value=='PRESS' and self._tool=='DOT':
                if self._stroke:
                    self._stroke.pop()
                self.build_dot()
                self.area.tag_redraw()
                return {'RUNNING_MODAL'}
            if event.type=='BACK_SPACE' and event.value=='PRESS' and self._tool=='POINTS':
                self.remove_last_point()
                self.area.tag_redraw()
                return {'RUNNING_MODAL'}
            if event.type=='BACK_SPACE' and event.value=='PRESS' and self._tool=='PEN':
                if self._pen:
                    self._pen_refs.pop(len(self._pen)-1,None)
                    self._pen.pop()
                self.area.tag_redraw()
                return {'RUNNING_MODAL'}
            if event.type in {'RET','NUMPAD_ENTER'} and event.value=='PRESS' and self._tool in {'DRAW','CONTOUR'} and (
                    self._stroke and not self._drawing and not self._preview_cancelled):
                self.source = core.surface(self.settings,context)
                if self._tool=='DRAW':
                    self.build_draw()
                else:
                    self.build_contour()
            if event.type in {'RET','NUMPAD_ENTER'} and event.value=='PRESS' and self._plan and self._tool!='POINTS':
                vertices,_faces = self.commit(self._plan)
                if self._tool=='CONTOUR':
                    count = self._contour_count
                    rim = vertices[-count:]
                    for face in self.bm.faces:
                        face.select_set(False)
                    for e in self.bm.edges:
                        e.select_set(e.verts[0] in rim and e.verts[1] in rim)
                    for v in self.bm.verts:
                        v.select_set(v in rim)
                    self.bm.select_flush_mode()
                    core.refresh(self.obj,self.bm,False)
                return {'RUNNING_MODAL'}
            if event.type=='MOUSEMOVE':
                self._preview_cancelled = False
                self._hit = self.hit_at(coordinates)
                if self._tool=='STAMP':
                    self.build_stamp()
                if self._tool in {'FILL','GFILL'}:
                    self.build_fill()
                if self._tool=='SLICE':
                    self.build_slice()
                if self._tool=='POINTS' and time.monotonic()-self._last_face_preview>.04:
                    self.build_points_face()
                    self._last_face_preview = time.monotonic()
                if self._drawing and self._hit:
                    if self._tool in {'DRAW','CONTOUR'}:
                        if not self._stroke or (self._hit[0]-self._stroke[-1]).length>self.source.size*.0005:
                            self._stroke.append(self._hit[0].copy())
                    elif time.monotonic()-self._last_brush>.025:
                        self.apply_brush()
                        self._last_brush = time.monotonic()
                self.area.tag_redraw()
                return {'PASS_THROUGH'} if not self._drawing else {'RUNNING_MODAL'}
            if event.type=='LEFTMOUSE':
                if event.ctrl or event.alt or event.shift:
                    return {'PASS_THROUGH'}
                if event.value=='PRESS':
                    self._hit = self.hit_at(coordinates)
                    if self._hit is None:
                        return {'PASS_THROUGH'}
                    if self._tool=='PEN':
                        self.pen_click()
                    elif self._tool=='DOT':
                        self.dot_click()
                    elif self._tool=='POINTS':
                        self.points_click()
                    elif self._tool in {'FILL','GFILL'}:
                        self.build_fill()
                        if self._plan:
                            self.commit(self._plan)
                    elif self._tool=='SLICE':
                        self.build_slice()
                        if self._plan:
                            self.commit(self._plan)
                    elif self._tool=='STAMP':
                        self.build_stamp()
                        if self._plan:
                            self.commit(self._plan)
                    elif self._tool in {'DRAW','CONTOUR','RELAX','TWEAK'}:
                        self._drawing = True
                        self._plan = None
                        self._stroke = [self._hit[0].copy()]
                        self.reset_stroke_cache()
                        self._preview_cancelled = False
                        self._last_hit = self._hit[0].copy()
                        if self._tool in {'RELAX','TWEAK'}:
                            self.apply_brush()
                    self.area.tag_redraw()
                    return {'RUNNING_MODAL'}
                if event.value=='RELEASE':
                    self.release_drawing()
                    return {'RUNNING_MODAL'}
                return {'RUNNING_MODAL'}
        except (ValueError,RuntimeError) as error:
            self.settings.status = str(error)
            self.report({'WARNING'},str(error))
            self._drawing = False
            self.rollback_brush()
        return {'PASS_THROUGH'}

    def build_stamp(self):
        if self._hit is None:
            self._plan = None
            return
        direction = self.rv3d.view_rotation @ Vector((1,0,0))
        self._plan = core.template_plan(self.settings.template,self._hit[0],self._hit[1],direction,
                                       self.settings.template_size,self.settings.template_angle,
                                       self.source,self.settings.offset)

    def build_slice(self):
        self._plan = slice.pick(self.obj,self.bm,self.region,self.rv3d,self._cursor,self.source,
                               self.settings.offset,self.settings.slice_radius,self.settings.slice_selected_only)
        if self._plan:
            percent = round(self._plan['slice_factor']*100)
            self.settings.status = f'Edge Slice: {percent}% along edge; click or Enter to cut'
        else:
            self.settings.status = 'Hover a quad edge to preview the loop; slide toward either end'

    def draw_overlay(self):
        if self._closed or bpy.context.area!=self.area or bpy.context.region!=self.region:
            return
        lines,points = [],[]
        if self._plan:
            points = self._plan['points']
            pairs = set(tuple(sorted((a,b))) for face in self._plan['faces']
                        for a,b in zip(face,face[1:]+face[:1]))
            pairs.update(self._plan['edges'])
            lines = [tuple(points[i]) for pair in pairs for i in pair]
        elif self._tool=='PEN' and self._pen:
            points = self._pen+([self._hit[0]] if self._hit else [])
            lines = [tuple(p) for a,b in zip(points,points[1:]) for p in (a,b)]
        elif self._stroke:
            points = self._stroke
            lines = [tuple(p) for a,b in zip(points,points[1:]) for p in (a,b)]
        if self._tool=='POINTS':
            points = list({tuple(p):p for p in [*points,*self._visible_points]}.values())
        if self._tool=='DOT':
            points = [self.source.project(p,self.settings.offset) for p in self._stroke]
            if self._plan:
                curve = self._plan['curve']
                lines.extend(tuple(p) for a,b in zip(curve,curve[1:]) for p in (a,b))
        if self._hole_outline:
            lines.extend(tuple(p) for a,b in zip(self._hole_outline,self._hole_outline[1:]+self._hole_outline[:1])
                         for p in (a,b))
        if self._tool in {'RELAX','TWEAK'} and self._hit:
            center,normal = self._hit
            u = self.rv3d.view_rotation @ Vector((1,0,0))
            u = (u-normal*u.dot(normal)).normalized()
            v = normal.cross(u).normalized()
            # Match the brush radius in pixels on the current depth plane.
            edge = view3d_utils.region_2d_to_location_3d(self.region,self.rv3d,
                       self._cursor+Vector((self.settings.brush_radius,0)),center)
            radius = (edge-center).length
            circle = [center+radius*(u*math.cos(i*math.tau/48)+v*math.sin(i*math.tau/48)) for i in range(49)]
            lines.extend(tuple(p) for a,b in zip(circle,circle[1:]) for p in (a,b))
        if not lines and not points:
            return
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        depth,blend = gpu.state.depth_test_get(),gpu.state.blend_get()
        width = gpu.state.line_width_get()
        try:
            gpu.state.depth_test_set('NONE')
            gpu.state.blend_set('ALPHA')
            gpu.state.line_width_set(2.0)
            shader.bind()
            if self._tool in {'POINTS','FILL','GFILL','DOT'} and self._plan and self._plan['faces']:
                face_points = self._plan['points']
                tris = [tuple(face_points[j]) for face in self._plan['faces']
                        for i in range(1,len(face)-1) for j in (face[0],face[i],face[i+1])]
                shader.uniform_float('color',(.12,.75,1.0,.22))
                batch_for_shader(shader,'TRIS',{'pos':tris}).draw(shader)
            shader.uniform_float('color',(.12,.85,1.0,1.0) if self._tool=='DOT' or
                                 (self._tool in {'POINTS','FILL','GFILL','SLICE'} and self._plan)
                                 else (1.0,.65,.12,1.0))
            if lines:
                batch_for_shader(shader,'LINES',{'pos':lines}).draw(shader)
            if points:
                if self._tool in {'POINTS','DOT'}:
                    # Screen-sized discs avoid changing Blender's global GPU point-size state.
                    discs = []
                    for co in points:
                        screen = view3d_utils.location_3d_to_region_2d(self.region,self.rv3d,co)
                        if screen is None:
                            continue
                        rim = [view3d_utils.region_2d_to_location_3d(self.region,self.rv3d,
                               screen+4*Vector((math.cos(i*math.tau/12),math.sin(i*math.tau/12))),co)
                               for i in range(12)]
                        discs.extend(tuple(p) for a,b in zip(rim,rim[1:]+rim[:1]) for p in (co,a,b))
                    if discs:
                        batch_for_shader(shader,'TRIS',{'pos':discs}).draw(shader)
                else:
                    batch_for_shader(shader,'POINTS',{'pos':[tuple(p) for p in points]}).draw(shader)
        finally:
            gpu.state.depth_test_set(depth)
            gpu.state.blend_set(blend)
            gpu.state.line_width_set(width)


CLASSES = (BETOPO_OT_tool,BETOPO_OT_exit,BETOPO_OT_session)
