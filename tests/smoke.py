# SPDX-License-Identifier: GPL-3.0-or-later
"""Public smoke checks; run only in a disposable background factory session."""
import json
import sys
from pathlib import Path
import bpy

if not bpy.app.background or bpy.app.version[:2] != (5, 1):
    raise RuntimeError('Use Blender 5.1 --background --factory-startup')
bpy.context.preferences.use_preferences_save = False
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import betopo


def keymaps():
    return [(config.name, [(km.name, km.space_type, km.region_type,
                           [(item.idname, item.type, item.value, item.ctrl, item.shift,
                             item.alt, item.oskey, item.key_modifier)
                            for item in km.keymap_items]) for km in config.keymaps])
            for config in bpy.context.window_manager.keyconfigs]


before_keys = keymaps()
before_data = {key: {block.as_pointer() for block in getattr(bpy.data, key)}
               for key in ('scenes', 'objects', 'meshes', 'collections', 'materials', 'cameras', 'texts', 'images')}
before_workspaces = {w.as_pointer(): w.name for w in bpy.data.workspaces}
betopo.register()
try:
    assert betopo.bl_info['version'] == (0, 1, 16)
    assert bpy.context.scene.betopo.contour_vertices == 8
    assert bpy.context.scene.betopo.tweak_strength == 1.0
    assert bpy.context.scene.betopo.flow_segments == 12
    assert {'AREA','FLOW'} <= {name for name,label in betopo.tools.TOOL_NAMES}
    assert set(betopo.core.TEMPLATES) == set('ABCDEFGH')
    for name, patch in betopo.core.TEMPLATES.items():
        assert patch['faces'], name
        assert (ROOT / 'betopo' / 'icons' / (name + '.png')).is_file()
    workspace = betopo.operators.duplicate_workspace(bpy.context)
    assert workspace.get('betopo_workspace')
    assert any(area.type == 'VIEW_3D' for screen in workspace.screens for area in screen.areas)
    assert all(w.name == before_workspaces[w.as_pointer()] for w in bpy.data.workspaces
               if w.as_pointer() in before_workspaces)
    assert all(pointers == {block.as_pointer() for block in getattr(bpy.data, key)}
               for key, pointers in before_data.items()), 'Workspace brought in scene or asset data'
    assert keymaps() == before_keys, 'Registration changed keymaps'
finally:
    betopo.unregister()
assert not hasattr(bpy.types.Scene, 'betopo')
assert keymaps() == before_keys, 'Unregistration changed keymaps'
print('BETOPO_SMOKE_OK: version, defaults, A-H, workspace, scene preservation, keymaps and cleanup', flush=True)
