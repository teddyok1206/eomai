# ADR 0177: Resolve document-review presets by their declared schema

## Status

Accepted on 2026-10-03 for the single-document review incident.

## Decision and boundary

The current `pdf-document-review` preset explicitly supports worker protocols
1.25, 1.26, and 1.27, but its V5 bootstrap publishes a V2 execution preset.
The single-document V13 and predecessor paired V14 resolvers incorrectly
decoded that exact current revision as V1. A valid HWP conversion consequently
failed with `PDF_DOCUMENT_REVIEW_REQUEST_UNSUPPORTED` before worker submission.

Decode the exact current released revision with its declared V1 or V2 schema,
validate the schema, hash, identity, lifecycle and declared protocol support,
and retain the existing isolated support-role checks. Unknown or malformed
presets fail with a control-plane error, not a document input error. Share this
small rule between the two real predecessor resolvers; do not search older
revisions or strip V2 fields to pretend they are V1.

V13 and V14 remain non-Graph execution contracts. A V2 preset does not grant
them an Evidence Bundle, receipt, or a second document. Their materialized job
instructions explicitly identify the actual predecessor input/output contract
and make unavailable Graph/paired requirements in a shared newer role bundle
inapplicable. Preserve the pinned bundle bytes and safety instructions. The
existing deterministic AGENTS materialization hash records this execution view.
V15 remains the exhaustive Graph-grounded paired path and is unchanged.

## Data and execution model

- Canonical sources: the released preset revision, pinned instruction bundle,
  document revisions and existing worker/result schemas.
- Identity: logical preset, immutable preset revision and content hash remain
  separate; output plans pin them. No new aggregate, schema, queue or migration.
- Access: indexed current-revision lookup and replay lookup, then bounded
  validation of at most five role policies. Time/space remain O(preset size).
- Transactions: the existing workflow/plan transaction owns creation; immutable
  plan replay precedes mutable current-pointer resolution. No DB row repair.
- Ownership: Application admission calls Orchestrator resolution/materialization;
  contracts remain independent of persistence and workers remain isolated.
- Failure/retry: invalid operational configuration is explicit and retryable at
  the upload application boundary; legitimate page/size limits are unchanged.
  Historical final failures remain unchanged. No automatic resubmission.
- Simpler alternative: only switching the decoder would leave the V5 paired
  Graph-only instructions conflicting with single-document inputs. Removing
  strict validation or selecting an older preset would break exact pinning.

## Verification

Cover V1/V2 resolution and exact pinning, replay without current-policy access,
unknown/invalid schema, hash and record identity drift, declared compatibility,
single-document contract instructions, unchanged Graph V15 materialization and
source/request limits. Use synthetic/non-live tests; never run mutating pytest
against the production database. Deployment/read-only preflight is separate
from a completed live worker review.
