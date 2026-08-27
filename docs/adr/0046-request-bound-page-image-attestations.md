# ADR 0046: Request-bound page-image attestations

## Status

Accepted.

## Context

A multimodal Knowledge Analysis request already pins every selected page PNG by physical page,
Artifact Revision, member path, SHA-256, and byte size.  The worker result repeats the physical page
and SHA-256 as a delivery attestation.  Asking a language model to transcribe an opaque 64-digit
hash permits a syntactically valid but wrong value.  Post-result validation correctly rejects that
value, but the avoidable transcription failure blocks an otherwise valid long-running batch.

The primary access pattern is an ordered lookup over at most 32 page images.  The request stores the
canonical tuple; the result is validated once.  A tuple preserves page order and a request-derived
map/set is unnecessary at this bounded projection step.  Artifact history and accepted outputs pin
immutable revisions and hashes and are never resolved through a mutable latest pointer.

## Decision

Keep the immutable V7 protocol schemas unchanged.  When the Orchestrator builds the job-specific
Codex result schema, project one closed `anyOf` branch per request page and bind both
`physical_page` and `image_sha256` with JSON Schema `const`.  Also bind the array length to the exact
request page count.  Existing typed validation still requires contiguous, unique, ordered pages;
the Artifact staging boundary still compares the full ordered `(page, hash)` tuple to the request.

This is a request-specific narrowing of an existing invariant, like the existing job, Artifact,
anchor, and page-range bindings.  It does not alter a persisted schema bundle, reinterpret an old
result, or silently repair worker output.

## Failure, retry, and scale

An invalid value now fails at the worker's structured-output boundary and cannot be committed.  The
Orchestrator performs no automatic retry.  Schema construction and validation are `O(p)` in page
count with `p <= 32`; the extra schema size is similarly bounded.  Batch FIFO and idempotency rules
are unchanged.

## Rejected alternative

Removing the hash from the result or rewriting it after generation would weaken or silently mutate
the attestation contract.  Creating a new protocol solely for a request-derived const that the
current protocol already requires would add lineage and deployment complexity without changing the
domain value.
