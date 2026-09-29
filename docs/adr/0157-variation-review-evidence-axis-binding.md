# ADR 0157: Variation review evidence-axis binding

## Status

Accepted for implementation.

## Responsibility and boundary

The exact-source variation review already requires a graph-grounded reviewer to select pinned
Evidence Bundle entries and to validate scientific correctness and curriculum scope independently.
A live review exposed a prompt/typed-contract gap: the worker declared a reference with both
purposes but left the scientific claim and curriculum assessment `evidence_ids` empty.  The typed
result correctly rejected it, but blind step retries repeated the same invalid shape.

This successor changes only the immutable Content Pack prompt and Catalog admission for that Pack.
It does not relax the result schema, edit a worker result, introduce direct worker communication,
or change released Pack 1.20.8.

## Canonical source, pointers, and access pattern

The canonical sources remain the plan-pinned Evidence manifest/context, solution-report pointer,
exact source Item Revision, authoring Artifact Revision, and their hashes.  Review performs bounded
key lookup by Evidence ID and set membership for the scientific and curriculum axes.  With at most
64 evidence references, validation remains O(E + U) time and O(E) space, where E is the manifest
subset and U is the bounded set of uses.

## Transaction, retry, and failure behavior

The worker still returns a local typed result and the Orchestrator alone validates and commits it.
For graph-grounded review, at least one scientific claim/choice/statement and the curriculum
assessment must each bind a real selected Evidence ID with the matching purpose.  The same entry may
support both when its content does so.  Missing usable evidence fails the role; IDs must never be
invented.  Existing job idempotency, leases, review retry, escalation, and rework state machines are
unchanged.

## Simpler alternative rejected

Weakening the Pydantic invariant or filling empty arrays after worker submission would create a
false attestation.  Repeating the same prompt consumes capacity without changing the deterministic
error.  An immutable prompt successor is the smallest change that preserves both the evidence
contract and historical reproducibility.
