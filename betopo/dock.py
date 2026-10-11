# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Betopo contributors
"""Workspace-only bottom buttons, native Sidebar focus, and mouse event routing."""
import bpy

ITEMS = [
    ('NEW', 'New Retopo'), ('EDIT', 'Edit Target'),
    ('PEN', 'Add'), ('POINTS', 'Points / Faces'), ('DRAW', 'Draw'), ('DOT', 'Dot'),
    ('AREA', 'Area'), ('FLOW', 'Flow'),
    ('CONTOUR', 'Contours'), ('FILL', 'Fill / Bridge'), ('GFILL', 'GFill'),
    ('SLICE', 'Edge Slice'), ('STAMP', 'Templates'), ('RELAX', 'Relax'), ('TWEAK', 'Tweak'),
    ('PROJECT', 'Magnet'), ('RELAX_SELECTED', 'Relax Selected'), ('PIN', 'Pin'),
    ('UNPIN', 'Unpin'), ('WELD', 'Weld'), ('LOOP', 'Loop Cut'), ('KNIFE', 'Knife'),
    ('TRANSITION', 'Transition Fill'), ('CHECK', 'Check Topology'), ('EXIT', 'Exit Tool'),
]
SHORTCUTS = {'B': 'TWEAK', 'V': 'POINTS', 'E': 'SLICE'}
MOUSE_EVENTS = {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE',
                'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE',
                'TRACKPADPAN', 'TRACKPADZOOM', 'BUTTON4MOUSE', 'BUTTON5MOUSE'}
CONTROLLERS = {}
HANDLE = None
ENABLED = False


def active(workspace):
    return workspace is not None and bool(workspace.get('betopo_workspace'))


def contains(rect, x, y):
    return rect is not None and rect[0] <= x < rect[0] + rect[2] and rect[1] <= y < rect[1] + rect[3]


def native_region_hit(area, event):
    """Overlapping Sidebar/Toolbar regions still occupy real interactive screen space."""
    space = area.spaces.active
    for region in area.regions:
        if region.type not in {'UI', 'TOOLS', 'HEADER', 'TOOL_HEADER', 'ASSET_SHELF', 'ASSET_SHELF_HEADER'}:
            continue
        if region.type == 'UI' and not space.show_region_ui:
            continue
        if region.type == 'TOOLS' and not space.show_region_toolbar:
            continue
        if region.width > 1 and region.height > 1 and contains(
                (region.x, region.y, region.width, region.height), event.mouse_x, event.mouse_y):
            return True
    return False


def ui_scale(context):
    return max(.5, min(3.0, context.preferences.system.ui_scale)) * context.scene.betopo.dock_scale


def native_modal_active(window):
    # Native navigation/mesh tools own input while the dock remains visible.
    return any(not op.bl_rna.identifier.startswith('BETOPO_OT_')
               for op in window.modal_operators)


def shortcut_context(context, event):
    """Resolve plain tool keys only over an editable Betopo viewport, never native UI."""
    identifier = SHORTCUTS.get(event.type)
    window = context.window
    if (identifier is None or event.value not in {'PRESS', 'RELEASE'} or window is None
            or not active(window.workspace) or event.ctrl or event.shift or event.alt or event.oskey
            or getattr(event, 'hyper', False)
            or native_modal_active(window)):
        return None
    for area in window.screen.areas:
        if area.type != 'VIEW_3D' or native_region_hit(area, event):
            continue
        region = next((r for r in area.regions if r.type == 'WINDOW' and contains(
            (r.x, r.y, r.width, r.height), event.mouse_x, event.mouse_y)), None)
        if region is not None:
            with context.temp_override(window=window, area=area, region=region):
                if identifier not in disabled_ids(bpy.context):
                    return area, region, identifier
    return None


def layout_for(context, area, region):
    if not ENABLED or not active(context.workspace) or not context.scene.betopo.dock_visible:
        return None
    from . import dock_draw
    left = right = 0
    for other in area.regions:
        if other.width <= 1 or other.height <= 1:
            continue
        overlap = max(0, min(region.x + region.width, other.x + other.width) - max(region.x, other.x))
        if other.type == 'UI' and area.spaces.active.show_region_ui:
            right = max(right, overlap)
        elif other.type == 'TOOLS' and area.spaces.active.show_region_toolbar:
            left = max(left, overlap)
    hints = {identifier: key for key, identifier in SHORTCUTS.items()}
    return dock_draw.layout(region.width, region.height, left, right, ui_scale(context),
                            [{'id': key, 'label': label + (' [' + hints[key] + ']' if key in hints else '')}
                             for key, label in ITEMS])


def dock_hit(context, area, region, event):
    if native_modal_active(context.window) or native_region_hit(area, event):
        return None
    layout = layout_for(context, area, region)
    if layout and contains(layout['rect'], event.mouse_x - region.x, event.mouse_y - region.y):
        return layout
    return None


