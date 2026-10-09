# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Betopo contributors
import math
from pathlib import Path

import bmesh
import bpy
import bpy.utils.previews
from bpy.props import EnumProperty, StringProperty
from mathutils import Matrix, Vector

from . import core

PREVIEWS = None
# Keep enum strings alive for Blender and preserve A–F's saved numeric values.
TEMPLATE_ITEMS = [(name, name, f'{len(data["faces"])} quad faces', 0, i)
                  for i, (name, data) in enumerate(core.TEMPLATES.items())]


def template_items(_settings, _context):
    return TEMPLATE_ITEMS


def load_previews():
    global PREVIEWS, TEMPLATE_ITEMS
    PREVIEWS = bpy.utils.previews.new()
    for name in core.TEMPLATES:
        path = Path(__file__).with_name('icons') / (name + '.png')
        if path.exists():
            PREVIEWS.load(name, str(path), 'IMAGE')
    TEMPLATE_ITEMS = [(name, name, f'{len(data["faces"])} quad faces',
                       PREVIEWS[name].icon_id if name in PREVIEWS else 0, i)
                      for i, (name, data) in enumerate(core.TEMPLATES.items())]


def clear_previews():
    global PREVIEWS, TEMPLATE_ITEMS
    if PREVIEWS:
        bpy.utils.previews.remove(PREVIEWS)
    PREVIEWS = None
    TEMPLATE_ITEMS = [(name, name, f'{len(data["faces"])} quad faces', 0, i)
                      for i, (name, data) in enumerate(core.TEMPLATES.items())]


def view_region(area):
    return next(r for r in area.regions if r.type == 'WINDOW')


def duplicate_workspace(context):
    """Load a clean layout instead of copying a screen with a live native Tooltip.

    In Blender 5.1 both workspace duplication and serializing the active screen
    can copy/free its transient Tooltip. Our bundled layout was saved without UI
    running; loading it creates fresh regions and never activates another tab.
    """
    view = next((a.spaces.active.region_3d for a in context.window.screen.areas
                 if a.type == 'VIEW_3D'), None)
    values = {key: getattr(view, key).copy() if key in {'view_location', 'view_rotation'}
              else getattr(view, key)
              for key in ('view_location', 'view_rotation', 'view_distance', 'view_perspective')} if view else {}
    path = str(Path(__file__).with_name('workspace.blend'))
    with bpy.data.libraries.load(path, link=False) as (_source, loaded):
        loaded.workspaces = ['Betopo']
    workspace = loaded.workspaces[0]
    if workspace is None:
        raise RuntimeError('Could not create the Betopo workspace')
    obj = context.view_layer.objects.active
    workspace.object_mode = obj.mode if obj else 'OBJECT'
    for screen in workspace.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                for key, value in values.items():
                    setattr(area.spaces.active.region_3d, key, value)
    workspace.name = 'Betopo'
    workspace['betopo_workspace'] = True
    return workspace


def activate_workspace(context):
    window = context.window
    workspace = next((w for w in bpy.data.workspaces if w.get('betopo_workspace')), None)
    if workspace is None:
        workspace = duplicate_workspace(context)
    window.workspace = workspace
    for area in window.screen.areas:
        if area.type == 'VIEW_3D':
            from . import dock
            dock.focus_sidebar(area)
    return workspace


class BETOPO_OT_workspace(bpy.types.Operator):
    bl_idname = 'betopo.workspace'
    bl_label = 'Open Betopo Workspace'
    bl_description = 'Open the separate Betopo workspace without replacing existing workspaces or keymaps'

    def execute(self, context):
        activate_workspace(context)
        return {'FINISHED'}


class BETOPO_OT_setup(bpy.types.Operator):
    bl_idname = 'betopo.setup'
    bl_label = 'Betopo: New Retopology Target'
    bl_options = {'REGISTER','UNDO'}

    def execute(self, context):
        settings = context.scene.betopo
        source = settings.source
        if source is None and context.active_object and context.active_object.type == 'MESH':
            source = context.active_object
        if source is None or source.type != 'MESH' or source == settings.target:
            self.report({'WARNING'}, 'Choose the high-poly Source first')
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        settings.source = source
        mesh = bpy.data.meshes.new('Betopo Retopology')
        obj = bpy.data.objects.new('Betopo_' + source.name, mesh)
        context.collection.objects.link(obj)
        obj.matrix_world = source.matrix_world.copy()
        obj.show_in_front = True
        obj.color = (.18,.65,1.0,1.0)
        for other in context.view_layer.objects:
            if other.select_get():
                other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        settings.target = obj
        source_surface = core.surface(settings, context)
        settings.strip_width = max(source_surface.size * .04, .0001)
        settings.template_size = max(source_surface.size * .12, .0001)
        settings.weld_distance = max(source_surface.size * .0001, .000001)
        core.ensure_symmetry(settings)
        if not bpy.app.background:
            activate_workspace(context)
        bpy.ops.object.mode_set(mode='EDIT')
        settings.status = 'Ready: choose Add, Points / Faces, Draw, Contours or a Template'
        return {'FINISHED'}


class BETOPO_OT_edit_target(bpy.types.Operator):
    bl_idname = 'betopo.edit_target'
    bl_label = 'Betopo: Edit Target'

    def execute(self, context):
        obj = context.scene.betopo.target
        if not obj or obj.name not in context.view_layer.objects:
            self.report({'WARNING'}, 'Choose a Target in this scene')
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for other in context.view_layer.objects:
            if other.select_get():
                other.select_set(False)
        obj.hide_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        return {'FINISHED'}


