# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Betopo contributors
bl_info = {
    'name': 'Betopo', 'author': 'Betopo contributors', 'version': (0, 1, 10),
    'blender': (5, 1, 0), 'location': 'Betopo workspace > bottom buttons / sidebar',
    'description': 'Surface retopology tools and reusable topology templates',
    'category': 'Mesh',
}

import bpy
from bpy.app.handlers import persistent
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, IntProperty,
                       PointerProperty, StringProperty)

from . import core, operators, tools, dock

REGISTERED = False


def mesh_poll(_settings, obj):
    return obj.type == 'MESH'


def update_symmetry(settings, _context):
    try:
        core.ensure_symmetry(settings)
    except ValueError:
        pass


def update_display(_settings, context):
    for window in context.window_manager.windows:
        if window.workspace.get('betopo_workspace'):
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()


class BETOPO_Settings(bpy.types.PropertyGroup):
    source: PointerProperty(name='Source', type=bpy.types.Object, poll=mesh_poll)
    target: PointerProperty(name='Target', type=bpy.types.Object, poll=mesh_poll)
    tool: EnumProperty(items=[(v, label, '') for v, label in tools.TOOL_NAMES], default='PEN')
    offset: FloatProperty(name='Surface Offset', default=0.0, soft_min=-.05, soft_max=.05, precision=4)
    weld_distance: FloatProperty(name='Weld Distance', default=.001, min=0, precision=5)
    snap_pixels: IntProperty(name='Point Snap (px)', default=12, min=2, max=64)
    segments: IntProperty(name='Segments', default=12, min=3, max=128)
    contour_vertices: IntProperty(name='Loop Vertices', default=8, min=3, max=128)
    strip_width: FloatProperty(name='Strip Width', default=.1, min=.00001, precision=4)
    dot_smooth: FloatProperty(name='Smooth', default=1.0, min=0.0, max=1.0)
    face_sides: EnumProperty(name='Face Type', items=[('4','Quad',''),('3','Triangle','')], default='4')
    points_sides: EnumProperty(name='Face Type', items=[('4','Quad',''),('3','Triangle','')], default='4')
    face_search_radius: IntProperty(name='Face Search (px)', default=220, min=40, max=1000)
    template: EnumProperty(name='Template', items=operators.template_items)
    template_size: FloatProperty(name='Template Size', default=.2, min=.00001, precision=4)
    template_angle: FloatProperty(name='Rotation', subtype='ANGLE', default=0.0)
    brush_radius: IntProperty(name='Brush Radius (px)', default=70, min=5, max=500)
    strength: FloatProperty(name='Strength', default=.35, min=.01, max=1.0)
    tweak_strength: FloatProperty(name='Strength', default=1.0, min=.01, max=1.0)
    iterations: IntProperty(name='Relax Iterations', default=3, min=1, max=20)
    keep_boundary: BoolProperty(name='Keep Boundary', default=True)
    selected_only: BoolProperty(name='Selected Only', default=False)
    symmetry: BoolProperty(name='Symmetry', default=False, update=update_symmetry)
    symmetry_axis: EnumProperty(name='Axis', items=[(a,a,'') for a in 'XYZ'], update=update_symmetry)
    grid_span: IntProperty(name='Grid Span (0 = auto)', default=0, min=0, max=128)
    bridge_cuts: IntProperty(name='Bridge Cuts', default=0, min=0, max=32)
    hole_hover: BoolProperty(name='Detect Holes on Hover', default=True)
    gfill_span: IntProperty(name='Span (0 = auto)', default=0, min=0, max=128)
    gfill_offset: IntProperty(name='Grid Offset', default=0, min=-256, max=256)
    gfill_simple: BoolProperty(name='Simple Blending', default=False)
    slice_radius: IntProperty(name='Edge Search (px)', default=20, min=4, max=80)
    slice_selected_only: BoolProperty(name='Selected Edges Only', default=False)
    status: StringProperty(default='Choose a source and create a retopology target')
    dock_visible: BoolProperty(name='Bottom Buttons', default=True, update=update_display)
    dock_scale: FloatProperty(name='Button Size', default=1.0, min=.7, max=1.5, update=update_display)


def workspace_active(context):
    workspace = context.workspace
    return workspace is not None and bool(workspace.get('betopo_workspace', False))


class VIEW3D_PT_betopo_templates(bpy.types.Panel):
    bl_label = 'Choose a Topology Template'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_options = {'HIDE_HEADER'}
    bl_ui_units_x = 22

    @classmethod
    def poll(cls, context):
        return workspace_active(context)

    def draw(self, context):
        layout, settings = self.layout, context.scene.betopo
        layout.label(text='Choose A–H below each preview')
        grid = layout.grid_flow(row_major=True, columns=4, even_columns=True, even_rows=True)
        icons = operators.PREVIEWS
        for name, data in core.TEMPLATES.items():
            tile = grid.box().column(align=True)
            tile.alignment = 'CENTER'
            if icons and name in icons:
                tile.template_icon(icon_value=icons[name].icon_id, scale=5)
            tile.operator('betopo.template', text=f'{name}  •  {len(data["faces"])} quads',
                          depress=settings.template == name).name = name
        layout.separator()
        layout.label(text='Ctrl + wheel: size')
        layout.label(text='Ctrl + right drag: rotate; Esc: undo rotation')


