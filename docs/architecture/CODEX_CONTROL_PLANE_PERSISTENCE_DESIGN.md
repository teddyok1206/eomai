# Codex Control Plane Persistence Design

Status: Phase 2 implementation design

Contract baseline: `0d46db802b4a044aa31d38ec62cf84f07d2c44bd`

Last reviewed: 2026-08-23 UTC

## 1. Responsibility and boundary

The Orchestrator owns persistence for reviewed Execution Presets, Instruction/Reference Bundles,
Resolved Execution Plans, sanitized Codex authentication bindings and observations, capability
snapshots, capacity policies, and short-lived worker leases. The workflow runner requests a plan
and the Orchestrator resolves/adopts it; workers never read or write these tables directly.

This design extends the existing `eom_orchestrator` model and transaction boundary. It does not
create a parallel scheduler, prompt registry, credential service, graph store, or worker registry.
The fixed `/etc/eom/worker-slots.yaml` inventory continues to populate `worker_slots`; capacity
records add transactional admission around those fixed identities.

Credential bytes, credential paths, Codex session IDs, full prompts, reference Markdown, and other
large payloads are outside this boundary. Authentication remains in each fixed worker identity's
private Codex credential store. This database stores only a reviewed non-secret account label and
sanitized health observations.

## 2. Canonical source and revision model

The canonical small control documents are the JSON Schema/Pydantic contracts from
[`CODEX_KNOWLEDGE_PROTOCOL_COMPATIBILITY.md`](CODEX_KNOWLEDGE_PROTOCOL_COMPATIBILITY.md). Their
canonical serialization and SHA-256 are persisted only after validation.

```text
ExecutionPreset
  -> immutable ExecutionPresetRevision
      -> role policy rows
          -> immutable Instruction Bundle Revision
          -> optional immutable Reference Bundle Revision
      -> immutable Capacity Policy Revision

ExecutionBundle (kind=INSTRUCTION | REFERENCE)
  -> immutable ExecutionBundleRevision
      -> approved manifest Artifact Revision
          -> bounded Markdown component pointers

WorkerCapacityPolicy
  -> immutable WorkerCapacityPolicyRevision
      -> bounded pools -> roles + fixed worker slots

WorkflowInstance
  -> exactly one immutable ResolvedExecutionPlan
      -> immutable step projections
      -> all exact revisions and hashes above

WorkerSlot
  -> sanitized CodexAuthBinding current projection
      -> append-only health events
      -> immutable capability snapshots and model/effort entries
  -> short-lived WorkerLease -> append-only lease events
```

Mutable logical rows contain only lifecycle and a `current_revision_id`. Historical workflows and
leases always pin revision IDs and never follow that mutable pointer.

## 3. Required pointers and resolution checks

Before releasing a Bundle Revision, the service validates the manifest Artifact and Artifact
Revision exist, belong together, are approved, match schema/media/logical member requirements, and
match the expected SHA-256. Bundle bytes remain in the Artifact store.

Before releasing a Preset Revision, every role policy resolves the exact Instruction and optional
Reference Bundle Revision and the Capacity Policy Revision. All must be released and the role,
bundle kind, protocol compatibility, model policy, and content hash must agree with the canonical
document.

Before inserting a Resolved Execution Plan, the service validates the Workflow Instance,
definition hash, Content Pack Release, Preset Revision, Bundle Revisions, Capacity Policy Revision,
optional Graph/Evidence pair, and plan hash. Plan rows are immutable and unique per workflow.

Before acquiring a lease, the service validates the fixed slot is enabled, its binding health is
`READY` and unexpired, a compatible unexpired capability snapshot contains the exact model/effort,
and the selected slot belongs to the exact capacity-policy pool. No check resolves an implicit
latest revision.

## 4. Primary access patterns and structures

