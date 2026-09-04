# ADR 0048: Recover completed fixed-worker results after runner loss

Status: Accepted

Date: 2026-09-04

## Responsibility and boundary

The Workflow Runner synchronously waits for a fixed systemd worker. A service restart can remove
the waiting runner process after the worker has atomically written `result.json` but before the
Orchestrator advances the durable Job from `RUNNING`. Recovery belongs to the existing Orchestrator
submission boundary: it validates and commits the retained result without starting another worker.

## Canonical source, revisions, and pointers

The durable Job request remains canonical for job, workflow, step-run, attempt, role, result-schema,
logical Artifact, and Artifact Revision identities. The only recoverable payload is the exact
`result.json` in that Job's fixed private workspace. Normal schema/Pydantic validation, request
identity comparison, Artifact staging, NAS commit, and immutable registry writes remain unchanged.

## Access patterns and data structures

Recovery uses indexed key lookup by the existing idempotency key and the partial unique held-lease
index by Job. Workspace lookup is one deterministic path keyed by worker slot and Job ID. No scans,
queues, caches, or duplicate payloads are introduced; time and space are O(1) apart from the existing
bounded result validation and Artifact commit.

## Resolution and trust checks

Recovery requires a Job in `RUNNING` or `VALIDATING_RESULT`, its already-bound worker slot, an exact
inactive fixed unit, the private workspace and Orchestrator staging directory with their expected
owners/groups/modes, and a single-link regular result of at most 1 MiB owned by the fixed worker.
An active or indeterminate unit is never recovered. The existing result validator then rechecks all
protocol identifiers and content constraints before the Orchestrator writes NAS or PostgreSQL.

## Transactions, concurrency, failure, and idempotency

The Job idempotency key prevents creation of a second Job or worker attempt. Recovery re-enters only
the uncommitted validation path. Normal row locks and state transitions serialize concurrent
reconcilers. A held capacity lease for the exact workflow/job/attempt/slot is released only after the
same terminal handling used by a normal worker return. `COMMITTING` is deliberately excluded because
NAS publication may already have happened and requires a separate commit-reconciliation protocol.
Missing, active, malformed, or identity-mismatched state fails closed without another model call.

## Dependency direction and ownership

The worker adapter owns fixed-unit/workspace observation. The Orchestrator application service owns
recovery, validation, and Artifact commit. The Workflow Runner only invokes its existing reconcile
use case. Workers still cannot access PostgreSQL or NAS, and only the Orchestrator commits artifacts.

## Simpler alternative

Waiting for the two-hour command lease or editing Job rows directly is insufficient: waiting would
turn a valid retained result into a false failure, while direct SQL would bypass schema validation,
Artifact provenance, lifecycle events, and capacity release. Re-running the worker would waste model
usage and violate the one-attempt contract.

