# ADR 0050: Capacity-queued workflow reconciliation

## Status

Accepted.

## Responsibility and boundary

The workflow runner must yield when an orchestrator job remains `QUEUED`. An explicit admin
reconciliation may resume a workflow that was incorrectly marked `FAILED` before that same job
crossed the worker-execution boundary. This does not add an automatic retry or a new worker attempt.

## Canonical source and identity

PostgreSQL workflow, step, job, job-event, lease, and artifact rows are canonical. Recovery retains
the exact workflow ID, step-run ID, attempt, job ID, request hash, immutable upstream pointers, and
workflow-definition snapshot. If prompt preparation already completed, reconciliation resolves the
exact prompt artifact revision, manifest hash, prompt hash, and canonical envelope already pinned to
that step attempt. It never renders or commits a replacement prompt. A filesystem path is not used
as identity.

## Access patterns and structures

The dominant operations are indexed primary-key lookups and append-only event iteration ordered by
`(job_id, sequence)`. Membership checks use exact scalar identities; no repeated corpus scan or
large payload copy is introduced. The operation is constant in workflow size apart from the short
event history of the one queued job.

## Transaction and concurrency boundary

Recovery locks the workflow, failed step, and queued job in one transaction. It is accepted only
when the job has exactly `JOB_CREATED -> REQUEST_VALIDATED -> JOB_QUEUED`, no slot, worker output,
terminal fields, lease, or artifact, and no competing workflow command. The normal orchestrator
idempotency key then continues that same job. Concurrent or stale commands fail explicitly.
Prompt bytes are read only after the database pointer, approved lifecycle, file-set manifest, and
runtime-context binding agree. Both small members are read through bounded `O_NOFOLLOW` descriptors
and checked for stable file identity and exact hashes.

## Failure, retry, and idempotency

`QUEUED` causes the current advancement command to finish and schedules one delayed idempotent
advance command. Admin reconciliation of the narrow pre-execution failure is idempotent at the job
identity boundary. A job that was claimed, leased, run, failed, or committed is never resurrected;
such a failure requires a separately modeled successor attempt.

## Dependency direction and alternatives

The workflow application service reads orchestrator job/lease/artifact evidence and invokes its
existing executor; workers remain unaware and cannot persist. The simpler alternative—starting a
new workflow—would consume authoring again and lose the exact upstream provenance. Mutating a failed
job or silently retrying it would erase history and is rejected.
