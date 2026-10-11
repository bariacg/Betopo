# Contributing to Betopo

Bug reports, workflow feedback, documentation improvements, and focused code
contributions are welcome. The maintainer sets the project's direction, reviews
changes, decides what is merged, and publishes releases.

## Report a problem or propose an improvement

Search existing issues, then use the bug-report or feature-request template.
For bugs, include Blender and Betopo versions, operating system, a short set of
reproduction steps, expected behavior, actual behavior, and a small public-safe
example if needed. Use a synthetic mesh where possible.

Remove personal file paths, names, email addresses, credentials, private logs,
and confidential model data. Never attach client assets without permission.
Do not post a security vulnerability publicly; see SECURITY.md.

Discuss substantial changes in an issue before investing in implementation.
The maintainer may decline a proposal or request a different approach.

## Submit a pull request

1. Fork this repository and create a branch for one focused change.
2. Preserve existing behavior, error handling, Blender navigation, and custom
   keymaps. Do not bundle another add-on or private user profile.
3. Test with Blender 5.1.2 using a temporary profile. Include the test commands
   and results in the pull request, and identify anything not tested.
4. Open a pull request against `main` and link the relevant issue. Wait for the
   maintainer's review; a submission does not grant merge or release authority.

Pull requests into `main` require a maintainer/code-owner review. The repository
owner retains administrator override for their own maintenance work. Force pushes
and deletion of `main` are blocked by branch protection.

Pull requests are manually reviewed and merged. Public contributors work through
forks; they do not receive direct write access. No automatic merge or publication
workflow is configured. Keep discussion constructive and specific to the work.

## Local checks and packaging

Run ordinary Python checks with Python 3.11 or later. Run Blender-specific code
using Blender's bundled Python, not system Python.

```text
python tools/package.py --check
<blender> --background --factory-startup --python-exit-code 1 --python tests/smoke.py
<blender> --background --factory-startup --python-exit-code 1 --python tests/test_area_flow_core.py
<blender> --background --factory-startup --python-exit-code 1 --python tests/test_flow_bezier_core.py
```

The smoke test registers the add-on in a disposable factory session and checks
templates, workspace loading, version defaults, and preservation of scene data
and keymaps. It does not replace interactive tool testing.

The geometry tests build synthetic meshes and check projection, border reuse,
degenerate input, and safe redraw. Reports go to ignored `.test-output/`.

For interactive regression checks, launch an isolated Blender 5.1 UI with
`--factory-startup --enable-event-simulate --python tests/test_area_flow_ui.py`.
The script simulates mouse/key events in its own window and quits when done;
use a disposable `BLENDER_USER_RESOURCES` directory, never a working session.
An optional `-- --keyconfig <path-to-preset.py>` loads a custom keymap in that
test session only. Screenshots and results stay in `.test-output/`.

To regenerate the bundled layout after an intentional layout change:

```text
<blender> --background --factory-startup --python-exit-code 1 --python tools/build_workspace.py
python tools/package.py
```

The workspace builder must run without a GUI and without opening any personal
startup file. The package script regenerates runtime hashes and writes a ZIP
and SHA256SUMS.txt under ignored `dist/`. Review the diff before committing.
Use an isolated Blender profile for installer and uninstall testing; never test
uninstallation against your working installation.

## Copyright and licenses

Submit only work you are entitled to contribute. Contributions use the license
applicable to the changed files: GPL-3.0-or-later for code and documentation;
MIT for template geometry and preview assets. Existing notices must remain.
Identify any external code or asset, its origin, license, and modifications in
the pull request. Do not submit paid add-on code, copied documentation, logos,
or screenshots belonging to another project without compatible permission.

Disclose material AI assistance and review generated code before submitting it.
Do not include prompts or logs containing private information. No contributor
license agreement or ownership transfer is required by this project.