def draw_tool_parameters(layout, settings):
    if settings.tool == 'PEN':
        layout.prop(settings, 'face_sides')
        layout.prop(settings, 'snap_pixels')
    elif settings.tool == 'POINTS':
        layout.prop(settings, 'points_sides')
        layout.prop(settings, 'snap_pixels')
        layout.prop(settings, 'face_search_radius')
        layout.label(text='Left click: point | Right click: face')
        layout.label(text='Hover between points to preview')
        layout.label(text='Backspace: remove last loose point')
        layout.label(text='Esc: exit | Ctrl+Z: undo')
    elif settings.tool in {'DRAW','DOT'}:
        layout.prop(settings, 'segments')
        layout.prop(settings, 'strip_width')
        if settings.tool=='DOT':
            layout.prop(settings, 'dot_smooth')
            layout.label(text='Left click: add point | Enter: create strip')
            layout.label(text='Backspace: remove last point')
            layout.label(text='Esc: cancel preview, then exit')
    elif settings.tool == 'CONTOUR':
        session = tools.SESSION
        extending = bool(session and session._tool=='CONTOUR' and session._plan and session._plan['existing'])
        row = layout.row()
        row.enabled = not extending
        row.prop(settings, 'contour_vertices')
        if extending:
            layout.label(text=f'Using {session._contour_count} points from selected ring')
        layout.label(text='Draw across source, then Enter')
        layout.label(text='Adjust settings after drawing for live preview')
        layout.label(text='Select a boundary ring to extend')
    elif settings.tool == 'FILL':
        layout.prop(settings, 'hole_hover')
        layout.prop(settings, 'grid_span')
        layout.prop(settings, 'bridge_cuts')
        layout.label(text='Hover a hole; click or Enter to fill')
        layout.label(text='Odd rims: triangles | Bridge: select 2 chains')
        layout.operator('betopo.transition', text='Transition Fill (unequal chains)')
    elif settings.tool == 'GFILL':
        layout.prop(settings, 'hole_hover')
        layout.prop(settings, 'gfill_span')
        layout.prop(settings, 'gfill_offset')
        layout.prop(settings, 'gfill_simple')
        layout.label(text='Hover hole; click to apply quad grid')
        layout.label(text='Even rim required; new points follow Source')
    elif settings.tool == 'SLICE':
        layout.prop(settings, 'slice_radius')
        layout.prop(settings, 'slice_selected_only')
        layout.label(text='Hover along edge to place the cut')
        layout.label(text='Click: create | Esc: cancel preview')
    elif settings.tool == 'STAMP':
        layout.label(text='Choose A–H below the previews')
        grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=True)
        icons = operators.PREVIEWS
        for name, _template in core.TEMPLATES.items():
            tile = grid.box().column(align=True)
            tile.alignment = 'CENTER'
            if icons and name in icons:
                tile.template_icon(icon_value=icons[name].icon_id, scale=3)
            tile.operator('betopo.template', text=name, depress=settings.template == name).name = name
        data = core.TEMPLATES[settings.template]
        layout.label(text=f'{settings.template}: {len(data["vertices"])} points / {len(data["faces"])} quads')
        layout.prop(settings, 'template_size')
        layout.prop(settings, 'template_angle')
        layout.label(text='Move cursor for preview; click to place')
        layout.label(text='Ctrl + wheel: size')
        layout.label(text='Ctrl + right drag: rotate')
    elif settings.tool in {'RELAX','TWEAK'}:
        layout.prop(settings, 'brush_radius')
        layout.prop(settings, 'strength' if settings.tool=='RELAX' else 'tweak_strength')
        if settings.tool == 'RELAX':
            layout.prop(settings, 'iterations')
            layout.prop(settings, 'keep_boundary')
        layout.prop(settings, 'selected_only')


def draw_surface_parameters(layout, settings):
    layout.prop(settings, 'offset')
    layout.prop(settings, 'weld_distance')
    row = layout.row(align=True)
    row.prop(settings, 'symmetry')
    row.prop(settings, 'symmetry_axis', text='')


class VIEW3D_PT_betopo_parameters(bpy.types.Panel):
    bl_label = 'Tool Settings'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_options = {'HIDE_HEADER'}
    bl_ui_units_x = 18

    @classmethod
    def poll(cls, context):
        return workspace_active(context)

    def draw(self, context):
        layout, settings = self.layout, context.scene.betopo
        layout.label(text=dict(tools.TOOL_NAMES)[settings.tool] + ' Settings', icon='PREFERENCES')
        draw_tool_parameters(layout, settings)
        layout.separator()
        layout.label(text='Surface & Symmetry')
        draw_surface_parameters(layout, settings)


