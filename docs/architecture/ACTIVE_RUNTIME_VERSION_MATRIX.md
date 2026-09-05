# Active runtime version matrix

This matrix distinguishes new-work admission from historical replay. “Historical” never means
invalid or deletable: an existing workflow, item revision, pack release, preset revision, or
Artifact continues to resolve the exact immutable version and SHA-256 hash that it pinned.

## New-work workflow paths

| Entry path | Workflow definition | Role protocol | Primary result contract |
| --- | --- | --- | --- |
| Generated item | `generic-item-development/1.7.0` | `workflow-role/1.15.0` | authoring/review/registration `@7.0` |
| Intake or approved item analysis | `knowledge-analysis/1.0.0` | `workflow-role/1.4.0` | proposal `@1.0`, accepted result `2.0` |
| Text document analysis | `knowledge-analysis/4.0.0` | `workflow-role/1.7.0` | proposal `@4.0`, accepted result `5.0` |
| Multimodal document analysis | `knowledge-analysis/8.0.0` | `workflow-role/1.11.0` | proposal `@8.0`, accepted result `8.0` |
| Legacy assessment extraction | `legacy-item-extraction/1.0.0` | `workflow-role/1.14.0` | extraction result `@1.0` |
| Legacy editorial compatibility | `legacy-item-editorial-compatibility/1.0.0` | `workflow-role/1.16.0` | compatibility result `@1.0` |

The code authority for this table is `eom_workflow.admission`. The DB authority for whether a
definition accepts new work is `workflow_definitions.active`; `eomctl workflow definition admission`
audits it and `--apply` reconciles it atomically.

## Generated-item and HWPX path

New generated items use the active `generated-knowledge-item/1.12.0` Content Pack release and the
V2 item-content contract. Auto HWPX rendering selects `content-team/1.0` for V2. The V1 item-content
contract and `eom-template` renderer remain historical/read compatibility paths; they are not
silently upgraded because an immutable item revision must retain its original content hash.

## Catalog application socket routes

The private socket is one framed protocol with operation-specific request and response projections;
the numeric suffixes are not competing runtime selections. Both endpoints consume the single
`CATALOG_APPLICATION_SCHEMA_ROUTES` map.

| Operation | Request schema | Response schema |
| --- | --- | --- |
| Import/load item content | v10 | v10 |
| Create knowledge analysis | v5 | v3 |
| Reconcile/review knowledge analysis | v3 | v3 |
| Create knowledge-analysis batch | v9 | v7 |
| Create evidence bundle | v3 | v9 |
| Create item-production evidence | v4 | v8 |

## Retention and removal rule

- Keep a historical contract or definition while any immutable row, manifest, receipt, or release
  pins it, or while it is required to validate those records.
- Mark historical workflow definitions inactive so they cannot accept new requests.
- Remove only code or files with zero immutable references and zero validation/rebuild use, in a
  separate reviewed deletion after an inventory proves both conditions.
- Never rewrite a historical ID/hash to make versions appear uniform. Consistency means one active
  admission decision at each boundary, not one numeric suffix across unrelated contracts.
