# ADR 0049: Separate active workflow admission from historical protocol replay

Status: Accepted

Date: 2026-09-05

## Responsibility and system boundary

Workflow versions serve two different purposes: accepting new work and reproducing immutable
history. The Workflow package owns one admission table for new instances. The Workflow Runner
persists and reconciles the table, while Catalog and API services continue to resolve historical
schemas from the definition and revision pinned by an existing workflow.

## Canonical source, revisions, and pointers

`eom_workflow.admission` is the canonical source for admitted definition key, definition version,
and role-protocol triples. A stored `workflow_definitions` row remains the immutable snapshot used
by every existing `workflow_instances.definition_id`; setting `active=false` never deletes or
rewrites it. Historical role/result schemas, Content Pack releases, item revisions, and Artifact
revisions remain addressable by their pinned IDs and hashes.

The admitted paths are:

| use case | definition | role protocol |
| --- | --- | --- |
| new generated item | `generic-item-development/1.7.0` | `workflow-role/1.15.0` |
| intake or approved-item analysis | `knowledge-analysis/1.0.0` | `workflow-role/1.4.0` |
| text document analysis | `knowledge-analysis/4.0.0` | `workflow-role/1.7.0` |
| multimodal stable-identity analysis | `knowledge-analysis/8.0.0` | `workflow-role/1.11.0` |
| legacy extraction | `legacy-item-extraction/1.0.0` | `workflow-role/1.14.0` |
| legacy editorial compatibility | `legacy-item-editorial-compatibility/1.0.0` | `workflow-role/1.16.0` |

## Required pointers and resolution checks

Admission resolves an exact `(definition_key, definition_version)` map key, then verifies that the
stored canonical definition derives the expected single role protocol. Missing admitted rows,
hash-conflicting imports, unexpected active rows, or protocol mismatches fail explicitly. Runtime
history continues to use `definition_id`, definition hash, preset revision, schema reference, and
Artifact revision without an implicit-latest substitution.

## Access patterns and data structures

New submissions perform exact-key lookup, so an immutable hash map is used: expected O(1) time and
O(v) space for six admitted identities. Reconciliation performs one ordered O(n) scan of the small
definition registry and set comparison. Historical instance lookup remains indexed by primary and
foreign keys; no list scan, cache, queue, or binary duplication is introduced.

## Transactions, concurrency, failure, retry, and idempotency

Reconciliation validates the complete desired set before updating any `active` flags and commits in
one transaction. Repeating it is idempotent. Existing instances are unaffected because execution
loads their pinned definition by ID rather than querying `active`. A failed or concurrent reconcile
rolls back normally. Re-enabling an old row requires a reviewed policy change, not an ad-hoc DB edit.

## Dependency direction and adapter ownership

The pure policy lives in the Workflow contract package. Workflow Runner implements persistence;
`eomctl` is only the explicit audit/apply adapter. Catalog socket request/response schema selection
likewise lives in Catalog contracts and is consumed by both client and server. Domain packages do
not import SQLAlchemy, filesystem, socket, or service modules.

## Simpler alternative and trade-off

Deleting old files or rows would make old workflows and artifacts unverifiable. Leaving every row
`active=true` and relying on callers to remember a latest version permits silent downgrade and
client/server drift. A small immutable admission map plus reversible flags preserves history while
making the supported production path explicit. Adding a version-negotiation framework is rejected:
the current fixed host has a small reviewed set and exact identities are safer and simpler.
