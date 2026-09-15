# ADR 0091: Fence transient shared-runtime consumers before API installation

Status: Accepted

Date: 2026-09-15

## Context and responsibility

The Application API release owns three wheels installed into the shared `eom-api` Conda
environment. Static API, Catalog, Workflow, maintenance, and HWPX application services consume
that environment and are restarted by `deploy_release.sh` after installation.

Operational backfills can also create transient Workflow runner units. Those units execute the
same installed entry point but are not members of the static restart array. Replacing shared wheel
files while one remains active can leave an old in-memory process, or a process that lazily imports
new bytes after installation. Neither state has one reproducible source identity.

This release fence owns discovery only. The Workflow operation that created a transient unit owns
its quiescence and stop decision.

## Canonical source and identity

The canonical release identity remains the Git commit, tree/archive, wheel hashes, distribution
`RECORD` files, and installed build information. A systemd unit name is discovery metadata, not the
runtime identity and not a replacement for these hashes.

The current bounded transient consumer family is `eom-workflow-runner-*.service`. The static
`eom-workflow-runner.service` is intentionally excluded and remains in the reviewed restart list.

## Access pattern and data structure

Installation performs one ordered scan of active systemd services for each explicit bounded
pattern, collects matching unit names in a shell array, and tests whether the array is empty. For
`u` active matching units the time and space cost are `O(u)`. There is no repeated database scan,
new cache, persistent derived state, or new index.

## Transaction and concurrency boundary

The fence runs after the release build and the second deployment-admission check, immediately
before the first installed wheel is replaced. Any active match aborts installation before shared
runtime bytes change.

The check does not stop a unit automatically. An operator must first prove that its jobs, commands,
and leases are quiescent, stop the exact transient unit through the operational boundary that owns
it, and rerun installation. The existing post-install restart and health checks continue to own the
static services.

## Dependency direction

The release shell queries systemd as an infrastructure adapter. No domain, contract, worker, or
application module imports systemd behavior. No wire schema or database migration is required.

## Failure, retry, and idempotency

An active transient consumer produces a stable pre-install failure with the exact unit names. At
that point no wheel has been replaced, so retry is safe after an explicit quiescence/stop decision.
The fence does not alter Workflow, Job, lease, Artifact, or systemd state.

## Simpler alternative considered

Ignoring transient units and restarting only the static array is simpler but does not produce one
runtime identity. Automatically restarting every wildcard match is also insufficient because a
transient backfill has an operation-specific lifecycle and may not be safe or necessary to resume.
Failing before installation is the smallest extension of the existing release boundary.
