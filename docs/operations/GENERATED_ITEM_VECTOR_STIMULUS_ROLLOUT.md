# Generated item SVG-first rollout

Status: reviewed source rollout procedure

Last reviewed: 2026-08-28 UTC

## Boundary

This rollout makes `generic-item-development@1.5.0` the default one-item workflow. The image worker
returns a bounded SVG overlay; Catalog adds a deterministic background, creates the canonical SVG,
rasterizes the current 800×500 PNG delivery member, and commits both members in one immutable
Artifact Revision. It does not authorize a live item workflow or HWPX build.

The only enabled production route is `DETERMINISTIC_SVG`. `LOCAL_GENERATIVE_BACKGROUND` and
`HUMAN_REVIEWED_BACKGROUND` are reserved contract values and fail closed until separate reviewed
provider adapters and immutable input/output pointers exist. External image or LLM APIs are not a
supported provider class.

## No-interruption gate

Do not run the installation phase while any fixed Codex worker unit is active or while an analysis
batch depends on the workflow runner. The canonical API release installation restarts API,
Catalog, workflow runner, and HWPX application runner as one compatible platform set. Waiting for a
terminal/safely drained Slot 5 boundary is mandatory; killing, pausing, or reassigning Slot 5 merely
to deploy this feature is forbidden.

The preflight must record, without printing worker content:

- clean `main` at the reviewed commit and matching `origin/main`;
- no active `eom-worker-05@*.service` unit and no held/reconciling Slot 5 lease;
- active batch terminal, or an explicit durable safe checkpoint that requires no running daemon;
- active/enabled API, Catalog, workflow runner, HWPX runner, and Scientific Studio services;
- currently active `generated-knowledge-item` release and `standard-item` preset revision;
- unchanged port 8000 and `/home/eom/EOMIS`.

## Source and package gates

Before installation, require:

1. V5 canonical/package role schemas are byte-identical and Draft 2020-12 valid.
2. Historical V4 schema hashes and prior workflow/pack hashes remain exact.
3. SVG attacks, malformed geometry, wrong fonts, unavailable provider routes, re-entry, and dual
   SVG/PNG Artifact commit tests pass.
4. Workflow, Catalog, API, HWPX, Web, strict mypy, Ruff, shell syntax, repository-boundary scan,
   and guarded PostgreSQL integration tests pass.
5. `scripts/api/deploy_release.sh --build-only` and `scripts/web_gui/build_release.sh` pass from the
   clean reviewed commit.

Install the deterministic renderer only through the reviewed Ubuntu package boundary:

```bash
sudo -n /home/eom/EOM/scripts/catalog/install_svg_rasterizer.sh
```

The script permits Ubuntu 24.04 packages `librsvg2-bin` and `fonts-droid-fallback`, verifies the
fixed root-owned paths, and installs no Python dependency. Catalog accepts only the system family
`Droid Sans Fallback`; the renderer version, renderer SHA-256, and font SHA-256 are stored in the
stimulus Artifact result provenance.

## Compatible deployment order

Use one protected operator evidence directory and record only IDs, versions, hashes, and sanitized
status. The order prevents a new V5 request from reaching an old reader:

1. Install the clean platform/API wheel set with `scripts/api/deploy_release.sh --install`.
2. Install the reviewed workflow configuration with
   `sudo -n scripts/workflow/install_runner_configuration.sh`.
3. Publish `standard-item-v3` through `eomctl control-plane bootstrap-standard`, using the exact
   reviewed source commit, the canonical `/home/eom/EOM/content` directory, a valid ADMIN actor ID,
   and the reviewed non-live evaluation count `4`.
4. Validate, build, import, release, and activate
   `content/packs/generated-knowledge-item/1.3.0`; verify all source/bundle/manifest hashes before
   activation.
5. Verify the active Content Pack pointer resolves exactly to version `1.3.0` and preserve the prior
   release ID for pointer-only rollback.
6. Install the reviewed Scientific Studio wheel and restart only its service after the backend,
   definition, preset, and active pack are ready.

`generated-knowledge-item@1.3.0` is the creation-time companion of workflow `1.5.0`. Activating it
intentionally moves new requests to V5; historical workflows retain their immutable prior pack and
schema pointers. Never reinterpret or rewrite a historical V4 result. If a legacy client must keep
creating V4 workflows, implement an explicit version-selection contract instead of silently binding
it to the new active pack.

## Non-generating acceptance

Before a usage-consuming workflow, verify through installed packages and actual service identities:

- workflow `1.5.0`, role protocol `workflow-role/1.12.0`, and all four `*-result@5.0` schemas load;
- `standard-item` resolves to the released V3 preset and exact reference Artifact Revisions;
- Content Pack `1.3.0` resolves and its four profiles point to the V5 result family;
- Catalog can read the fixed font and invoke `/usr/bin/rsvg-convert` under its systemd identity;
- a disposable typed SVG fixture produces one deterministic SVG/PNG pair twice with identical
  hashes and no DB/NAS commit;
- unsafe SVG and both undeployed provider routes fail before Artifact or Item registration;
- API, Catalog, workflow runner, HWPX runner, Web, and observability remain active/enabled;
- internal ports remain loopback-only and Slot 5 remains unclaimed by this acceptance.

A live one-item workflow is a separate one-shot authorization. Its acceptance must prove that the
image result, stimulus SVG/PNG Artifact Revision, approved Item Revision image pointer, and HWPX
output all resolve to exact immutable revisions and hashes.

## Rollback

Rollback is pointer-oriented:

1. stop accepting new V5 requests;
2. let any already-started V5 workflow finish or fail closed; do not reinterpret it as V4;
3. restore the prior active Content Pack release and prior `standard-item` preset pointer;
4. restore the prior default workflow/GUI release as one compatible set;
5. retain all immutable V5 role results, stimulus artifacts, Items, audit events, and package
   releases.

Do not uninstall the system renderer/font, delete artifacts, mutate historical rows, touch the
textbook-analysis batch, alter port 8000, or modify `/home/eom/EOMIS` as part of rollback.
