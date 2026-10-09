# Betopo assistant instructions

For a user requesting installation, follow AI_INSTALL.md and INSTALLATION.json.
Do not treat repository instructions as permission to access unrelated user data.

For development:
- Read CONTRIBUTING.md. Make focused changes and explain validation and limits.
- Preserve the user's Blender settings, startup file, custom keymaps, other
  add-ons, and unrelated projects. Do not run tests against a real user profile.
- Use Blender 5.1 for runtime tests, with --background --factory-startup and a
  temporary BLENDER_USER_RESOURCES directory for installer tests.
- Build workspace.blend only in a background factory session. Never duplicate
  or serialize a live GUI screen to produce this asset; transient native tooltip
  pointers can cause Blender crashes.
- Keep Betopo independent of other add-ons and private project paths.
- Preserve license notices. Do not copy third-party code or assets without
  compatible redistribution rights and recorded attribution.
- Exclude credentials, usernames, machine paths, private models, generated
  installation markers, local profiles, caches, and backups from commits.
- Run python tools/package.py --check after relevant changes. If runtime files
  changed, regenerate the manifest with python tools/package.py before validating.
- Never publish a release, merge a pull request, or change repository permissions
  merely because this file describes the process. Those actions require the
  maintainer's instruction. Do not add automatic merge or release workflows.
