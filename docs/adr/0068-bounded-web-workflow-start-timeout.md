# ADR 0068: Bounded Web workflow-start timeout

## Status

Accepted.

## Context and responsibility

The Web GUI is an HTTP adapter over the Application API. Ordinary reads and short mutations need a
small failure-detection bound, but `POST /api/v1/workflows` may synchronously resolve and publish a
pinned Graph evidence bundle before the Workflow and its resolved execution plan are committed. A
production request took 10.67 seconds while the Web adapter applied its common five-second timeout;
the API returned `202` and committed exactly one Workflow, but the browser received the misleading
`APPLICATION_API_UNAVAILABLE` result.

The Application API remains the canonical owner of idempotency, Workflow identity, the immutable
resolved plan, and transaction boundaries. The Web session stores only the small typed command
result. No artifact bytes or new persistent cache are introduced.

## Decision

Keep the common Application API timeout at five seconds and add one explicit
`workflow_start_timeout_seconds` setting, defaulting to 150 seconds and bounded to 30–165 seconds.
Only `start_workflow` passes that override through the authorized HTTP adapter, including its single
access-token refresh replay. Every other operation keeps the common client timeout.

The upper bound stays below the Application API's 180-second idempotency claim lease, while allowing
the Catalog evidence operations' bounded 120-second response-idle timeout plus normal local
validation and commit overhead. API idempotency remains authoritative: a repeated request must use
the same key and body, and no Web-side identity is invented.

## Access patterns and complexity

Timeout selection is a constant-time lookup at the operation boundary and has constant memory cost.
There is no list scan, new index, database migration, queue, or graph traversal. Concurrent claims,
retry ownership, and stale completion rejection remain inside the Application API's existing
idempotency state machine.

## Failure and verification

Connect and transport failures still map to the stable `APPLICATION_API_UNAVAILABLE` code. A bounded
workflow-start timeout can still produce an unknown client outcome, so callers must preserve the
same idempotency key rather than create a second request. Tests assert that workflow start receives
the extended timeout, token refresh preserves it, and ordinary requests retain the common timeout.