class BETOPO_OT_template(bpy.types.Operator):
    bl_idname = 'betopo.template'
    bl_label = 'Betopo: Select Topology Template'
    name: StringProperty()

    def execute(self, context):
        if self.name not in core.TEMPLATES:
            return {'CANCELLED'}
        context.scene.betopo.template = self.name
        bpy.ops.betopo.tool('INVOKE_DEFAULT', tool='STAMP')
        return {'FINISHED'}


class BETOPO_OT_action(bpy.types.Operator):
    bl_idname = 'betopo.action'
    bl_label = 'Betopo: Mesh Action'
    bl_options = {'REGISTER','UNDO'}
    action: EnumProperty(items=[(v,v,'') for v in ('PROJECT','RELAX','PIN','UNPIN','WELD')])

    @classmethod
    def description(cls,_context,properties):
        if properties.action=='PROJECT':
            return 'Magnet: move selected vertices onto the nearest Source surface, using Surface Offset'
        return 'Apply '+properties.action.title()+' to selected vertices'

    def execute(self, context):
        from . import tools
        tools.stop_session()
        try:
            obj, bm = core.edit_mesh(context)
            settings = context.scene.betopo
            vertices = [v for v in bm.verts if v.select and not v.hide]
            if not vertices:
                raise ValueError('Select vertices first')
            if self.action in {'PIN','UNPIN'}:
                layer = bm.verts.layers.int.get('betopo_pin') or bm.verts.layers.int.new('betopo_pin')
                vertices = [v for v in bm.verts if v.select and not v.hide]
                for v in vertices:
                    v[layer] = int(self.action == 'PIN')
            elif self.action == 'RELAX':
                core.relax_vertices(obj,bm,core.surface(settings,context),vertices,settings.strength,
                                    settings.iterations,settings.keep_boundary,settings.offset)
            elif self.action == 'PROJECT':
                source = core.surface(settings,context)
                inverse = obj.matrix_world.inverted_safe()
                for v in vertices:
                    v.co = inverse @ source.project(obj.matrix_world @ v.co,settings.offset)
            elif self.action == 'WELD':
                # World-distance comparisons also work with nonuniform Target transforms.
                mapping, remaining = {}, set(vertices)
                for v in vertices:
                    if v not in remaining:
                        continue
                    for w in list(remaining):
                        if w != v and (obj.matrix_world @ v.co - obj.matrix_world @ w.co).length <= settings.weld_distance:
                            mapping[w] = v
                            remaining.remove(w)
                if mapping:
                    bmesh.ops.weld_verts(bm,targetmap=mapping)
            core.refresh(obj,bm)
            settings.status = ('Magnet' if self.action=='PROJECT' else self.action.title()) + ': done'
        except (ValueError,RuntimeError) as error:
            self.report({'WARNING'},str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


class BETOPO_OT_transition(bpy.types.Operator):
    bl_idname = 'betopo.transition'
    bl_label = 'Betopo: Transition Fill'
    bl_description = 'Connect unequal open chains using supported transition patches (may include triangles or ngons)'
    bl_options = {'REGISTER','UNDO'}

    def execute(self, context):
        from . import tools, transition
        tools.stop_session()
        try:
            obj, bm = core.edit_mesh(context)
            source = core.surface(context.scene.betopo,context)
            _,_,a,b = transition.selection(context)
            plan = transition.plan(obj,bm,a,b)
            # Transfer its validated plan into our world-space application path.
            originals,coords,_sources,faces,_points,_templates = plan
            points = [obj.matrix_world @ co for co in coords]
            for i in range(len(originals),len(points)):
                points[i] = source.project(points[i],context.scene.betopo.offset)
            core.add_patch(obj,bm,core.patch(points,faces,existing=dict(enumerate(originals))),source)
            context.scene.betopo.status = f'Transition Fill: {len(faces)} faces'
        except (ValueError,RuntimeError) as error:
            self.report({'WARNING'},str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


class BETOPO_OT_native(bpy.types.Operator):
    bl_idname = 'betopo.native'
    bl_label = 'Betopo: Native Mesh Tool'
    action: EnumProperty(items=[('LOOP','Loop Cut',''),('KNIFE','Knife','')])

    def execute(self, context):
        from . import tools
        tools.stop_session()
        try:
            core.edit_mesh(context)
            with context.temp_override(region=view_region(context.area)):
                if self.action == 'LOOP':
                    bpy.ops.mesh.loopcut_slide('INVOKE_DEFAULT')
                else:
                    bpy.ops.mesh.knife_tool('INVOKE_DEFAULT')
        except (ValueError,RuntimeError) as error:
            self.report({'WARNING'},str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


class BETOPO_OT_check(bpy.types.Operator):
    bl_idname = 'betopo.check'
    bl_label = 'Betopo: Check Topology'

    def execute(self, context):
        try:
            _obj,bm = core.edit_mesh(context)
            quads = sum(len(f.verts)==4 for f in bm.faces)
            bad = sum(len(e.link_faces)>2 for e in bm.edges)
            loose = sum(not e.link_faces for e in bm.edges)
            zero = sum(f.calc_area()<1e-12 for f in bm.faces)
            message = f'{quads}/{len(bm.faces)} quads; {bad} nonmanifold; {loose} loose; {zero} zero-area'
            context.scene.betopo.status = message
            self.report({'INFO'},message)
        except ValueError as error:
            self.report({'WARNING'},str(error))
            return {'CANCELLED'}
        return {'FINISHED'}


CLASSES = (BETOPO_OT_workspace,BETOPO_OT_setup,BETOPO_OT_edit_target,BETOPO_OT_template,
           BETOPO_OT_action,BETOPO_OT_transition,BETOPO_OT_native,BETOPO_OT_check)
