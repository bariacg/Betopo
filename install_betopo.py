# SPDX-License-Identifier: GPL-3.0-or-later
"""Copy only Betopo-owned files. Run using Blender's bundled Python."""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

import bpy

bpy.context.preferences.use_preferences_save = False
if bpy.app.version[:2]!=(5,1):
    raise RuntimeError('This Betopo package is tested with Blender 5.1; use the matching Blender version')

ROOT = Path(__file__).resolve().parent
OWNED_BOOTSTRAP = 'betopo_autoload.py'
BOOTSTRAP = '''# Betopo-owned startup loader; does not replace keymaps or save preferences.
import addon_utils
import bpy

def _enable():
    addon_utils.enable("betopo", default_set=False, persistent=True)
    return None

def register():
    if not bpy.app.background and not bpy.app.timers.is_registered(_enable):
        bpy.app.timers.register(_enable, first_interval=.5, persistent=True)

def unregister():
    if bpy.app.timers.is_registered(_enable):
        bpy.app.timers.unregister(_enable)
    addon_utils.disable("betopo", default_set=False)
'''

args = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
parser = argparse.ArgumentParser()
parser.add_argument('--uninstall',action='store_true')
options = parser.parse_args(args)
scripts = Path(bpy.utils.user_resource('SCRIPTS',create=True)).resolve()
addon = scripts/'addons'/'betopo'
bootstrap = scripts/'startup'/OWNED_BOOTSTRAP
if addon.resolve()!=scripts/'addons'/'betopo' or bootstrap.resolve()!=scripts/'startup'/OWNED_BOOTSTRAP:
    raise RuntimeError('Unexpected linked installation paths; no files changed')

if options.uninstall:
    if bootstrap.exists() and bootstrap.read_text(encoding='utf-8')!=BOOTSTRAP:
        raise RuntimeError('Startup loader changed; no files removed')
    # Verify resolved ownership boundaries before removing any directory.
    if addon.exists():
        if addon.is_symlink() or addon.resolve()!=scripts/'addons'/'betopo':
            raise RuntimeError('Unexpected Betopo installation path')
        if not (addon/'betopo-installation.json').exists():
            raise RuntimeError('Existing directory is not a managed Betopo installation')
        shutil.rmtree(addon)
    if bootstrap.exists():
        if bootstrap.read_text(encoding='utf-8')!=BOOTSTRAP:
            raise RuntimeError('Startup loader changed; kept it for manual review')
        bootstrap.unlink()
    print('BETOPO_UNINSTALL_OK: other add-ons, settings and project meshes preserved.')
else:
    manifest = json.loads((ROOT/'package-manifest.json').read_text(encoding='utf-8'))
    if manifest['version'] != '0.1.16' or not manifest['files']:
        raise RuntimeError('Unexpected or empty package manifest')
    for relative,expected in manifest['files'].items():
        path = ROOT/'betopo'/relative
        if Path(relative).is_absolute() or not path.resolve().is_relative_to((ROOT/'betopo').resolve()):
            raise RuntimeError('Unsafe package path')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise RuntimeError('Package verification failed: '+relative)
    if addon.exists() and not (addon/'betopo-installation.json').exists():
        raise RuntimeError('An unmanaged betopo add-on already exists; no files changed')
    if bootstrap.exists() and bootstrap.read_text(encoding='utf-8')!=BOOTSTRAP:
        raise RuntimeError('A different Betopo startup loader exists; no files changed')
    # Preserve a previous managed version; never touch other add-ons or presets.
    if addon.exists():
        backup = ROOT/'Backups'/bpy.app.version_string.replace('.','_')
        backup.mkdir(parents=True,exist_ok=True)
        index = 1
        while (backup/('betopo_'+str(index))).exists():
            index += 1
        shutil.copytree(addon,backup/('betopo_'+str(index)))
    addon.mkdir(parents=True,exist_ok=True)
    for relative in manifest['files']:
        destination = addon/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/'betopo'/relative,destination)
    (addon/'betopo-installation.json').write_text(json.dumps({'version':manifest['version'],
                                                           'files':manifest['files']},indent=2),encoding='utf-8')
    bootstrap.parent.mkdir(parents=True,exist_ok=True)
    bootstrap.write_text(BOOTSTRAP,encoding='utf-8')
    print('BETOPO_INSTALL_OK:',addon)
    print('Open Blender: a separate Betopo workspace is added. Preferences and Startup are not overwritten.')