class VIEW3D_PT_betopo(bpy.types.Panel):
    bl_label = 'Tool Settings'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Betopo'
    bl_order = 0

    @classmethod
    def poll(cls, context):
        return workspace_active(context)

    def draw(self, context):
        layout, settings = self.layout, context.scene.betopo
        layout.label(text=dict(tools.TOOL_NAMES)[settings.tool], icon='PREFERENCES')
        draw_tool_parameters(layout, settings)
        layout.separator()
        layout.label(text='Left: Point | Right: Face | Esc: Exit' if settings.tool=='POINTS'
                     else 'Enter: Apply preview | Esc: Cancel', icon='INFO')
        layout.label(text='Ctrl/Alt click: existing selection')


class VIEW3D_PT_betopo_surface(bpy.types.Panel):
    bl_label = 'Surface & Symmetry'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Betopo'
    bl_order = 1

    @classmethod
    def poll(cls, context):
        return workspace_active(context)

    def draw(self, context):
        draw_surface_parameters(self.layout, context.scene.betopo)


class VIEW3D_PT_betopo_source(bpy.types.Panel):
    bl_label = 'Source & Target'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Betopo'
    bl_order = 2

    @classmethod
    def poll(cls, context):
        return workspace_active(context)

    def draw(self, context):
        layout, settings = self.layout, context.scene.betopo
        layout.prop(settings, 'source')
        layout.prop(settings, 'target')
        if settings.target and context.mode == 'EDIT_MESH' and context.active_object == settings.target:
            import bmesh
            bm = bmesh.from_edit_mesh(settings.target.data)
            layout.label(text=f'{len(bm.verts)} points | {len(bm.faces)} faces')
        layout.separator()
        for line in settings.status.split('\n'):
            layout.label(text=line[:64])


class VIEW3D_PT_betopo_display(bpy.types.Panel):
    bl_label = 'Display'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Betopo'
    bl_order = 3
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return workspace_active(context)

    def draw(self, context):
        self.layout.prop(context.scene.betopo, 'dock_visible')
        self.layout.prop(context.scene.betopo, 'dock_scale')


def menu_entry(self, _context):
    self.layout.separator()
    self.layout.operator('betopo.workspace', text='Betopo Workspace', icon='WORKSPACE')


@persistent
def loaded(_unused):
    tools.stop_session()
    dock.reset()
    core.SURFACES.clear()
    if REGISTERED and not bpy.app.background and not bpy.app.timers.is_registered(ensure_workspace):
        bpy.app.timers.register(ensure_workspace, first_interval=.5)


def ensure_workspace():
    if not REGISTERED or bpy.app.background:
        return None
    for window in bpy.context.window_manager.windows:
        if not any(w.get('betopo_workspace') for w in bpy.data.workspaces):
            with bpy.context.temp_override(window=window):
                operators.duplicate_workspace(bpy.context)
    return None


CLASSES = (BETOPO_Settings, *operators.CLASSES, *tools.CLASSES, *dock.CLASSES,
           VIEW3D_PT_betopo_templates, VIEW3D_PT_betopo_parameters, VIEW3D_PT_betopo,
           VIEW3D_PT_betopo_surface, VIEW3D_PT_betopo_source, VIEW3D_PT_betopo_display)


def register():
    global REGISTERED
    if REGISTERED:
        return
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.betopo = PointerProperty(type=BETOPO_Settings)
    bpy.types.VIEW3D_MT_mesh_add.append(menu_entry)
    bpy.app.handlers.load_post.append(loaded)
    bpy.app.handlers.depsgraph_update_post.append(core.mark_source_dirty)
    bpy.app.handlers.depsgraph_update_post.append(tools.mark_target_dirty)
    operators.load_previews()
    REGISTERED = True
    if not bpy.app.background:
        dock.start()
        bpy.app.timers.register(ensure_workspace, first_interval=1.0)


def unregister():
    global REGISTERED
    if not REGISTERED:
        return
    REGISTERED = False
    tools.stop_session()
    dock.stop()
    if bpy.app.timers.is_registered(ensure_workspace):
        bpy.app.timers.unregister(ensure_workspace)
    for collection, callback in ((bpy.app.handlers.load_post, loaded),
                                  (bpy.app.handlers.depsgraph_update_post, core.mark_source_dirty),
                                  (bpy.app.handlers.depsgraph_update_post, tools.mark_target_dirty)):
        if callback in collection:
            collection.remove(callback)
    bpy.types.VIEW3D_MT_mesh_add.remove(menu_entry)
    operators.clear_previews()
    del bpy.types.Scene.betopo
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    core.SURFACES.clear()
