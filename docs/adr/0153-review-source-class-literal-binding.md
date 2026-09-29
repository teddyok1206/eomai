# ADR 0153: Review source-class literal binding Pack successor

## Status

Accepted for implementation on 2026-09-29 UTC.

## Context and responsibility

The review worker selects immutable Evidence IDs and declares the source classes required by each
verification target. The orchestrator owns the trusted comparison against the pinned Evidence
manifest. A live image-generation canary selected a `TEXTBOOK` evidence entry correctly but wrote
`CURRICULUM` in `required_source_classes`, apparently translating the semantic purpose of a
curriculum-scope check into a different source-class enum. The trusted validator correctly rejected
the result with `EVIDENCE_REVIEW_TARGET_SOURCE_INVALID` before Artifact commit.

The Content Pack owns the detailed worker guidance. Existing Pack `1.20.5`, review result schema
`review-result@12.0`, failed Workflow history, and validator behavior remain immutable.

## Decision

- Publish `generated-knowledge-item@1.20.6` as a prompt-only successor of `1.20.5`.
- Increment the review profile revision to `12.0.2` and change only the Pack manifest, review
  profile, and review prompt.
- Treat `source.source_class` as an opaque literal enum. For every selected Evidence ID, the worker
  must look up the exact manifest entry, copy its literal class without semantic translation, then
  sort and deduplicate the resulting values.
- State explicitly that a `CURRICULUM_SCOPE` target does not imply a `CURRICULUM` source class and
  that `TEXTBOOK` must remain `TEXTBOOK`.
- Keep the trusted validator fail-closed. Do not repair or derive a worker's malformed declaration
  after submission.

## Data and access patterns

No database, queue, workflow, Artifact, or result-schema change is required. Manifest lookup is a
bounded key lookup by Evidence ID. The worker already receives the pinned manifest; the new rule
only removes an ambiguous semantic translation. Pack resolution remains an indexed immutable
release lookup.

## Transactions, failure, retry, and rollback

The historical failed Workflow remains failed. A fresh Workflow identity uses the successor Pack.
The orchestrator still rejects any source-class mismatch before NAS commit. Rollback is activation
of Pack `1.20.5`; no row or Artifact is rewritten.

## Simpler alternative considered

Relaxing the validator or silently replacing the worker's classes with manifest values would hide a
false attestation. Retrying the identical immutable Pack can repeat the deterministic mistake. A
prompt-only immutable successor is the smallest change that preserves the trust boundary.
