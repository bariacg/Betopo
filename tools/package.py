# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a source-complete installer bundle from explicit public file lists."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MODULES = ('__init__', 'contours', 'core', 'dock', 'dock_draw', 'holes',
           'operators', 'point_faces', 'slice', 'tools', 'transition')
RUNTIME = ([f'{name}.py' for name in MODULES]
           + [f'icons/{name}.png' for name in 'ABCDEFGH']
           + ['templates.json', 'workspace.blend', 'LICENSE', 'LICENSE-ASSETS', 'NOTICE'])
ROOT_FILES = ['README.md', 'AI_INSTALL.md', 'INSTALLATION.json', 'AGENTS.md',
              'CONTRIBUTING.md', 'SECURITY.md', 'CHANGELOG.md', 'LICENSE',
              'LICENSE-ASSETS', 'NOTICE', 'install_betopo.py', 'verify_install.py',
              'package-manifest.json', 'tools/build_workspace.py', 'tools/package.py',
              'tests/smoke.py', '.gitignore', '.gitattributes', '.github/CODEOWNERS', '.github/pull_request_template.md',
              '.github/ISSUE_TEMPLATE/bug_report.yml',
              '.github/ISSUE_TEMPLATE/feature_request.yml',
              '.github/ISSUE_TEMPLATE/config.yml']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Verify without rewriting or packaging')
    options = parser.parse_args()
    info = ast.parse((ROOT / 'betopo' / '__init__.py').read_text(encoding='utf-8'))
    metadata = ast.literal_eval(next(node.value for node in info.body
                                    if isinstance(node, ast.Assign) and any(
                                        isinstance(t, ast.Name) and t.id == 'bl_info'
                                        for t in node.targets)))
    version = '.'.join(map(str, metadata['version']))
    install = json.loads((ROOT / 'INSTALLATION.json').read_text(encoding='utf-8'))
    if install['version'] != version:
        raise RuntimeError('Installation contract version mismatch')
    if not options.check:
        for name in ('LICENSE', 'LICENSE-ASSETS', 'NOTICE'):
            (ROOT / 'betopo' / name).write_bytes((ROOT / name).read_bytes())
    expected = {'version': version, 'blender': '5.1.2',
                'files': {relative: digest(ROOT / 'betopo' / relative) for relative in sorted(RUNTIME)}}
    manifest_path = ROOT / 'package-manifest.json'
    if options.check:
        if json.loads(manifest_path.read_text(encoding='utf-8')) != expected:
            raise RuntimeError('Runtime manifest is stale; rebuild before releasing')
    else:
        manifest_path.write_text(json.dumps(expected, indent=2) + '\n', encoding='utf-8', newline='\n')
    # Reject unexpected runtime files instead of silently shipping them.
    actual = {path.relative_to(ROOT / 'betopo').as_posix()
              for path in (ROOT / 'betopo').rglob('*')
              if path.is_file() and '__pycache__' not in path.parts}
    if actual != set(RUNTIME):
        raise RuntimeError('Unexpected runtime files: ' + repr(actual ^ set(RUNTIME)))
    public_files = sorted(ROOT_FILES + ['betopo/' + relative for relative in RUNTIME])
    for relative in public_files:
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError('Missing or linked public file: ' + relative)
        if path.suffix == '.py':
            compile(path.read_text(encoding='utf-8'), relative, 'exec')
    if options.check:
        print('BETOPO_PACKAGE_OK:', len(public_files), 'public files; runtime hashes verified')
        return
    destination = ROOT / 'dist'
    destination.mkdir(exist_ok=True)
    archive = destination / f'Betopo-{version}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for relative in public_files:
            # Fixed timestamps and no host paths/ownership attributes.
            entry = zipfile.ZipInfo(relative, (2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            bundle.writestr(entry, (ROOT / relative).read_bytes())
    (destination / 'SHA256SUMS.txt').write_text(digest(archive) + '  ' + archive.name + '\n', encoding='utf-8', newline='\n')
    print('BETOPO_PACKAGE_BUILT:', archive.name, len(public_files), 'files')


if __name__ == '__main__':
    main()
