# Bounded Workflow Runner Scale-Out v1

## Responsibility and boundary

The workflow runner may be materialized as two identical service processes while the legacy
corpus campaign is active. Both processes consume the same durable workflow-command queue; they
do not communicate directly. PostgreSQL command claims and worker-capacity leases remain the
orchestrator-owned concurrency boundary.

## Canonical source and identity

`infra/systemd/eom-workflow-runner.service` remains the sole canonical unit definition. A second
runtime unit is an exact, SHA-256-verified materialization under a distinct systemd unit name. It
uses the same installed release and configuration. The runtime copy is removed when the campaign
ends or before a release deployment.

Workflow IDs, command IDs, step-run IDs, job IDs, lease IDs, Artifact identities, immutable
revisions, and content hashes remain separate. No new persistent entity or implicit latest-pointer
resolution is introduced.

## Access patterns and data structures

The dominant operations are FIFO command claim, concurrent membership/uniqueness checks, and
append-only event recording. Commands continue to use the indexed PostgreSQL queue ordered by
`available_at`, `created_at`, and `command_id`. `FOR UPDATE SKIP LOCKED` provides an O(log n)
indexed claim followed by constant-size row locking. Unique constraints and partial unique worker
lease indexes prevent duplicate command execution and duplicate slot/job ownership.

## Scale and capacity

The current knowledge-analysis policy has two support slots, 05 and 06, a support-pool maximum of
two, a knowledge-analysis maximum of two, and a global Codex maximum of three. Two runner processes
allow two independently claimed support commands to reach those two slots concurrently. The
existing global and per-pool `max_active` values remain authoritative; adding runner processes
cannot create capacity beyond those limits. Other campaigns may share the support pool, so the
capacity controller rather than the process count remains the final admission boundary. Expected
additional memory is about one runner process (well below the existing service and host limits).

## Transaction and concurrency boundary

Each runner has a unique generated runner ID. Command claims occur in transactions with
`SKIP LOCKED`; command leases, step idempotency keys, job idempotency keys, and worker leases
provide replay and crash recovery. Shared staging roots contain job-keyed materializations and do
not become canonical storage. Only the orchestrator commits validated artifacts to NAS.

## Dependency direction and ownership

The scale-out changes only the infrastructure process count. Interfaces still call application
services, workflow state machines own transitions, and infrastructure adapters own PostgreSQL,
systemd, filesystem, and NAS behavior. Worker isolation and the no-worker-to-worker rule are
unchanged.

## Failure, retry, and idempotency

If one runner exits, its command becomes reclaimable after the existing lease. A second runner
cannot claim the same live command. Terminal failures remain immutable; corpus retry uses fresh
work-unit and workflow identities. The corpus watchdog stops Catalog on repeated equal failure
signatures or a bounded accumulation of isolated failures, preventing a systemic cascade.

## Deployment and rollback

Release deployment must stop the runtime accelerator before replacing installed code, then may
re-materialize it from the newly verified canonical unit. Rollback is immediate: stop and remove
the accelerator runtime unit and continue with the canonical single runner. Existing commands,
jobs, and leases remain durable.

The only supported operator path is `scripts/workflow/manage_runner_scale_out.py`. It pins the
exact installed canonical unit SHA-256, publishes the runtime unit with no-replace semantics, and
accepts an existing target only when its bytes and metadata are exact. `start` requires the base
runner to be active, healthy, restart-free, and free of drop-ins. `stop` first stops the accelerator
and removes only the exact reviewed runtime unit. Both transitions reload systemd and independently
verify the final unit state. The accelerator name remains inside the shared-runtime deployment
fence pattern, so a release fails closed until it is stopped and removed.

Release installation also rejects the inactive runtime unit path. Merely stopping the accelerator
is insufficient: the exact staged copy must be removed before shared runtime bytes change. This
prevents an older inactive unit from being adopted after a later deployment.

An exact runtime unit may be present while inactive. The manager reports this explicitly as
`STAGED` or, before a manager reload, `STAGED_UNLOADED`; it neither treats staged bytes as an active
consumer nor overwrites them. `start` may adopt those exact bytes, while any hash, metadata, path,
drop-in, or service-state mismatch fails closed.

## Simpler alternative

A single runner is simpler but serializes long support commands and leaves one authenticated
support slot idle for minutes per Item when two eligible commands are queued. Increasing queue
polling or host resources cannot remove that blocking call. Two bounded consumers are the smallest
change that uses the concurrency and idempotency mechanisms already present.

## Verification

- canonical and runtime unit bytes have identical SHA-256 values;
- both runner services are active under the same non-root identity and sandbox;
- slot 05 and slot 06 can be active concurrently;
- database counts stay within the pinned global, knowledge-analysis, and support-pool maxima and
  never expose duplicate commands, Jobs, leases, or accepted successors;
- watchdog, API, GUI, Catalog, and non-target listener health remain active;
- removal of the accelerator returns operation to the original single-runner topology.
