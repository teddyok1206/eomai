# ADR 0047: Automate validated legacy extraction acceptance and learning

Status: Accepted

Date: 2026-09-04

## Context and responsibility

The legacy corpus batch already performs source review, isolated extraction, canonical JSON Schema
and Pydantic validation, and Orchestrator-only NAS commit. Requiring a second person to restate
`ACCEPT` for every fully validated result prevents the corpus from progressing and leaves accepted
content outside the canonical Item and Education Graph paths. This decision applies only to legacy
extraction results that have crossed all existing canonical and artifact boundaries. It does not
auto-approve ordinary authoring workflows or relax extraction validation.

## Canonical source and revision model

The immutable extraction result Artifact Revision is the canonical source. Automatic acceptance
creates the existing immutable acceptance document and pointer; promotion creates the existing Item
logical entity and immutable Item Revision; Knowledge Analysis creates its existing immutable run,
proposal, accepted result, and graph snapshot/event history. Logical IDs, revision IDs, Artifact IDs,
and hashes remain separate.

## Pointer and resolution checks

Automatic acceptance pins the result Artifact ID, Artifact Revision ID, member path, schema,
media type, Artifact content hash, extraction result ID, and result self-hash. It re-reads and
validates the exact result before producing a deterministic acceptance. Promotion and learning use
the existing acceptance, Item, origin, workflow, preset, risk-policy, and Artifact resolution
checks. Missing, stale, non-approved, malformed, or hash-mismatched pointers fail explicitly.

## Access patterns and data structures

The hot path is an indexed FIFO claim/reconcile operation. When automatic policy is enabled, a due
completed result is reconciled before another extraction claim. Membership and local reference
normalization use maps and sets in O(n) time. Learning candidates use indexed acceptance/result,
unique Item registration-key, and Knowledge Analysis source-history lookups; binary content remains
outside PostgreSQL.

Expected scale is hundreds to low thousands of work units per batch. Acceptance construction is
O(items + anchors), bounded by the existing eight-item and 16 MiB result limits. Stored space is one
small acceptance JSON Artifact plus existing pointer rows per result.

## Transaction, concurrency, failure, and retry

Artifact commit and registry insertion retain their existing transaction boundaries. Automatic
acceptance identity is derived from the immutable result pointer, so replay after a crash resolves
the same document and idempotency key. The batch row is bound only after that acceptance is
registered. The global extraction claim lock continues to permit one claimed/submitted extraction.
Failures remain immutable; continuation uses fresh work-unit and workflow identities after a
systematic cause is fixed.

## Dependency direction and ownership

The Catalog application runner selects the explicit deployment policy. It calls application
services; acceptance and promotion own Catalog/NAS writes; the Orchestrator owns worker execution
and result commits. Workers remain unable to communicate with peers, write PostgreSQL, or write NAS.
Contracts and identifiers do not import infrastructure.

## Decision

- Enable `AUTO_ACCEPT_VALIDATED` explicitly in the Catalog service unit.
- Construct an existing acceptance document with actor
  `system.legacy-item-auto-acceptance`, complete coverage, and one `ACCEPT` decision per exact
  proposal. Do not record a human review that did not happen.
- Preserve every canonical extraction validation and NAS boundary.
- Reconcile successful results to `ACCEPTED` before claiming more work.
- Promote accepted proposals idempotently through the existing Item/origin service, then schedule
  the existing approved-item Knowledge Analysis path with pinned deployment policy inputs.
- Stop on a new systematic extraction or analysis failure; do not blind-retry the same workflow.

## Alternatives

Direct SQL state updates are simpler but insufficient because they omit immutable acceptance
evidence, Artifact/NAS provenance, transition events, Item registration, origin records, and Graph
learning. Keeping manual review is safer for editorial authoring but is unnecessary duplication for
this already source-reviewed, canonical extraction pipeline and does not meet the corpus-processing
requirement. A new parallel queue was rejected because the current durable batch and analysis state
machines already own the required idempotency and concurrency boundaries.
