# Betopo

**Surface retopology tools for Blender, built around a dedicated workspace.**

Build surface-aligned quad patches, shape short strips with editable Bézier handles, place points and faces, fill holes, slice edge loops, and stamp reusable topology templates. Large buttons at the bottom of the viewport keep tools within reach; the right sidebar shows settings for the active tool.

**Status:** early release · **Version:** 0.1.16 · **Tested:** Blender 5.1.2 on Windows

**New in 0.1.16:** Area quad grids, two-endpoint Flow with draggable tangent handles, persistent bottom buttons, and workspace-scoped shortcuts. See the [changelog](CHANGELOG.md).

## Install with your AI assistant

Give an AI assistant with access to your computer this repository URL and the following request:

> Install Betopo from https://github.com/bariacg/Betopo into my Blender. Read AI_INSTALL.md first, identify my Blender version and installation, download the published release, verify its checksum, and use the supplied installer. Preserve my other add-ons, workspaces, startup file, preferences, and custom keymaps. Verify the installation and tell me how to open Betopo. Ask me only if the Blender installation or profile is ambiguous.

**[AI installation guide](AI_INSTALL.md)** contains the exact commands, supported version, validation steps, update process, and uninstall instructions. **[INSTALLATION.json](INSTALLATION.json)** provides machine-readable installation metadata.

AI assistants without local computer or terminal access can explain the steps, but cannot install software on your computer themselves.

## Install manually

