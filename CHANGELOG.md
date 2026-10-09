# Changelog

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
