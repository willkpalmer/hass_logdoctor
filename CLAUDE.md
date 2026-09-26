# Working in this repository

## Always commit completed changes

When a change is complete, commit it (with a clear, descriptive message) and
push it to the working branch straight away. Don't leave finished work
uncommitted in the working tree.

## Always merge to main and release

Every change that affects the integration must bump `"version"` in
`custom_components/log_doctor/manifest.json` (semantic versioning: patch
for fixes, minor for features). Once committed, merge it into `main` and
push, so `.github/workflows/release.yml` creates the `v<version>` release
that HACS offers as an update. Then confirm the release exists. Don't
leave finished work sitting on a branch.
