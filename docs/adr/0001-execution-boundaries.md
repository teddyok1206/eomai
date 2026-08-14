# ADR 0001: Execution Boundaries

Status: Accepted

## Context

EOM uses Codex workers for one-shot tasks. Worker accounts carry subscription-specific state and must be isolated from each other and from root.

## Decision

- Codex workers never run as root.
- Each Codex account maps to a separate Linux user.
- Each worker has a separate HOME and `.codex` directory.
- Worker execution is one-shot `codex exec`, not a long-lived TUI backend.
- Workers do not communicate directly with each other.
- The orchestrator is the only coordination path.
- Global Codex concurrency starts at 3.
- GPU concurrency starts at 1.
- The test control terminal is future `eomctl`, not another Codex account.

## Consequences

The orchestrator must stage inputs locally, launch a bounded worker process, validate structured output, and collect results. Account login is an operations task performed per worker user. Root Codex auth is never copied.
