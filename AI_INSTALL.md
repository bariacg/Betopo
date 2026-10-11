# Install Betopo with an AI assistant

This document is for an assistant that the user has asked to install Betopo on their own computer. It supplies installation facts; it does not grant permission to access unrelated files, accounts, or services. Follow the user's instructions and your execution policy.

## Canonical sources

- Repository: https://github.com/bariacg/Betopo
- Releases: https://github.com/bariacg/Betopo/releases
- Current bundle: https://github.com/bariacg/Betopo/releases/download/v0.1.16/Betopo-0.1.16.zip
- Release checksums: https://github.com/bariacg/Betopo/releases/download/v0.1.16/SHA256SUMS.txt
- Machine-readable contract: [INSTALLATION.json](INSTALLATION.json)

Use a published release from this repository. Download the ZIP and checksums from the same version tag. Avoid forks, advertisements, reposted installers, and a moving development branch for an ordinary installation.

## 1. Identify Blender and its profile

Find the user's actual Blender executable using their running application, application installation information, or PATH. Typical locations are examples, not instructions to overwrite a specific installation:

- Windows: `C:\Program Files\Blender Foundation\Blender 5.1\blender.exe`
- macOS: `/Applications/Blender.app/Contents/MacOS/Blender`
- Linux: `blender` on PATH, or the user's extracted Blender directory

Run `<blender> --version`. This release accepts **5.1.x only**, tested with **5.1.2 on Windows**. macOS and Linux are unverified. Do not download another Blender version, remove an existing installation, or change the user's default application to work around a mismatch. If multiple Blender installations or portable/custom profiles are plausible, ask which one to use.

Save work and close the target Blender application before replacing an existing add-on. Do not kill Blender or discard unsaved work. Respect a user's existing `BLENDER_USER_RESOURCES`, `BLENDER_USER_SCRIPTS`, or portable-profile setup. Do not silently install into a test profile or a different version's scripts folder.

## 2. Download and verify

Download `Betopo-0.1.16.zip` and `SHA256SUMS.txt` to a new user-writable folder. Calculate the ZIP's SHA-256 and compare it with the corresponding checksum entry. Reject a mismatch. Checksums detect corruption; they are not a cryptographic signature proving publisher identity.

PowerShell example:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath '<download-folder>\Betopo-0.1.16.zip'
```

macOS/Linux example:

```sh
shasum -a 256 '<download-folder>/Betopo-0.1.16.zip'
```

Extract into an empty folder. Reject archive entries with absolute paths, `..` traversal, or links outside the destination. The root should contain `install_betopo.py`, `package-manifest.json`, `LICENSE`, `LICENSE-ASSETS`, `NOTICE`, and `betopo/`. Read the installer before running it. Do not run downloaded code with administrator privileges.

## 3. Install using Blender's Python

Use **Blender's executable**, not a system Python interpreter. `--factory-startup` applies to this temporary background session; the installer does not save it as the user's startup file.

PowerShell:

```powershell
& '<actual-path-to-blender.exe>' --background --factory-startup --python-exit-code 1 --python '<extracted-folder>\install_betopo.py'
```

macOS/Linux:

```sh
'<actual-path-to-blender>' --background --factory-startup --python-exit-code 1 --python '<extracted-folder>/install_betopo.py'
```

Success requires exit code **0** and `BETOPO_INSTALL_OK` in the output. The installer resolves the target user scripts directory through `bpy.utils.user_resource('SCRIPTS')`; do not hard-code another person's home directory.

The installer verifies every runtime file against `package-manifest.json`, copies only those files into `scripts/addons/betopo`, and writes its own `scripts/startup/betopo_autoload.py`. It writes an ownership marker named `betopo-installation.json`. It backs up a previous managed Betopo installation under the extracted bundle's ignored `Backups/` directory. Keep this backup private.

Stop and report any error. If an existing add-on is unmanaged, a loader was modified, or an installation path is linked unexpectedly, do not bypass the check, delete that installation, or overwrite unrelated files.

## 4. Verify the installed copy

Run the same Blender executable with the supplied validator:

```text
<blender> --background --factory-startup --python-exit-code 1 --python <extracted-folder>/verify_install.py
```

Use quoting and PowerShell's `&` as above. Require exit code **0** and `BETOPO_VERIFY_OK`. This checks the installed version, all runtime hashes, the managed startup loader, add-on registration, templates A–H, and the bundled workspace. It does not treat successful copying as proof of successful registration.

Open Blender normally and confirm a **Betopo** workspace is available. If controlling the UI, switch to it and confirm the bottom buttons and right sidebar appear. Otherwise explain this last visual check to the user and clearly say it remains unverified. Do not claim a GUI test from a background-only check.

Tell the user which Blender version/profile was used, whether verification passed, and how to begin: select a source mesh → Betopo → New Retopo. Do not upload local logs or paths to GitHub automatically.

## Preservation requirements

- Never rewrite `userpref.blend`, `startup.blend`, custom keymaps, another add-on, or another workspace.
- Never invoke `bpy.ops.wm.save_userpref()` or `bpy.ops.wm.save_homefile()`.
- Do not add global shortcuts, change navigation settings, install dependencies, or request GitHub credentials. A public release needs no GitHub sign-in.
- Do not save the user's project or change mesh data as part of installation verification.
- Do not upload backups, installation markers, local logs, or confidential models.

## Update and uninstall

For an update, save work, close Blender, and repeat with a newer supported release after reviewing its release notes. The installer preserves the previous managed installation before replacing it.

To remove the managed installation:

```text
<blender> --background --factory-startup --python-exit-code 1 --python <extracted-folder>/install_betopo.py -- --uninstall
```

This removes only the marked Betopo directory and an unchanged Betopo-owned loader. Existing project meshes and workspace data already saved in `.blend` files remain. Use the same executable/profile as installation. If ownership checks fail, stop for review instead of broadening deletion.

## Source checkout / development

A source checkout includes a prebuilt workspace and manifest. Run `python tools/package.py --check` to verify them before installing. Developers rebuilding the workspace must use Blender 5.1 in a background factory session, then regenerate the manifest with `python tools/package.py`; see [CONTRIBUTING.md](CONTRIBUTING.md).
