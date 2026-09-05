# Codex Slot Usage Observation V1

Status: implemented

Date: 2026-09-05 UTC

## Responsibility and boundary

Scientific Studio administrators may refresh and view the sanitized Codex allowance for one fixed
worker slot. The Application API enqueues the existing `OBSERVE` command, the orchestrator owns the
use case, and a fixed systemd unit runs Codex App Server as that slot's Linux identity. Neither the
browser, API, nor orchestrator reads a worker's authentication files.

## Canonical source and identity

OpenAI Codex App Server's `account/rateLimits/read` response is the transient canonical source.
The durable EOM value is an immutable observation embedded in the terminal control-command result.
The existing command ID, binding ID, and slot key identify which explicit operator refresh produced
the observation; this small value object has no independent logical-revision lifecycle.

## Pointers and resolution checks

The command pins one binding and expected binding resource version. Resolution verifies the fixed
slot record, fixed Linux identity, root-owned Codex executable and unit, authenticated ChatGPT
account type, bounded App Server response, JSON-RPC request IDs, UTC timestamps, percentage range,
and self-hash. Account email, tokens, credits, raw JSON-RPC, and authentication paths are discarded.

## Access patterns and structures

The dominant operations are keyed lookup by binding ID, FIFO command claim, and latest successful
observation per binding. PostgreSQL's existing command queue is append-only after terminalization;
a partial B-tree index on successful OBSERVE commands supports the latest lookup. In memory, rate
limit windows are a sorted immutable tuple and are deduplicated with a set keyed by limit ID and
window kind. With at most six slots and a bounded 32 windows per response, parsing is O(w) time and
O(w) space; latest lookup is O(log n).

## Transaction, concurrency, and idempotency

The existing idempotency key prevents duplicate operator commands. App Server execution happens
outside a database transaction. Terminal persistence locks the exact command and binding version.
An active worker lease makes usage refresh fail closed so the account session is not shared with a
generation process. Conversely, a non-expired `PROCESSING` OBSERVE command reserves its binding
from lease acquisition until its four-minute command claim expires. That claim covers the bounded
auth and App Server probes without creating a second lock service. The fixed systemd instance and
O_EXCL handoff prevent duplicate observations.

## Dependency direction and ownership

JSON Schema and frozen models live in `eom_workflow`. The orchestrator owns command processing and
the systemd adapter. The Application API exposes only typed projections. Scientific Studio renders
percentages and reset times and contains no usage business rules. Codex/stdin/systemd/filesystem
behavior stays in infrastructure adapters and never enters domain models.

## Failure, retry, and freshness

Malformed, oversized, unauthenticated, timed-out, or lingering App Server sessions produce stable
error codes and do not overwrite the last successful observation. A command may follow the existing
bounded queue retry policy, while the systemd handoff remains per-command and idempotent. The UI
shows the observation timestamp and treats the value as a snapshot; clicking refresh creates a new
command. Reset timestamps are UTC in storage and Asia/Seoul only in the UI.

## Alternatives

Calling an undocumented HTTP endpoint from the browser would expose account context and couple the
UI to an unstable response. Reading authentication files in the API would violate slot isolation.
A second usage service and table would duplicate the existing command/result lifecycle. Reusing the
supported App Server protocol and OBSERVE result is the smallest implementation that preserves the
current control-plane boundaries.
