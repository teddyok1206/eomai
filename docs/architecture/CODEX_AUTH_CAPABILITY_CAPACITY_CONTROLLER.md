# Codex Authentication, Capability, and Capacity Controller

Status: Phase 4 source complete; runtime deployment and benchmark remain Phase 5 gates

Last reviewed: 2026-08-23 UTC

## Responsibility and system boundary

The Orchestrator application layer owns sanitized worker readiness and deterministic admission. A
root-owned fixed systemd probe executes `codex login status` under each exact `eom-cdx-0N`
identity. It exposes only a stable exit classification. It never reads, copies, serializes, or
prints credential material. A reviewed capability policy is combined with non-generating CLI
version/help observations and stored as a short-lived immutable capability snapshot.

The capacity controller is ordinary deterministic code. It does not choose educational content,
credentials, model fallbacks, or worker prompts. It acquires Phase 2 leases, reconciles expired
leases against exact fixed-unit activity, and exposes bounded sanitized metrics.

## Canonical source and pointers

- the fixed Linux user and its protected `CODEX_HOME` are the authentication source of truth;
- Codex Auth Health is a TTL projection, not a credential record;
- the root-owned installed Codex executable and reviewed capability policy are the capability
  observation inputs;
- the immutable Resolved Execution Plan fixes requested model and reasoning effort;
- the released Worker Capacity Policy Revision fixes all ceilings;
- a Worker Lease pins plan, workflow, job, step run, slot, binding, attempt, and expiry.

No credential path, token, session, device code, raw `codex` output, full log, or account email is
stored in PostgreSQL, returned by an API, written to Slack, or included in a job manifest.

## Primary access patterns and structures

| Operation | Structure/index | Complexity |
| --- | --- | --- |
| binding by slot | unique indexed `worker_slot_id` | `O(log n)` |
| capability pair membership | normalized unique model/effort entry | `O(log n)` |
| deterministic eligible slots | bounded ordered query over at most five slots | `O(k)`, `k <= 5` |
| pool/global/GPU/analysis count | indexed held-lease counts under pool lock | bounded SQL aggregates |
| one held lease per slot/job | partial unique indexes | constraint-enforced |
| expired lease scan | `(state, expires_at)` B-tree | `O(log n + expired)` |
| event history | append-only `(owner, sequence)` | `O(log n)` |

A second scheduler, in-memory queue, or agent-based allocator is unnecessary at this scale. The
existing indexed job queue remains authoritative; five-slot admission is a deterministic bounded
scan.

## Transaction and concurrency boundary

Auth and capability observations run without a DB transaction, are sanitized, and are then stored
in one short transaction. Lease acquisition locks one capacity-pool row, revalidates the exact
queued job and immutable plan, checks all ceilings, and inserts one lease atomically. No Codex or
systemd call occurs inside that transaction.

Expired reconciliation first changes `ACTIVE -> RECONCILING` transactionally. It then inspects the
exact fixed unit outside the transaction. Only an authoritative absent terminal process permits
`RECONCILING -> EXPIRED`. A running, ambiguous, denied, or unavailable inspection leaves the lease
held and the slot unavailable. This favors temporary under-utilization over concurrent reuse.

## Failure, retry, and idempotency

- auth probe exit `0` is `READY`; the fixed helper's auth-required exit is `AUTH_REQUIRED`; all
  other outcomes are sanitized `DEGRADED` reasons;
- stale TTLs fail admission even if the prior state was `READY`;
- unsupported or unobserved model/effort pairs fail before claim without substitution;
- drain/disable immediately prevents new leases but never interrupts an existing process;
- repeated same-job acquisition returns the same held lease;
- no cross-account retry or implicit next candidate occurs after claim;
- reconciliation never starts, restarts, kills, or resets a worker unit.

## Dependency direction and adapter ownership

`eom_workflow` owns health, capability, policy, and lease contracts.
`eom_orchestrator.worker_auth` and `worker_auth_exec.py` isolate systemd/Codex observation.
`eom_orchestrator.capability_observer` owns reviewed non-generating CLI observation.
`eom_orchestrator.capacity_controller` owns lease application transactions and reconciliation.
The GUI/API added in Phase 5 call these application services and never touch SQLAlchemy, systemd,
worker homes, or credential files.

## Simpler alternative considered

Reading `auth.json` or sharing one root Codex account would make readiness easier to query, but
would collapse identity isolation and expose credential bytes. Treating configured models as
always available would hide account/CLI drift. Counting processes without durable leases would
race after crashes. Fixed-identity status probes, TTL observations, and short durable leases are
the smallest safe design.

## Source validation evidence

The source gate uses no generating Codex call. It proves:

- fixed auth units for all five identities expose only `READY`, `AUTH_REQUIRED`, invalid, or
  timeout constants and discard captured CLI output;
- the reviewed CLI observation retains only an exact semantic version and allowlisted command-line
  option membership;
- expired `READY` observations project as `STALE`, while administrator actions can only produce
  `DRAINING` or `DISABLED`; only a fresh exact-identity probe may restore `READY`;
- PostgreSQL admission enforces three global leases, one lease per slot, one GPU lease, and one
  knowledge-analysis lease under the released policy lock;
- an auth failure after claim never interrupts or releases the existing lease;
- expired leases enter `RECONCILING` and remain held across controller restart until the exact
  fixed unit is authoritatively absent;
- queue, failure, lease-state, held-resource, and oldest-duration metrics contain counts and
  durations only, never credentials, raw CLI output, paths, prompts, or item content.

The final disposable PostgreSQL migration cycle and integration matrix passed on 2026-08-23 UTC.
The initial runtime policy remains five configured identities and at most three active processes.
The non-generating three-slot host/service latency benchmark is intentionally executed only after
the reviewed fixed units and application release are installed together in Phase 5; source
completion does not claim that deployment evidence.
