# ADR 0081: release a deployment hold from the terminal retirement successor

## Status

Accepted.

## Context and responsibility

The mock-exam retirement service pins and signs the checkpoint observed before it atomically
fences the cohort. Cancellation commands are then consumed by the Workflow runner. A final
`advance-items` pass records those terminal Workflow states in a new immutable execution
checkpoint. Deployment admission correctly rejects the pre-cancellation checkpoint and requires
that terminal successor. The hold-release verifier previously required `current.json` to remain
the retired checkpoint, making the two safety gates mutually exclusive.

This change belongs to the privileged deployment hold verifier. It does not change the retirement
wire contract, coordinator state machine, Workflow persistence, or NAS artifacts.

## Decision

The retirement receipt remains authoritative for the exact retired checkpoint. While holding the
per-execution checkpoint lock, the verifier resolves three bounded files by immutable revision ID:

1. `current.json`;
2. the immutable revision named by `current.json`; and
3. the immutable retired revision named by the signed receipt and command-line pins.

The receipt, cohort, dispositions, and command self-hash are checked against the retired immutable
revision. Hold release then accepts either that same revision (the interrupted pre-admission
recovery case) or exactly one immediate successor. A successor must be terminal, preserve all
execution-level pins and all item-run pointers, preserve already-checkpointed failures byte for
byte, and only terminalize the remaining rows with non-retryable Workflow-execution failures. Its
checkpoint time must not predate retirement.

## Data structures and access patterns

Checkpoint and outcome rows are indexed in three position-keyed maps for O(n) identity and
membership checks; `n` is fixed at 25. Immutable output order remains the contract tuple order.
The verifier reads at most three checkpoint payloads, each bounded to 2 MiB, so time and space are
O(n + bytes) with constant cohort size. No derived value is persisted.

## Transactions, concurrency, and failure behavior

The existing flock on the execution checkpoint lock spans all reads, validation, and the privileged
hold mutation handshake. Any missing revision, unsafe file metadata, hash/schema mismatch,
nonterminal successor, skipped revision, pointer drift, or retryable row fails closed before the
hold changes. After the receipt and current checkpoint pass, the verifier emits a fresh UTC journal
lower bound while it still owns that lock. The systemd adapter proves the stopped hold identity and
rejects any unit journal event after that cursor. Historical runner activity needed to consume the
retirement cancellations is therefore accounted for by the terminal successor instead of making
release impossible. Release remains idempotent through the existing exact receipt and systemd
checks.

## Dependency direction and alternatives

The deployment interface imports only installed API contracts and identifier value objects. It
does not query application tables or reach into infrastructure adapters. Rewriting the retirement
receipt after cancellation was rejected because Workflow history permits only the original exact
retirement identity. Directly editing `current.json`, ignoring deployment admission, or accepting an
arbitrary later terminal checkpoint would weaken immutable history and recovery safety.