| Access pattern | Structure/index | Expected cost |
| --- | --- | --- |
| logical preset/bundle/policy by key | unique B-tree key | O(log n) |
| exact immutable revision | primary key | O(log n) |
| revision history | unique `(logical_id, revision_number)` | O(log n + k) |
| preset role policy | primary key `(preset_revision_id, role)` | O(log n) |
| plan by workflow | unique `workflow_id` | O(log n) |
| plan step by key | primary key `(plan_id, step_key)` | O(log n) |
| current binding by fixed slot | unique `worker_slot_id` | O(log n) |
| usable capability | `(binding_id, valid_until)` snapshot index plus entry key | O(log n) |
| deterministic eligible slots | bounded five-row ordered query | O(5), intentionally no heap |
| global/pool admission | lock exact Capacity Policy Revision, indexed held-lease count | O(log n + 5) |
| one held lease per slot/job | partial unique indexes | constraint-enforced |
| expired lease reconciliation | partial index `(expires_at, lease_id)` | O(log n + k) |
| event history | unique `(owner_id, sequence)` | O(log n + k) |

Preset role policies and resolved plan steps are bounded keyed collections. Model candidates remain
an ordered typed JSON value of at most four entries because order is semantically meaningful and
the only query is whole-policy retrieval; decomposing four values into a mutable table adds joins
without a real access pattern. Capability membership is decomposed into rows because it is queried
at every claim.

## 5. Physical records and indexes

The Phase 2 migration adds:

- `execution_bundles` and `execution_bundle_revisions`;
- `worker_capacity_policies`, `worker_capacity_policy_revisions`, `worker_capacity_pools`,
  `worker_capacity_pool_roles`, and `worker_capacity_pool_slots`;
- `execution_presets`, `execution_preset_revisions`, and `execution_preset_role_policies`;
- `resolved_execution_plans` and `resolved_execution_plan_steps`;
- `codex_auth_bindings` and append-only `codex_auth_health_events`;
- `codex_capability_snapshots` and `codex_capability_entries`;
- `worker_leases` and append-only `worker_lease_events`.

Foreign keys enforce local identity. Partial unique indexes cover lease states `ACTIVE` and
`RECONCILING`, because both states reserve capacity. Check constraints close state, role,
reasoning-effort, bundle-kind, workload-class, timestamp, and host-limit vocabularies. Artifact
pointer relationship and hash consistency remain application validations because the existing
Artifact Revision table has a revision primary key rather than a composite artifact/revision key.

Canonical typed documents are small JSONB snapshots, not arbitrary dictionaries. Their declared
hash is the canonical serialization of the document with that one hash field omitted, avoiding a
self-referential digest. They provide byte-reproducible historical input and are protected by
schema validation, SHA-256, size bounds, and database immutability triggers. Normalized
role/step/capability/pool rows provide pointer FKs and indexed access. Binary or Markdown bytes
never enter these rows.

## 6. Scale, time, and space

The configured host has five worker slots and at most three active Codex jobs. Capacity and
eligibility scans are therefore strictly bounded. Preset, Bundle, and Policy revisions are expected
to grow by tens or hundreds per year; plans, leases, observations, and events grow with workflows.
All history queries are keyset/index ordered, and no claim path scans unbounded JSON.

Each canonical document is bounded by its schema (five role policies, 64 resolved steps, 256
Reference entries). Large reference data remains in Artifact Revisions. Event payloads contain
only stable IDs and reason codes. Phase 12 measurements must verify index use and row growth before
any retention or partitioning is introduced.

## 7. Transaction and concurrency boundary

Revision creation validates the typed document and inserts its normalized rows in one transaction.
A revision's state is part of its hashed immutable content. Releasing or deprecating a draft
therefore creates a new revision ID/number rather than mutating the draft. Publication locks and
revalidates the exact `RELEASED` revision, then atomically updates only the logical current pointer.
Revision content and state columns are never changed.

