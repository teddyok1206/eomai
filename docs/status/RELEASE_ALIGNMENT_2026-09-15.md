# EOM Release Alignment — 2026-09-15

Observed and deployed at: 2026-09-15 12:44–12:49 UTC

This is the durable S02 release record for the coordinated Application API and Scientific Studio
alignment. It records the exact source identity, release artifacts, quiescence boundary, installed
verification, and rollback inputs. It is not an educational-quality acceptance and does not replace
the immutable Workflow, Item, or HWPX receipts.

## Release identity

| Field | Value |
| --- | --- |
| Git branch | `main` |
| source commit | `d4748d1e0cb4832dbb5d8a6ffb1ce422e7270fe7` |
| source tree | `dd6d53a57f4298ce7e94def6270a063154a3a9f6` |
| source archive SHA-256 | `sha256:6dd95a66f31e5a93a859416e315a0b9e5fd58f800da319aa653019366ccbebbb` |
| migration head | `20260912_0035` |
| GitHub `origin/main` | exact source commit |

The source includes the read-only S01 baseline and a release fence that rejects installation while
an untracked active `eom-workflow-runner-*.service` transient consumer could retain the old shared
Python environment.

## Quiescence and consumer boundary

Immediately before installation, the typed read-only database projection reported:

- active platform jobs: 0;
- held or reconciling worker leases: 0;
- pending, leased, or processing Workflow commands: 0;
- processing API idempotency records: 0.

The two solution-report backfill transient consumers
`eom-workflow-runner-production.service` and `eom-workflow-runner-backfill.service` were stopped
after that check. They had no work to terminate. The base Workflow runner and the API, Catalog, HWPX,
and Web services remained active. The same database projection after deployment retained zero work
in all four categories. Historical non-terminal Workflow rows were not modified.

## Candidate artifacts

| Artifact | SHA-256 |
| --- | --- |
| `eom_api_contracts-0.1.0-py3-none-any.whl` | `e5e9ea859e722d68bb83adfdb2ae9e2d31ebc29ac01d1796e89a336f251d713a` |
| `eom_application_api-0.1.0-py3-none-any.whl` | `81e23811dd651f184d1a6ca6c9148dac096a3424f652b8d63c584be3be37a0de` |
| `eom_platform-0.1.0-py3-none-any.whl` | `09ae6440486d906c6712f93a66be169efb0e409c780ab14dd6d9dd32401e6241` |
| `eom_web_gui-0.1.0-py3-none-any.whl` | `bb6c378e261aeffba52a22ccfa63aea82a495cf89264d904f096deb33ba726f5` |

Build-only, installed-wheel import, distribution `RECORD`, migration admission, runtime isolation,
and source-checkout independence checks passed before installation. The release build directories
under `/tmp` are build materializations, not canonical release identity.

## Installed verification

The Application API deployment created the protected rollback record
`/var/lib/eom-api/deployments/d4748d1e0cb4832dbb5d8a6ffb1ce422e7270fe7.json`.

Post-install evidence:

- API build information resolves to source commit `d4748d1`, tree `dd6d53a…a9f6`, and archive
  `sha256:6dd95a…ebbb`;
- Web build information resolves to source commit `d4748d1`;
- API release verification and runtime-isolation verification passed;
- Web installed identity verification covered 28 packaged files;
- API, Web, Catalog application runner, base Workflow runner, and HWPX application runner are
  `active/running`, with restart count zero and successful main-process status;
- Scientific Studio `/studio/api/v1/health/live` returned `LIVE` and
  `/studio/api/v1/health/ready` returned `READY`, with Application API and Observability active.

Authenticated Preview, media authorization, stale-response browser behavior, and secure download
remain S03/S04 gates; health and installed identity are not substitutes for those checks.

## Rollback inputs

The immediately preceding compatible wheels were retained for bounded rollback:

| Component | Prior source | Wheel SHA-256 |
| --- | --- | --- |
| API contracts | `3a5c6e44769e02417aa58f102e0d36bd9dc0cb42` | `57444365d93faa3aea6e4c47ee5624db40cf8717f38c2e328314ca57ec4dba35` |
| Application API | same | `c84dc0cea77f7cfcd70e4f306ffdb532dc805bb46c580ad55fc0ffa187027b44` |
| Platform | same | `2f77312c02e3e9c05753a43a87412e7bceab86eb8c18696db3fb93329cc7860f` |
| Scientific Studio Web | `a32a124b6cb68e624fc5acda3176216684a527a4` | `1f99634a9c0450d8f6d222295d09ee5c11d78e81f10ab81b6c0989ad873432d3` |

Rollback is component-release selection followed by the same identity, health, and compatibility
verification. It must not rewrite database history, Artifact bytes, Workflow pins, Pack activation,
or Graph revisions. A timeout or partial failure must be reconciled against the protected deployment
record and installed build information before replay.

## S02 result

`RELEASE_ALIGNMENT=PASS`

`AUTHENTICATED_PRODUCT_SMOKE=PENDING_S03`

