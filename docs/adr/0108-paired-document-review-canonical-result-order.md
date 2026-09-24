# ADR 0108: Paired document-review canonical result order

## Status

Accepted on 2026-09-24.

## Context

`pdf-document-review-result@2.0` already requires deterministic, unique target, candidate, finding,
cross-document-check, page-reference, and anchor collections. JSON Schema 2020-12 validates the
closed shapes while Pydantic enforces ordering relations that JSON Schema cannot express. The V2
role instruction described exact locations but did not tell the worker how to order every emitted
collection. A validly shaped result therefore reached typed validation with five unsorted target
anchor collections and failed closed as `WORKER_RESULT_INVALID`.

The canonical source is the immutable role instruction bundle together with the existing V2 result
contract. The failed workflow, worker output, and V2 control revisions remain immutable history.

## Decision

Publish `pdf-document-review-control-bootstrap/3.0` as an exact successor of the active V2 preset
and instruction revisions. Its role instruction explicitly states every existing canonical ordering
rule. The constrained worker-facing JSON Schema repeats those rules as descriptions without
changing the released `pdf-document-review-result@2.0` schema bytes or weakening Pydantic.

The logical preset and instruction bundle remain stable; only immutable revisions advance. The
bootstrap transaction locks and checks the current preset and bundle, their revision IDs, hashes,
states, and the next instruction revision number before publication. Idempotent replay returns the
same successor; concurrent or stale publication fails closed.

## Data and access patterns

- Current control resolution is an indexed lookup by preset key and bundle key: O(1) database
  lookup plus bounded revision validation.
- Result validation iterates each bounded collection once: O(n) time and O(n) temporary set space
  for uniqueness.
- No source document, page PNG, worker result, or other binary is duplicated in PostgreSQL.
- Workflows pin the exact preset and instruction revisions resolved at start; no historical workflow
  follows a mutable current pointer.

## Alternatives

Silently sorting worker output was rejected because it would repair an attestation after submission
and could hide a candidate/finding mismatch. Weakening typed validation was rejected because stable
ordering is required for reproducibility and exact relation checks. Replacing the result protocol
was unnecessary because the semantic rule already exists; the omission was instructional.

## Failure and rollback

If predecessor identities differ, publication stops with
`CONTROL_BOOTSTRAP_PREDECESSOR_MISMATCH`. If the successor performs worse, activation can return to
the prior released preset revision without deleting V3 or altering historical workflows. Existing
failed workflows are not retried or rewritten; a user starts a new review after activation.