Workflow creation/resolution locks the Workflow Instance as needed and inserts exactly one plan;
idempotent replay with the same plan hash returns it, while a different hash is a conflict.

Lease acquisition is a short database transaction:

1. lock the exact released Capacity Policy Revision row;
2. select at most five eligible fixed slots in deterministic `slot_id` order;
3. check global, pool, GPU, knowledge-analysis, per-slot, and per-job held counts;
4. insert one `ACTIVE` lease and event;
5. commit before systemd/Codex execution.

No external process, filesystem materialization, Artifact commit, or Codex call runs inside the
transaction. A uniqueness race returns a stable capacity conflict rather than selecting a second
slot. Release/reconciliation locks the lease, verifies exact unit/process evidence in the adapter,
records terminal state/reason, and appends one event transactionally.

## 8. Dependency direction and adapter ownership

`eom_workflow` and `eom_catalog_contracts` contain immutable DTOs only. SQLAlchemy records and
repositories live in `eom_orchestrator`. The application service owns release, resolution,
admission, idempotency, and transaction boundaries. A later systemd adapter supplies exact process
state; a later Codex observation adapter supplies sanitized auth/capability results. Neither adapter
contains business rules.

Application API, CLI, and GUI will call application use cases and never update these tables
directly. Workers receive only their resolved job-local plan and staged files.

## 9. Failure, retry, and idempotency

- duplicate logical keys or revision numbers fail with stable conflicts;
- exact revision insert replay with the same canonical SHA returns the existing record;
- the same ID with different bytes fails closed;
- plan replay for one workflow succeeds only when the plan SHA matches;
- failed pre-claim resolution or admission creates no lease and consumes no worker attempt;
- a post-claim process failure terminalizes the exact lease once;
- expired leases become `RECONCILING`, not silently reusable, until exact process evidence permits
  `EXPIRED`;
- authentication/capability observation failure appends sanitized evidence and may drain the
  binding, but never writes credential material;
- database serialization/unique conflicts are not automatic cross-account retries.

## 10. Migration, rollout, and rollback

Migration `20260823_0009` is additive and starts empty. It does not backfill historical workflows,
change current worker invocation, or modify existing protocol rows. Upgrade and downgrade are
tested only in the guarded disposable database before any production migration is proposed.

Dual-read code must tolerate workflows without a plan until Milestone A explicitly switches new
workflow creation. Rollback disables new plan selection and returns the current one-shot path while
preserving immutable control history. Dropping Phase 2 tables is a disposable-test downgrade only;
production rollback does not discard written revisions or leases.

## 11. Simpler alternative and why it is insufficient

Keeping model names in YAML and calling `WorkerRegistry.select(role)` is simpler, but it cannot
pin workflow-specific model/effort/instruction/reference provenance, report authentication health,
or atomically prevent concurrent use of the same slot. A single JSONB control table is also
simpler, but cannot enforce one active lease per slot, indexed capability membership, revision FKs,
or reliable concurrency.

A dedicated scheduler, graph database, or external secret service is unnecessary for the current
five-slot host. PostgreSQL row locks, partial unique indexes, typed documents, and the existing
fixed systemd identities satisfy the measured access patterns with less operational complexity.

## 12. Phase 2 validation evidence

The source gate used a newly prepared disposable PostgreSQL database and the guarded
`scripts/api/testdb_*` lifecycle. Migration `20260823_0009` completed upgrade, single-revision
downgrade, and re-upgrade. The composed SQLAlchemy metadata matched the migrated schema exactly.
Integration tests proved immutable payload triggers, pointer/current-revision constraints,
idempotent plan persistence, one held lease under concurrent claims, pool capacity, explicit
expired-lease reconciliation, event ordering, and coexistence of historical protocol hashes.

The disposable database and its protected state directory were deleted by the guarded cleanup
script. Production migration head, records, services, workers, credentials, Artifact storage, and
NAS were not changed during Phase 2 source work.
