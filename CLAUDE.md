# Working in this repository

## Always commit completed changes

When a change is complete, commit it (with a clear, descriptive message) and
push it to the working branch straight away. Don't leave finished work
uncommitted in the working tree.

## Only release when asked

Don't create a release unless the user explicitly asks for one. Until
then, finished changes are committed and pushed to the working branch
only: don't bump `"version"` in
`custom_components/log_doctor/manifest.json` and don't merge into `main`
(`.github/workflows/release.yml` creates a `v<version>` release, which HACS
offers as an update, whenever `main` carries a version that hasn't been
released yet).

When the user asks for a release: bump `"version"` once for everything
since the last release (semantic versioning: patch for fixes only, minor
if there are features), commit, merge the working branch into `main` and
push, then confirm the release exists.
