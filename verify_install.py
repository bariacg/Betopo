# SPDX-License-Identifier: GPL-3.0-or-later
"""Read and register the installed copy in a disposable Blender session."""
import hashlib
import json
import sys
from pathlib import Path

import bpy

if not bpy.app.background or bpy.app.version[:2] != (5, 1):
    raise RuntimeError('Use Blender 5.1 --background --factory-startup')
bpy.context.preferences.use_preferences_save = False
root = Path(__file__).resolve().parent
scripts = Path(bpy.utils.user_resource('SCRIPTS')).resolve()
addon = scripts / 'addons' / 'betopo'
manifest = json.loads((root / 'package-manifest.json').read_text(encoding='utf-8'))
marker = json.loads((addon / 'betopo-installation.json').read_text(encoding='utf-8'))
if marker != {'version': manifest['version'], 'files': manifest['files']}:
    raise RuntimeError('Installed ownership marker does not match this bundle')
for relative, expected in manifest['files'].items():
    path = (addon / relative).resolve()
    if not path.is_relative_to(addon.resolve()):
        raise RuntimeError('Unsafe manifest path')
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError('Installed hash mismatch: ' + relative)
# Extract the loader constant without executing the installer.
import ast
tree = ast.parse((root / 'install_betopo.py').read_text(encoding='utf-8'))
bootstrap = next(ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and any(
                     isinstance(target, ast.Name) and target.id == 'BOOTSTRAP'
                     for target in node.targets))
if (scripts / 'startup' / 'betopo_autoload.py').read_text(encoding='utf-8') != bootstrap:
    raise RuntimeError('Installed loader differs from the supplied loader')
sys.path.insert(0, str(addon.parent))
import betopo
if Path(betopo.__file__).resolve().parent != addon.resolve():
    raise RuntimeError('Imported a different Betopo installation')
if '.'.join(map(str, betopo.bl_info['version'])) != manifest['version']:
    raise RuntimeError('Installed version mismatch')
betopo.register()
try:
    assert hasattr(bpy.types.Scene, 'betopo'), 'Scene settings not registered'
    assert set(betopo.core.TEMPLATES) == set('ABCDEFGH'), 'Missing templates'
    workspace = betopo.operators.duplicate_workspace(bpy.context)
    assert workspace.get('betopo_workspace'), 'Workspace could not be loaded'
finally:
    betopo.unregister()
print('BETOPO_VERIFY_OK: version, hashes, loader, registration, templates and workspace', flush=True)
