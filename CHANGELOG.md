# Changelog

## 0.1.16

### Added

- **Area:** surface-projected quad grids from four connected guide strokes,
  with live density/subdivision controls and draggable free corners. Reuse an
  existing open boundary while preserving its vertices and subdivision count.
- **Flow:** short cubic Bézier strips controlled by two endpoints and two
  visible tangent handles. Click two endpoints or drag start to end; edit
  endpoints, tangents, or the free curve before applying.
- Flow border attachment and **Redraw Last** for reshaping the last strip in
  the current session without changing its topology or fixed attachments.
- Workspace-scoped **B → Tweak**, **V → Points / Faces**, and **E → Edge Slice**
  while editing the Betopo target. No global keymap entries are installed.

### Improved

- Bottom buttons remain visible during viewport navigation and native modal
  tools, with input left to those tools while they are running.
- Muted color accents for frequently used tools, stronger active colors, and
  a thicker white active-tool marker.
- Live Flow updates for Segments, Strip Width, and Surface Offset. Preview
  changes leave target geometry untouched until Enter.
- Geometry checks reject folded grids, collapsed ribbons, and attachment
  growth over an existing face. Redraw checks preserve pinned vertices and
  reject strips changed or connected elsewhere since creation.
- Portable geometry and interactive regression tests, updated AI installation
  metadata, and a source-complete installer bundle with SHA-256 checksums.

Validated on Blender 5.1.2 on Windows. Area, Flow, native Undo, border reuse,
parameter previews, and existing Draw behavior were tested in isolated Blender
sessions. macOS and Linux remain unverified. This release includes the changes
developed since the previous public version, 0.1.10.

## 0.1.10

First public distribution of Betopo.

- Dedicated workspace with large bottom tool buttons and contextual sidebar.
- Add, Points / Faces, Draw, Dot, Contours, hover hole filling, GFill, Edge Slice,
  templates A-H, Relax, Tweak, Magnet, symmetry, and mesh cleanup helpers.
- Live parameter previews for Draw, Dot, and Contours.
- Workspace layout rebuilt from Blender's factory Modeling workspace, without
  personal startup data or dependencies on another add-on.
- Source, licenses, reproducible workspace/package scripts, and runtime hashes.
- Managed installer, verification, update backup, and ownership-aware uninstall.
- AI installation guide and machine-readable installation metadata.
- Issue forms and a contribution process with maintainer-controlled merging
  and releases.

This release includes the workspace-loading approach introduced during private
development to avoid copying transient native tooltip state. Only Blender
5.1.2 on Windows has been tested.