def disabled_ids(context):
    from . import tools
    settings = context.scene.betopo
    obj = context.active_object
    editing = obj is not None and obj == settings.target and context.mode == 'EDIT_MESH'
    source = settings.source
    valid_source = source is not None and source.type == 'MESH' and source != settings.target
    selected_source = obj is not None and obj.type == 'MESH' and obj != settings.target
    disabled = set()
    if not valid_source and not selected_source:
        disabled.add('NEW')
    if settings.target is None or settings.target.name not in context.view_layer.objects:
        disabled.add('EDIT')
    if not editing:
        disabled.update(key for key, _label in ITEMS if key not in {'NEW', 'EDIT', 'EXIT'})
    elif not valid_source:
        disabled.update([key for key, _label in tools.TOOL_NAMES] + ['PROJECT', 'RELAX_SELECTED', 'TRANSITION'])
    if tools.SESSION is None:
        disabled.add('EXIT')
    return disabled


def draw():
    context = bpy.context
    area, region = context.area, context.region
    if area is None or area.type != 'VIEW_3D' or region is None or region.type != 'WINDOW':
        return
    layout = layout_for(context, area, region)
    if not layout or not layout['buttons']:
        return
    from . import tools, dock_draw
    controller = CONTROLLERS.get(context.window.as_pointer())
    hover = controller.hover if controller and controller.hover_area == area.as_pointer() and controller.hover_region == region.as_pointer() else None
    selected = tools.SESSION._tool if tools.SESSION is not None and tools.SESSION.area == area else None
    dock_draw.draw(layout, active_id=selected, hover_id=hover, disabled_ids=disabled_ids(context),
                   scale=ui_scale(context))


def focus_sidebar(area):
    """Select our native tab only on entry/tool clicks; users may still collapse or change tabs."""
    if area.type != 'VIEW_3D':
        return False
    space = area.spaces.active
    space.show_region_ui = True
    space.show_region_tool_header = False
    area.tag_redraw()
    region = next((r for r in area.regions if r.type == 'UI'), None)
    if region is None:
        return False
    try:
        region.active_panel_category = 'Betopo'
    except (AttributeError, TypeError, ValueError):
        return False  # Tab categories are populated after Blender draws the Sidebar.
    return True


def dispatch(context, area, region, identifier):
    from . import tools
    with context.temp_override(window=context.window, area=area, region=region):
        if identifier in disabled_ids(bpy.context):
            return
        focus_sidebar(area)
        if identifier in dict(tools.TOOL_NAMES):
            bpy.ops.betopo.tool('INVOKE_DEFAULT', tool=identifier)
        elif identifier in {'PROJECT', 'PIN', 'UNPIN', 'WELD', 'RELAX_SELECTED'}:
            bpy.ops.betopo.action('EXEC_DEFAULT', action='RELAX' if identifier == 'RELAX_SELECTED' else identifier)
        elif identifier in {'LOOP', 'KNIFE'}:
            bpy.ops.betopo.native('EXEC_DEFAULT', action=identifier)
        else:
            operator = {'NEW': 'setup', 'EDIT': 'edit_target', 'TRANSITION': 'transition',
                        'CHECK': 'check', 'EXIT': 'exit'}[identifier]
            if identifier in {'NEW', 'EDIT', 'TRANSITION'}:
                tools.stop_session()
            getattr(bpy.ops.betopo, operator)('EXEC_DEFAULT')


