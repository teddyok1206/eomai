# ADR 0109: Document-review recommendation payload projection

## Status

Accepted on 2026-09-24.

## Context

`PdfReviewRecommendation` already validates operation-dependent payloads after worker submission.
The released result schema keeps `before_text` and `after_text` nullable because JSON Schema
conditionals are outside the Codex strict-output subset used by this runtime. The active role
instruction did not enumerate those relations. A paired review therefore emitted `DELETE` with a
null `before_text`; the worker exited successfully and the orchestrator correctly failed closed as
`WORKER_RESULT_INVALID`.

The canonical sources remain the immutable request, the released result schema, and Pydantic's
semantic validator. Historical failed workflows and V1--V3 instruction revisions are immutable.

## Decision

Publish `pdf-document-review-control-bootstrap/4.0` as the exact successor of V3. The role
instruction enumerates operation payloads and the remaining paired-review relations. Project the
existing recommendation model into a strict-output `anyOf` with one closed branch per operation.
This is a strict subset of the released semantic contract and prevents a known-invalid payload
before worker submission without repairing or weakening an attestation.

## Data structures and access patterns

- Result validation is one bounded ordered traversal: O(n) time and O(n) temporary set space.
- Recommendation branch selection is a seven-entry immutable tuple and therefore O(1) bounded work.
- Control resolution remains indexed lookup by preset and bundle keys with immutable revision pins.
- No PDF, page PNG, worker result, or other binary is copied into PostgreSQL.

## Transaction, retry, and rollback

The bootstrap compares and locks exact V3 preset and bundle revision IDs and hashes before one
successor publication. Stable idempotency keys and current-revision CAS prevent duplicate or stale
activation. Failed workflows are never rewritten or automatically retried. Rollback changes only
the active released preset revision; it does not delete V4 or modify history.

## Alternatives

Silently filling `before_text` from an anchor quote was rejected because that would mutate the
worker's attestation. Weakening Pydantic was rejected because downstream annotation and correction
need the exact original text. A new result protocol was unnecessary because the semantic invariant
already exists; the missing boundary was its strict-output projection and instruction.
