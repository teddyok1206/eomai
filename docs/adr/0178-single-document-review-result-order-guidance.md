# ADR 0178: Single-document review result ordering guidance

## Status

Accepted on 2026-10-03.

## Context

A single-document V1 worker finished successfully but submitted two distinct target anchors in
descending `anchor_id` order. The existing typed contract correctly rejected the result as
`WORKER_RESULT_INVALID`. Paired review already described these ordering rules in its job-local
schema; the single-document projection did not.

## Decision and boundary

Extend the existing worker-facing constrained JSON Schema descriptions and the V13 admitted
contract notice. Describe target and candidate identity order, ascending unique page numbers,
ascending unique anchor identities, and confirmed-candidate/finding correspondence explicitly.
Share the descriptions for common V1/V2/V3 fields so they cannot drift between review paths.

The canonical source remains the released JSON Schema and Pydantic contracts. Released schema
bytes, control/instruction revisions, document pointers and hashes, and historical workflows are
unchanged. The notice is a deterministic job-local materialization of existing requirements, not a
new control revision or review protocol. Existing execution records retain the materialized
instruction and constrained-schema hashes; the installed runtime release identifies the projection.

No database, queue, claim, transaction, concurrency, or artifact model changes are needed. The
application materializer stages the notice; workflow contracts own schema projection and typed
validation. Workers still receive only orchestrator-staged inputs and submit local results.

Access is bounded dictionary lookup into schema definitions: O(1) per described field. Existing
bounded collection validation remains authoritative; no extra document reads, copies, or persisted
derived state are introduced. There is no new dependency.

## Verification, failure and rollback

Tests cover single-document descriptions, strict worker-schema compatibility, sorted acceptance,
unsorted/duplicate rejection in targets, candidates and findings, and non-mutation of submitted
results. Materializer tests check that the exact notice reaches the worker workspace.

Silently sorting submitted results is rejected: it could conceal an attestation mismatch. Invalid
results continue to fail closed. The failed workflow and worker output are not repaired, retried or
declared successful. A user can start a new review after release activation. Rollback restores the
previous compatible runtime wheel set; it does not modify documents or history.
