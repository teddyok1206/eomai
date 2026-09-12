# ADR 0061: Recover workflow-role jobs before worker execution

Status: Accepted

Date: 2026-09-12

## Responsibility and boundary

The Orchestrator owns creation and execution of one durable workflow-role Job. A runner process can
stop after the Job row is committed but before it reaches the executable `QUEUED` state. Replaying
the same workflow command must resume that exact Job instead of leaving `CREATED` or `VALIDATED`
forever. This recovery never starts a second Job, changes a Workflow attempt, or lets a worker write
PostgreSQL or NAS.

## Canonical source, identity, and pointers

The canonical source is the existing `jobs` row selected by its unique idempotency key. Its Job ID,
logical Artifact ID, Artifact Revision ID, request document, request hash, and protocol version are
immutable. Before any replay, the Orchestrator compares the caller's workflow/step/attempt/role,
typed worker request, ordered upstream Artifact pointers, result-schema protocol, task type, and the
stored canonical request hash. A mismatch is an idempotency conflict; it is never repaired or
silently rebound.

## Access patterns and data structures

Replay is one indexed lookup by the existing unique idempotency key followed by one primary-key row
lock. Ordered upstream pointers remain an immutable tuple. Exact request comparison is linear in the
small bounded worker input and upstream pointer list; persistent lookup and transition work are
`O(log n + 1)` and use no scan, cache, or new table.

## State and transaction boundary

One short transaction locks the Job and advances only these pre-execution states:

```text
CREATED -> VALIDATED -> QUEUED
VALIDATED -> QUEUED
```

If a concurrent owner has already advanced the row, the locked current state wins and recovery does
nothing. `QUEUED` then follows the existing claim path. `RUNNING` and `VALIDATING_RESULT` continue to
use the completed fixed-worker recovery defined by ADR 0048. `COMMITTING` is not moved backward:
recovering it requires the original manifest timestamp and an exact NAS/DB publication receipt and
remains a separate protocol. A `CLAIMED` row also remains fail-closed because workspace and capacity
materialization may have begun even though no result is yet authoritative.

## Failure, retry, and idempotency

Only a byte-semantically identical typed request can resume. Validation runs before state mutation.
Repeated recovery is idempotent because the row lock observes `QUEUED` after the first successful
advance. A malformed stored request, hash mismatch, pointer drift, different result protocol, or
terminal Job with a different replay input fails without worker execution or NAS access.

## Dependency direction

The Orchestrator application service owns replay validation and transaction boundaries. The Job
state machine owns legal transitions; the repository owns indexed persistence. Workflow Runner only
replays the already fenced command, and the worker adapter remains unaware of database state.

## Simpler alternative and why it is insufficient

Returning every existing nonterminal Job is simpler, but permanently strands `CREATED` and
`VALIDATED` after a process loss. Creating a replacement Job loses immutable identity and can run a
duplicate worker. Retrying without exact request and pointer comparison can bind the old Job to new
inputs. The selected change extends the existing state machine only at the two unambiguous
pre-execution boundaries.

