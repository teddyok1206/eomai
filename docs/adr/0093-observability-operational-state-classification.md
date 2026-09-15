# ADR 0093: Read-only operational state classification

Date: 2026-09-15

Status: Accepted for implementation

## Context and responsibility

The Observability service owns a read-only operational projection. Its existing
`observe-snapshot/1.0` summary counts every non-terminal Workflow as active. That is useful for
historical topology, but it cannot distinguish a Workflow backed by a claimable command, active
Job, held worker lease, or pending human approval from an old non-terminal row with none of those
execution edges. It also does not expose active command, lease, or API idempotency-claim counts.

This ambiguity caused historical Workflow 1.8 rows to appear beside current solution-report work.
The projection must not infer that an old row is safe to mutate or call it a state-machine defect.
It only classifies observable execution evidence and leaves repair to the owning application.

## Decision

Add the independent `observe-operational-overview/1.0` read contract. Do not change the bytes or
meaning of `observe-snapshot/1.0`.

The canonical source is one read-only PostgreSQL transaction over existing Workflow command,
Workflow, step, Job, worker-lease, approval, and API-idempotency records. The projection reports:

- active Workflow commands, active Jobs, held leases, processing API claims, and pending approvals;
- executable Workflows that have at least one active command, active Job, or held lease;
- quiescent non-terminal Workflows that have no such execution edge and no pending approval;
- recent and historical terminal Workflow/Job failure counts; and
- a bounded, newest-first attention list for quiescent non-terminal Workflows, expired claims or
  held leases, and recent failures.

`QUIESCENT_NONTERMINAL_WORKFLOW` means only that the current read model found no executable or human
edge. It does not mean cancelled, abandoned, broken, or eligible for direct database repair.
Likewise, a recent failure is an observation, not authorization to retry it.

The attention record carries only small correlation pointers: Workflow, Job, command, lease, or API
idempotency record ID; state; stable error code; and observation time. It never carries prompts,
Item content, arbitrary request payloads, filesystem paths, idempotency keys, tokens, or logs.

## Identity, access patterns, and structures

The overview is a transient immutable value, not a new logical entity or revision. Existing IDs
remain separate and are never synthesized into a replacement identity. The dominant operations are:

- equality membership in explicit active-state sets;
- indexed joins by Workflow or Job identity;
- count aggregation by state and time boundary; and
- bounded newest-first iteration of attention rows.

SQL uses `UNION`/`EXISTS` sets and existing primary, foreign-key, claimable-command, held-lease, and
approval indexes instead of application-side repeated list scans. The current schema has no
general Job-status or Workflow-state/time index; those count partitions can scan their bounded
metadata tables. Expected scale is tens of thousands of Jobs and commands and hundreds of
concurrent or non-terminal rows. The response is O(1) counts plus at most 100 attention values. No
large payload is copied and no derived value is persisted. The live query must remain within the
existing 1.5-second statement timeout. Query-plan evidence is required before adding an index or
claiming a performance improvement; this change has no migration.

The production-shaped read-only probe on 2026-09-15 completed Python startup, both SQL statements,
Pydantic validation, and JSON Schema validation in 0.295 seconds against 11,332 Job rows and 8,836
Workflow-command rows. This is release evidence for the current scale, not a future SLO.

The endpoint runs through the existing authenticated Observability API. Each open console performs
one initial read and then a fixed 10-second refresh with at most one request in flight; ordinary DOM
renders do not initiate queries. The service already limits concurrent authenticated sessions.

## Transaction, retry, and failure behavior

All rows and counts come from one PostgreSQL `REPEATABLE READ, READ ONLY` transaction, so the count
and bounded attention statements observe the same snapshot. A database timeout or unavailable table
produces the existing sanitized Observability error and no partial overview. GET replay is
side-effect free. The caller may retry it; there is no idempotency record because the operation does
not mutate state.

Expired claim classification compares the stored expiry to the database transaction time. It never
releases a lease, reclaims a command, changes a Workflow, or interprets a failed history as success.

## Dependency direction

The JSON Schema and Pydantic models live in `eom_observe_contracts`. An application builder maps the
fixed repository projection to that contract. The PostgreSQL adapter remains in `eom_observe`; the
FastAPI route only authenticates and invokes the builder. No domain or contract package imports
SQLAlchemy, FastAPI, or filesystem code.

## Simpler alternatives considered

Renaming the existing “Active workflows” label would leave command, lease, and stale-claim evidence
invisible. Changing `observe-snapshot/1.0` in place would silently alter a released contract.
Inferring age alone would misclassify long human reviews and paused but valid work. Directly fixing
rows from the console would cross ownership and audit boundaries. The separate, read-only typed
projection is the smallest boundary that makes the distinction explicit without authorizing repair.
