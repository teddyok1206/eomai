# Observability Deployment Audit

Date: 2026-08-15 UTC

## Scope

This audit covers only the `eom-observe` release boundary. It does not inspect or record secret
values, process environments, Codex authentication, worker homes, NAS content, or PostgreSQL business
data.

## Before The Fix

The deployed console was source-coupled even though its Python environment was dedicated:

| Item | Observed value |
| --- | --- |
| Application distribution | `eom-observe==0.1.0` |
| Contract distribution | `eom-observe-contracts==0.1.0` |
| Install mode | PEP 660 editable for both distributions |
| Application import | `/home/eom/EOM/apps/observe_console/eom_observe/__init__.py` |
| Contract import | `/home/eom/EOM/packages/observe_contracts/eom_observe_contracts/__init__.py` |
| Console script | `eom-observe = eom_observe.cli:main` |
| Build backend | `setuptools.build_meta`, setuptools 80.9.0 |
| Unit working directory | `/home/eom/EOM` |
| Pre-change service | active and enabled |
| Pre-change live health | PASS on loopback port 8780 |

Both `direct_url.json` files contained a local source URL and `"editable": true`. The observer
site-packages directory contained two `__editable__` `.pth` files and two editable finder modules.
Those finders mapped imports back to the Git checkout.

Static files were declared as `eom_observe` package data but were reached through the editable source
mapping. Observe JSON Schemas were not package data: contract validation walked three parents from
`__file__` to `schemas/observe`. Worker config and the fallback systemd unit were also found by walking
to the repository root. Snapshot deployment revision read `.git/HEAD` and a ref file on every build.
No `git` subprocess was run, but the deployment revision still depended on the checkout.

## Corrected Release Boundary

`eom-observe==0.1.1` is a single wheel containing:

- `eom_observe` and `eom_observe_contracts` Python packages;
- all local HTML, CSS, JavaScript, and SVG assets;
- all eight Observe JSON Schema documents;
- the five-slot observer projection config;
- console entry point, wheel metadata, and generated `build-info.json`.

All runtime resources are opened with `importlib.resources`. `build-info.json` records the exact
40-character source commit, package version, and UTC build timestamp. Runtime code neither walks to
the repository nor reads `.git` nor invokes Git.

The installed unit works from `/var/lib/eom-observe` and makes `/home/eom/EOM` inaccessible. The
existing NAS, Docker socket, worker-home, root Codex-auth, and platform-secret restrictions remain.

## Build And Install Controls

`scripts/observe/deploy_release.sh` requires the expected repository and branch and a clean working
tree. It stages inputs under `/tmp/eom-observe-build/<commit>/`, generates immutable build metadata,
builds with PEP 517, and inspects wheel packages, assets, schemas, entry point, metadata, and forbidden
editable markers before installation.

Installation uses only `/srv/eom/conda/envs/eom-observe/bin/python` and the exact command semantics
`pip install --no-deps --no-cache-dir --force-reinstall <wheel>`. Only the two known observer
distributions are inspected, and only known editable distributions are removed. No other environment
package is uninstalled. Deployment records and a prior unit copy are stored with mode 0600 below
`/var/lib/eom-observe/deployments/` for rollback.

Post-install verification rejects source imports, editable metadata and finder files, repository
paths in the service environment, incorrect working directory, missing package resources, public
binds, failed health/authentication/SSE checks, write-capable DB access, or readable restricted paths.

## Residual Operational Rule

Build artifacts remain under `/tmp` and are never committed. A branch switch, including later HWPX
work, cannot affect the installed process. A source change becomes active only after a clean committed
revision is explicitly rebuilt and deployed.
