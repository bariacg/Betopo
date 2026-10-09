# SPDX-License-Identifier: GPL-3.0-or-later
"""Bake a layout from a factory background session; never serialize live UI."""
from pathlib import Path
import bpy

if not bpy.app.background or bpy.app.version[:2] != (5, 1):
    raise RuntimeError('Use Blender 5.1 --background --factory-startup')
bpy.context.preferences.use_preferences_save = False
bpy.ops.wm.read_factory_settings(use_empty=False)
workspace = bpy.data.workspaces['Modeling']
workspace.name = 'Betopo'
workspace['betopo_workspace'] = True
workspace.object_mode = 'OBJECT'
for screen in workspace.screens:
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            area.spaces.active.show_region_ui = True
            area.spaces.active.show_region_tool_header = False
destination = Path(__file__).resolve().parents[1] / 'betopo' / 'workspace.blend'
bpy.data.libraries.write(str(destination), {workspace}, compress=False)
print('BETOPO_WORKSPACE_BUILT', flush=True)