class BETOPO_OT_dock(bpy.types.Operator):
    bl_idname = 'betopo.dock'
    bl_label = 'Betopo Bottom Buttons'
    bl_options = {'INTERNAL'}

    def invoke(self, context, _event):
        pointer = context.window.as_pointer()
        if not ENABLED or pointer in CONTROLLERS:
            return {'CANCELLED'}
        self.window = context.window
        self.pointer = pointer
        self._closed = False
        self._armed = None
        self._hover_context = None
        self.hover = self.hover_area = self.hover_region = None
        self._workspace = None
        self._pending_sidebar = set()
        self._timer = context.window_manager.event_timer_add(.2, window=self.window)
        CONTROLLERS[pointer] = self
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def finish(self):
        if self._closed:
            return
        self._closed = True
        if self._timer is not None:
            try:
                bpy.context.window_manager.event_timer_remove(self._timer)
            except (ReferenceError, RuntimeError):
                pass
            self._timer = None
        if CONTROLLERS.get(self.pointer) is self:
            CONTROLLERS.pop(self.pointer, None)

    def cancel(self, _context):
        self.finish()

    def locate(self, context, event):
        for area in self.window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            for region in area.regions:
                if region.type != 'WINDOW' or not contains((region.x, region.y, region.width, region.height),
                                                         event.mouse_x, event.mouse_y):
                    continue
                with context.temp_override(window=self.window, area=area, region=region):
                    layout = dock_hit(bpy.context, area, region, event)
                if layout:
                    x, y = event.mouse_x - region.x, event.mouse_y - region.y
                    button = next((b for b in layout['buttons'] if contains(b['rect'], x, y)), None)
                    return area, region, button['id'] if button else None
        return None

    def modal(self, context, event):
        if self._closed or not ENABLED:
            self.finish()
            return {'CANCELLED'}
        if event.type == 'TIMER':
            workspace = self.window.workspace
            key = workspace.as_pointer()
            if key != self._workspace:
                self._workspace = key
                self.hover = self.hover_area = self.hover_region = None
                self._armed = None
                self._pending_sidebar = {a.as_pointer() for a in self.window.screen.areas if a.type == 'VIEW_3D'} if active(workspace) else set()
            for area in self.window.screen.areas:
                if area.as_pointer() in self._pending_sidebar and focus_sidebar(area):
                    self._pending_sidebar.remove(area.as_pointer())
            return {'PASS_THROUGH'}
        shortcut = shortcut_context(context, event)
        if shortcut is not None:
            from . import tools
            session = tools.SESSION
            if (session is not None and not session._closed and session.window == self.window
                    and session.area == shortcut[0] and session.workspace == self.window.workspace):
                return {'PASS_THROUGH'}  # The tool session owns this key exactly once.
            if session is not None and (session._drawing or session._rotation is not None):
                return {'RUNNING_MODAL'}
            if event.value == 'PRESS' and not event.is_repeat:
                try:
                    dispatch(context, *shortcut)
                except (ValueError, RuntimeError) as error:
                    context.scene.betopo.status = str(error)
            return {'RUNNING_MODAL'}  # Consume releases/repeats so native B/V/E cannot fire.
        if not active(self.window.workspace) or event.type not in MOUSE_EVENTS:
            return {'PASS_THROUGH'}
        if native_modal_active(self.window):
            self._armed = None
            return {'PASS_THROUGH'}
        # A stroke/rotation that began on the model owns its release even above the dock.
        from . import tools
        session = tools.SESSION
        if session is not None and (session._rotation is not None or session._drawing):
            return {'PASS_THROUGH'}
        location = self.locate(context, event)
        old_area = self.hover_area
        if location:
            area, region, identifier = location
            self.hover, self.hover_area, self.hover_region = identifier, area.as_pointer(), region.as_pointer()
            self._hover_context = (area, region)
        else:
            self.hover = self.hover_area = self.hover_region = None
            self._hover_context = None
        for area in self.window.screen.areas:
            if area.as_pointer() in {old_area, self.hover_area}:
                area.tag_redraw()
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE' and self._armed is not None:
            armed = self._armed
            self._armed = None
            if location and self.hover is not None and armed == (self.hover_area, self.hover_region, self.hover):
                try:
                    dispatch(context, location[0], location[1], self.hover)
                except (ValueError, RuntimeError) as error:
                    context.scene.betopo.status = str(error)
            return {'RUNNING_MODAL'}
        if not location:
            return {'PASS_THROUGH'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self._armed = (self.hover_area, self.hover_region, self.hover)
        # Consume mouse actions on the entire dock, including its padding and disabled buttons.
        return {'RUNNING_MODAL'}


def ensure_controllers():
    if not ENABLED:
        return None
    wm = bpy.context.window_manager
    live = {window.as_pointer() for window in wm.windows}
    for pointer, controller in list(CONTROLLERS.items()):
        if pointer not in live:
            controller.finish()
    for window in wm.windows:
        if window.as_pointer() in CONTROLLERS:
            continue
        area = next((a for a in window.screen.areas if a.type == 'VIEW_3D'), None)
        if area is not None:
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            if region is not None:
                with bpy.context.temp_override(window=window, area=area, region=region):
                    bpy.ops.betopo.dock('INVOKE_DEFAULT')
    return .5


def start():
    global ENABLED, HANDLE
    if ENABLED or bpy.app.background:
        return
    ENABLED = True
    HANDLE = bpy.types.SpaceView3D.draw_handler_add(draw, (), 'WINDOW', 'POST_PIXEL')
    bpy.app.timers.register(ensure_controllers, first_interval=.1, persistent=True)


def reset():
    for controller in list(CONTROLLERS.values()):
        controller.finish()


def stop():
    global ENABLED, HANDLE
    ENABLED = False
    reset()
    if bpy.app.timers.is_registered(ensure_controllers):
        bpy.app.timers.unregister(ensure_controllers)
    if HANDLE is not None:
        bpy.types.SpaceView3D.draw_handler_remove(HANDLE, 'WINDOW')
        HANDLE = None


CLASSES = (BETOPO_OT_dock,)
