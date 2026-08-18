# ADR 0030: Workflow Pre-Claim Execution Readiness

## Status

Accepted

## Decision

Before claiming a workflow command, the runner performs a read-only pending-work query and a typed,
non-destructive execution readiness check. Only a ready runtime proceeds to the existing locked
claim. The runner and doctor share the same readiness implementation.

## Consequences

Broken Catalog wiring, staging permissions, account group snapshots, workspaces, launch binaries,
schemas, or definitions do not consume an attempt or terminal-fail a workflow. Readiness adds a
small bounded check for five workers before a command claim. It invokes no worker and reads no
credential. A real execution failure after claim retains the existing domain behavior.
