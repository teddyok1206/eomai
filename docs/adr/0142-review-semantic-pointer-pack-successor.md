# ADR 0142: Review semantic pointer Pack successor

## Status

Accepted for implementation on 2026-09-28 UTC.

## Context and responsibility

The review worker reports bounded RFC 6901 pointers into the immutable authoring draft. The
orchestrator, not the worker, owns the authoritative semantic-leaf validation. A live canary showed
that the review prompt permitted the model to cite `/metadata/subject`, while the trusted validator
correctly permits only answer-bearing or editorial draft roots. Repeating the same deterministic
contract error consumed review attempts without changing the pinned input.

The Content Pack owns worker guidance. The workflow runner owns retry classification. Existing
Pack `1.20.1`, role schemas, Artifact revisions, job history, and validation rules remain immutable.

## Decision

- Publish `generated-knowledge-item@1.20.2` as a successor of `1.20.1`.
- Change only the Pack identity, review profile revision, and review prompt.
- The prompt lists the exact semantic root allowlist and explicitly forbids metadata/provenance,
  renderer, score, and item-number paths. Curriculum verification must point to actual semantic
  leaves such as the stem, statements, choices, inquiry, or explanations.
- Classify the trusted validator's `EVIDENCE_DRAFT_POINTER_INVALID`,
  `EVIDENCE_DRAFT_POINTER_MISSING`, and `EVIDENCE_DRAFT_POINTER_NOT_LEAF` detail codes as
  deterministic pre-commit failures. The same applies to
  `EVIDENCE_REVIEW_TARGET_SOURCE_INVALID` and `EVIDENCE_REVIEW_TARGET_SOURCE_MISSING`, because the
  worker selected evidence classes that cannot satisfy its own immutable target declaration. They
  terminate the current workflow attempt series; a fixed Pack and a fresh workflow identity are
  required.

## Data and access patterns

No database, queue, schema, or Artifact model changes. Pack resolution remains an indexed lookup by
pack key and immutable release revision. Retry classification remains O(1) membership in a frozen
set. Draft pointer resolution remains O(number of bounded pointers x pointer depth), using mapping
lookup and array indexing. No binary data is stored in PostgreSQL.

## Transactions, failure, and rollback

The orchestrator continues to reject an invalid result before NAS commit. Existing failed jobs and
their immutable results remain historical evidence. Pack release and activation use the existing
Catalog transaction and idempotency boundary. Rollback is activation of the previous `1.20.1`
release; no row or Artifact is rewritten.

## Simpler alternative considered

Relaxing the trusted root allowlist or silently dropping `/metadata/subject` would make a malformed
attestation appear valid and would weaken reproducibility. Retrying the identical worker input does
not repair a deterministic contract violation. A prompt-only immutable successor plus terminal
classification is the smallest change that preserves the trust boundary.
