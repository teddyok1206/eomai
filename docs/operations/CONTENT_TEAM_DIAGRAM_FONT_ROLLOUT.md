# Content-team diagram font rollout

## Scope

This rollout installs the reviewed content-team diagram fonts, deploys the Catalog renderer update,
and activates `generated-knowledge-item@1.6.0` for new workflows. It does not modify EOMIS, HWPX
templates, existing Item/Artifact Revisions, worker accounts, the textbook-analysis batch, or local
GPU model files.

## Immutable preflight

1. Require the reviewed Git commit and a clean working tree.
2. Require API, Catalog application runner, workflow runner, HWPX runner, and Web services active.
3. Require no currently executing one-item workflow at the Catalog registration boundary before
   restarting Catalog.
4. Record the current active `generated-knowledge-item` release for pointer-only rollback.
5. Verify the authorized source directory is a non-symlink and contains exactly the expected font
   bytes:

   - `SM중고딕.OTF`: `9200e1e46cca77f0ff9481c5345c3333caf22d50487418df74f830e4221adea1`
   - `NotoSansCJKkr-Regular.otf`:
     `6bcb2a0703aa137e874fc2dffa85f6c21ba9a67fa329e81b8c801663af7e992a`
   - `CenturyOldStyle-Regular.otf`:
     `7f9420403e10e7e74f002fbb48e8034d48f64cbdbef556d4f964b266043de338`
   - `CenturyOldStyle-Italic.otf`:
     `44b00cbdab9fdb7b4307db79784c5b90cbc52c5ffb0add32ac8239d73e567809`

Do not copy or modify EOMIS source files. The installer only reads the approved source directory and
materializes verified root-owned runtime copies.

## Deployment

```bash
sudo -n scripts/catalog/install_content_team_svg_fonts.sh \
  --source-dir /home/eom/EOMIS/var/experiments/source_guidelines_inventory/fonts \
  --korean-fallback-source /home/eom/.local/share/fonts/eomis/NotoSansCJKkr-Regular.otf
sudo -n scripts/catalog/install_svg_rasterizer.sh
scripts/api/deploy_release.sh --build-only
scripts/api/deploy_release.sh --install
sudo -n systemctl restart eom-catalog-application-runner.service
```

Validate, build, import, release, inspect, and activate
`content/packs/generated-knowledge-item/1.6.0` using the normal Content Pack commands. Verify the
source-tree, bundle, and manifest hashes at every step and resolve the development pointer back to
the exact new release ID.

## Non-usage-consuming smoke

Run the focused deterministic SVG fixture as the actual Catalog service identity. Require:

- Fontconfig resolves `SM JGothic Std`, regular/italic `Century Old Style`, and `DejaVu Serif` to
  the exact reviewed system paths.
- A Korean label rasterizes without a missing-glyph box and the deterministic PNG hash repeats.
- ASCII line-graph axes use `Century Old Style`; Hangul axes use `SM JGothic Std`.
- Unknown fonts, implicit fonts, Korean text under a Latin font, symlinks, wrong owner/mode, and hash
  drift fail closed.
- Artifact result provenance includes renderer contract `eom-safe-svg-compositor/1.1`, font profile
  `eom-content-team-diagram-fonts/1.0`, primary font SHA, and font-manifest SHA.

No live item workflow or HWPX build is part of this smoke.

## Rollback

1. Restore the prior active Content Pack release pointer.
2. Reinstall the prior reviewed API/platform wheel set and restart only Catalog if required.
3. Preserve the installed fonts and every historical SVG/PNG Artifact Revision; their hashes remain
   valid and removing a renderer dependency is unnecessary.

Rollback must not modify EOMIS, Slot 5, workers, PostgreSQL schema, HWPX templates, port 8000, or
canonical Items.