1. Download **Betopo-0.1.16.zip** and **SHA256SUMS.txt** from [Releases](https://github.com/bariacg/Betopo/releases/latest). Extract the ZIP into a folder you can keep for updates and uninstalling. This is an installer bundle; do not select it in Blender's Install from Disk dialog.
2. Close Blender after saving your work. Run Blender 5.1 with the extracted installer, using your actual paths:

   ```text
   "<path-to-blender>" --background --factory-startup --python-exit-code 1 --python "<extracted-folder>/install_betopo.py"
   ```

   In PowerShell, put `&` before the quoted executable path. See [AI_INSTALL.md](AI_INSTALL.md) for complete examples and verification.
3. Open Blender normally. Select the **Betopo** workspace. If needed, use Blender's operator search for **Open Betopo Workspace**.

The installer writes only the `betopo` add-on and its own startup loader in Blender's user scripts directory. It does not save preferences, replace your startup file, or register global keyboard shortcuts. A previous managed Betopo installation is backed up before updating. An existing installation without Betopo's ownership marker is left untouched for review.

## Start retopologizing

1. Select the high-resolution mesh you want to retopologize.
2. Open the **Betopo** workspace and click **New Retopo**. Betopo creates a separate target mesh and enters Edit Mode.
3. Choose a tool from the bottom buttons. Adjust its settings in the right **Betopo** sidebar; press `N` if the sidebar is hidden.
4. Use **Exit Tool** or `Esc` to leave the current tool. Your target remains a normal Blender mesh.

For an existing target, set **Source** and **Target** in the sidebar, then choose **Edit Target**.

## Tools

- **Add** — click to build triangles or quads, reusing nearby existing vertices.
- **Points / Faces** — left-click to place surface points; right-click to create the previewed face. Continue from an existing boundary.
- **Draw** — draw a freehand quad strip, adjust its preview, then press `Enter` to apply.
- **Dot** — click a sequence of control points to form a smooth quad strip. Adjust Segments, Smooth, and Strip Width before applying with `Enter`.
- **Area** — draw four connected boundary strokes to preview a surface-projected quad grid. Adjust Quad Size or Columns/Rows live; `Ctrl`-drag a free corner to reshape the preview. An existing open boundary can provide the first side.
- **Flow** — define two endpoints for a short Bézier quad strip. Drag endpoints, orange tangent handles, or the white centerline to shape and move the preview. Adjust Segments and Strip Width before applying; attach either end to an open border or reshape the last strip with Redraw Last.
- **Contours** — draw a cutting stroke to generate a surface contour loop. Loop Vertices starts at **8**; the preview updates as settings change.
- **Fill / Bridge** — hover a boundary hole to preview a fill, or bridge selected boundary chains.
- **GFill** — apply Blender's grid-fill operation and project the resulting vertices onto the source surface.
- **Edge Slice** — preview a cut through a connected quad strip; position the cursor to adjust the cut before committing.
- **Templates** — choose from eight original topology patches, **A–H**, using thumbnail previews. `Ctrl` + mouse wheel changes size; hold `Ctrl` + right mouse button and drag to rotate.
- **Relax / Relax Selected** — distribute vertices more evenly while projecting them back onto the source. Boundary and selection options are available.
- **Tweak** — move surface vertices with a brush. Strength starts at **1.0**.
- **Magnet** — project selected vertices back onto the source mesh.
- **Symmetry** — configure the target's Mirror modifier from the sidebar.
- **Pin / Unpin, Weld, Transition Fill, Check Topology** — supporting mesh tools. **Loop Cut** and **Knife** invoke Blender's native tools.

The bottom buttons remain visible while orbiting, panning, or zooming. Points / Faces, Dot, Edge Slice, Templates, and Tweak have restrained color accents; the active tool uses a stronger color and a thick white underline.

While editing the Betopo target in a Betopo viewport, **`B` → Tweak**, **`V` → Points / Faces**, and **`E` → Edge Slice**. These shortcuts are handled locally by Betopo; they do not install global keymap entries. Outside that context, existing bindings remain available. Sidebar text fields and native modal tools keep their own input.

Navigation and modified selection gestures pass through to Blender's existing keymap. Betopo's mouse gestures apply while its own tools are active. Area additionally uses `Ctrl`-drag on its preview corners.

### Shape a Flow strip

1. Select **Flow** and **New Strip**. Click the start and end points, or drag from start to end. Intermediate mouse movements do not add control points.
2. Drag a blue endpoint to reposition it; its tangent handle moves with it. Drag either **orange handle** to adjust the curve's direction and bend. Drag the **white centerline** to move a free strip as a whole.
3. Adjust **Segments**, **Strip Width**, and **Surface Offset** in the sidebar. The curve and quad preview update before any target geometry is changed.
4. Press **`Enter`** to apply. **`Esc` during a drag** restores the previous preview; `Esc` when idle discards the preview. A second `Esc` exits the tool.

**Attach to Borders** reuses actual vertices at an open end edge. Attached endpoints stay fixed; their tangent handles remain editable. In New Strip, disable this option to detach a preview before moving it. Whole-curve translation is available when both endpoints are free.

**Redraw Last** restores the endpoints and handles of the last Flow strip in the current session. Applying reshapes that strip without changing its segment count or attachment vertices. Edited, externally connected, or pinned strips are rejected; use Tweak for those cases. This temporary history ends when the tool session ends or native Undo leaves the session.

### Fill an Area patch

Draw four consecutive connected sides, closing the fourth at the first corner. Use **Quad Size** for automatic density or **Columns/Rows** for explicit counts (`0` means automatic). Click an open border first, or select one open boundary chain before activating Area, to reuse that boundary. Attached boundary counts and vertices remain fixed.

`Ctrl`-drag a free corner to adjust the preview; `Backspace` removes the last side. Press `Enter` to create the grid, then begin another patch. Area rejects incompatible opposite boundary counts, crossed guides, and folded grids; it does not automatically repair every boundary configuration.

## Compatibility and limitations

This release targets **Blender 5.1.x**; **5.1.2 on Windows** is the tested configuration. The installer deliberately rejects other Blender minor versions. macOS and Linux have not been verified. Blender must already be installed; no administrator privileges or Python package installation are normally needed.

Betopo works with one source mesh at a time. Non-manifold source geometry, ambiguous hole boundaries, and complex contour intersections may require manual cleanup. Templates project a patch onto the surface; they do not perform automatic anatomical landmark fitting. Inspect the resulting topology before production use, and save your work regularly.

The workspace asset is generated from Blender's factory Modeling workspace in a background process. It contains layout data only. Betopo runs offline and has no account, telemetry, or external Python dependencies.

## Help improve Betopo

**[Report a bug](https://github.com/bariacg/Betopo/issues/new?template=bug_report.yml)** · **[Suggest an improvement](https://github.com/bariacg/Betopo/issues/new?template=feature_request.yml)** · **[Contribution guide](CONTRIBUTING.md)**

Contributions are welcome through forks and pull requests. Opening an issue or pull request does not grant write access. The project maintainer decides which changes are accepted and controls releases; there is no automatic merge or deployment workflow.

Before posting logs or screenshots, remove personal file paths, names, email addresses, credentials, and confidential model data. Do not upload a client model without permission.

## License and attribution

Betopo's code, documentation, and workspace layout are licensed under **GPL-3.0-or-later**; see [LICENSE](LICENSE) and [NOTICE](NOTICE). The original A–H template geometry and preview icons are separately available under the **MIT license** in [LICENSE-ASSETS](LICENSE-ASSETS), allowing reuse with its copyright and permission notice.

Using Betopo does not by itself place your independently created meshes under the add-on's GPL license. If you redistribute substantial portions of the bundled template assets, retain their MIT notice. Third-party models you work on remain subject to their own terms.

Betopo is an independent project. It is not affiliated with or endorsed by Blender, RetopoFlow, 3DCoat, or TopoPen. Those names identify their respective products and owners. Workflow references and the scope of bundled material are documented in [NOTICE](NOTICE).

## For developers

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md). The repository contains the add-on source and the scripts needed to rebuild its workspace and release bundle. No personal Blender profile, private project models, or unrelated add-on is required.
