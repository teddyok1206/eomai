# ADR 0083: Bounded pre-commit agent-attempt retry

## Status

Accepted for implementation.

## Context and responsibility

The workflow definition contract already publishes `limits.max_step_attempts`, but the runtime used
that limit only for human-requested rework. A transient worker execution failure or a structurally
invalid worker result therefore made the whole Workflow terminal on its first attempt. A 25-Item
production occurrence could be lost because one model response misspelled an Evidence anchor even
though no Artifact had been committed.

The workflow runner owns attempt scheduling and Workflow state. The orchestrator remains the only
component that validates worker results and commits validated Artifacts to NAS. This change does not
add or modify an agent message: every attempt continues to use the released role JSON Schema and
Pydantic model already pinned by the Workflow definition.

## Decision

An agent step may schedule another attempt only when all of these conditions hold:

1. the platform job returned a failed result with one of the explicitly retryable pre-commit codes
   `WORKER_UNAVAILABLE`, `WORKER_TIMEOUT`, `WORKER_EXEC_FAILED`, `WORKER_RESULT_MISSING`, or
   `WORKER_RESULT_INVALID`;
2. no Artifact row exists and the Job event history has never entered `COMMITTING` or `SUCCEEDED`
   for that exact platform job;
3. no `ACTIVE` or `RECONCILING` worker lease remains for the Job;
4. the current attempt is below the immutable Workflow definition's `max_step_attempts` limit; and
5. the current Workflow and step are still the command-fenced `RUNNING` occurrence.

The failed step records its stable error and remains `FAILED`; its
`superseded_by_step_run_id` points to the successor so audit queries do not rewrite the historical
outcome. The runner creates one new `READY` step run with a monotonically increasing attempt number
and the same pinned upstream Artifact pointers. It appends one `STEP_RETRY_SCHEDULED` Workflow event
and enqueues one idempotent `ADVANCE_WORKFLOW` command derived from Workflow ID, step key, failed job
ID, and the new attempt. The current command can then finish; it never executes two attempts inside
one command lease.

The final allowed attempt retains existing behavior and makes the Workflow terminal `FAILED`.
Exceptions raised after a worker result succeeds, Artifact commit failures, hash mismatches,
database/NAS failures, and Catalog registration failures are never retried by this rule because
their side-effect outcome may be ambiguous. No failed output is repaired, accepted, or copied into
the next attempt.

## Canonical source and revision model

The immutable Workflow definition revision is the canonical retry limit. A Workflow is the logical
entity; each `WorkflowStepRunRecord` is an immutable numbered attempt except for its explicit state
transition and error fields. Validated Artifact identity remains
`logical artifact -> immutable revision -> content hash`. Failed attempts have no Artifact pointer.

## Access patterns and data structures

- Current Workflow, step, job, and Artifact evidence use primary-key or indexed equality lookup.
- Attempt allocation uses the existing indexed `(workflow_id, step_key)` maximum and unique attempt
  constraint.
- Supersession and event history are append/monotonic operations.
- Retry code membership is a frozen set, O(1) expected time and O(1) bounded space.

At current scale each decision is O(1), aside from the existing indexed maximum-attempt lookup.
No large result bytes or arbitrary dictionaries are persisted.

## Transaction, concurrency, retry, and idempotency

The failed-attempt transition, Artifact absence check, successor attempt creation, Workflow event,
and successor command enqueue occur in one command-fenced database transaction. The command lease
and row locks prevent two runners from allocating the same successor. The successor command's
stable idempotency key prevents duplicate scheduling on command replay. A crash commits either the
whole retry schedule or none of it.

## Dependency direction

The workflow runner applies the policy using the existing workflow-domain state machine and
repository functions. It consumes only the orchestrator's typed execution outcome and does not
reach into worker workspaces or NAS. Interfaces, Catalog, and workers gain no orchestration logic.

## Failure behavior

Missing job identity, existing Artifact or commit-boundary evidence, an active lease, exhausted
attempts, an unsupported error code, or any state/concurrency mismatch fails closed through the
existing terminal Workflow path. Tests cover one retryable pre-commit failure, exhausted attempts,
non-retryable failure, committed Artifact evidence, commit-boundary entry without an Artifact,
idempotent successor command creation, and preserved prior attempt history.

## Simpler alternative rejected

Restarting an entire 25-Item production occurrence is operationally simple but discards up to 24
valid Workflows and makes success probability shrink with cohort size. Silently repairing a worker
result would falsify the worker's Evidence attestation. A bounded, immutable successor attempt is
the smallest boundary that preserves both auditability and useful production reliability.
