# Codex Control-Plane MVP Application Design

Status: Phase 5 implementation design

Date: 2026-08-23 UTC

## 1. Responsibility and boundary

This phase activates the already-defined Codex execution control plane without creating a second
workflow, prompt, worker-registry, or credential system. Ownership remains:

- `eom_workflow`: immutable JSON Schema 2020-12 contracts and frozen value models;
- `eom_orchestrator`: preset/bundle/plan/auth/capability/lease application rules and persistence;
- `eom_workflow_runner`: the only production component that may initiate fixed worker and fixed
  authentication-probe units;
- Application API: authenticated RBAC/idempotency boundary and bounded projections;
- Scientific Studio: BFF and human-facing educational/admin controls only;
- Artifact Revision storage: canonical Markdown instruction/reference/evaluation bytes;
- PostgreSQL: identities, immutable revisions, pointers, commands, leases, and projections only.

The API does not receive credentials, credential paths, arbitrary host paths, raw Codex arguments,
or free-form worker identities. Worker identities never receive DB, NAS, sudo, Docker, another
worker's home, or direct service authority.

## 2. Canonical source and revision model

```text
ExecutionPreset logical identity
  -> immutable DRAFT revision
  -> immutable RELEASED revision (current pointer)
  -> optional immutable DEPRECATED revision + retired logical identity

Instruction/Reference Bundle logical identity
  -> immutable RELEASED manifest revision
  -> pinned approved Markdown Artifact Revisions

Workflow Instance
  -> exactly one immutable Resolved Execution Plan
  -> exact preset/capacity/bundle/model/effort hashes
  -> per-step short-lived Worker Lease

Codex auth binding
  -> mutable sanitized current projection
  -> append-only health events
  -> immutable capability snapshots
```

An immutable revision row is never updated to simulate release or deprecation. Releasing a draft
creates a new immutable `RELEASED` revision containing the same reviewed semantic policy, advances
the logical current pointer atomically, and retains the draft. Deprecation creates immutable audit
evidence and retires the logical identity; it never rewrites a released revision or makes a
deprecated revision current.

Quality/evaluation evidence is not hidden in a description or confused with a Reference Bundle.
When persisted, it is a separately typed immutable evidence record whose payload is an approved
Artifact Revision and whose target is an exact preset revision/policy hash. A release must expose
the evidence scope (`STATIC`, `NON_LIVE`, or `LIVE_ONE_SHOT`); Milestone A is not complete until a
separately authorized live acceptance is linked. This relationship is additive and does not alter
the immutable `execution-preset-revision/1.0` bytes.

## 3. Required pointers and resolution checks

Before a new workflow receives a plan, resolution verifies:

1. exact active preset key and current released revision;
2. preset document schema, typed model, self-hash, and logical/revision ownership;
3. exact released capacity-policy revision and fixed pool/role/slot membership;
4. every instruction/reference manifest logical ID, revision ID, schema, media type, approval,
   owner, manifest hash, and content hash;
5. exact active workflow definition ID/version/hash and one role protocol family;
6. exact Content Pack release ID/bundle hash and compatibility;
7. one policy for each agent step and an available model/effort pair;
8. no graph/evidence pointer for the Reference-Bundle-only Milestone A path.

Materialization re-resolves only the immutable pointers stored in the plan. It never consults a
mutable current pointer, substitutes a latest revision, follows a symlink, stages an unauthorized
member, or trusts a filesystem path as identity. The plan-derived allowlist contains only the
manifest and Markdown Artifact Revision IDs required by that exact step.

## 4. Primary access patterns and structures

| Operation | Structure/index | Complexity and scale |
| --- | --- | --- |
| preset list/current lookup | B-tree unique preset key/current FK | `O(log n)`, expected <100 |
| immutable revision compare | `(preset_id, revision_number)` unique index | `O(log n + k)` |
| account health list | five-row binding scan plus indexed latest capability | bounded `O(5 log n)` |
| control command claim | indexed state/time order with `SKIP LOCKED` | `O(log n)`, one runner |
| execution-plan lookup | unique workflow ID | `O(log n)` |
| capacity admission | one locked pool policy plus bounded five-slot scan | `O(5)` |
| active-per-slot/global limits | partial unique indexes and indexed held state | constraint-enforced |
| health/lease history | append-only owner/sequence | `O(log n + k)` |

Five fixed slots do not justify a generic scheduler or priority-queue framework. Excess jobs remain
queued. Preset revision policy rows use keyed role lookup rather than repeated unordered scans.

## 5. Transactions and concurrency

- Workflow creation, preset resolution, immutable plan insertion, and initial workflow command
  insertion occur in one transaction. Failure publishes neither workflow nor plan.
- Existing idempotent workflow replay returns the already-pinned plan and never resolves current
  preset state again.
- Control commands use an operator-scoped idempotency key, immutable request hash, short lease,
  `FOR UPDATE SKIP LOCKED`, and one terminal result. They never contain credentials.
- Capacity claim locks one capacity-policy row, checks all ceilings, selects one deterministic
  eligible slot, and inserts one lease in a short transaction. Codex never runs in a DB transaction.
- Lease release is best-effort in a `finally` boundary and records a stable terminal reason. An
  expired lease enters `RECONCILING`; the slot is reusable only after exact fixed-unit absence.
- Preset release/deprecation locks one logical row and allocates the next revision number under its
  unique constraint. API idempotency turns transport replay into the same command result.

## 6. Dependency direction and adapters

```text
Scientific Studio -> Application API contracts/routes
                  -> control-plane application/query adapter
                  -> eom_orchestrator public use cases
                  -> eom_workflow contracts + identifiers

workflow runner composition -> control-command processor
                            -> systemd auth-probe adapter

workflow role executor -> plan resolver/capacity/materializer interfaces
                       -> fixed systemd worker adapter
```

Routers validate HTTP concerns and call use cases. They do not implement preset lifecycle,
capability, scheduling, filesystem, or systemd rules. Domain/contract packages do not import API,
SQLAlchemy sessions, systemd, or filesystem infrastructure.

## 7. API and GUI surface

ADMIN-only API/BFF surfaces expose:

- sanitized account/binding health, CLI version, latest capability pairs, lease state, and last
  successful job;
- idempotent drain, disable, and observe/enable commands (fresh authentication required);
- preset logical identities, immutable revisions, current pointer, lifecycle, policy comparison,
  validation result, and evaluation evidence metadata;
- draft/release/deprecate commands with strong preconditions and idempotency.

The editor request surface exposes only educational requirements plus one released reviewed preset
choice. It never exposes model, effort, Linux user, slot, path, credential, fallback, or arbitrary
graph controls. The first selectable value is only `standard-item`; `fast`/`deep` labels in older
ephemeral GUI drafts remain parseable for compatibility but are not selectable for new control-
plane requests.

## 8. Authentication operations

The Application API must not receive a Codex token/password/device code and must not start worker
units directly. It enqueues a sanitized command. The existing workflow-runner identity claims it
and may start only an exact root-installed `eom-worker-auth-XX.service` permitted by the existing
polkit regex. `READY` is written only after the exact worker-identity non-generating probe and the
reviewed CLI capability observation both pass.

Re-authentication itself remains an operator-side action under the exact worker identity. The GUI
may show `REAUTH_REQUIRED` and a non-secret operational instruction; it never transports login
material. Drain waits for an active lease to terminalize naturally. Disable and drain do not kill a
worker or broaden permissions.

## 9. Failure, retry, and idempotency

- Missing/stale/unsupported plan input fails before worker claim and consumes no Codex attempt.
- Capacity exhaustion leaves work queued; it does not select another model/account implicitly.
- A post-claim auth/process/result failure creates one terminal attempt and releases/reconciles the
  exact lease. There is no cross-account retry or session resume.
- A control command is at-most-once per idempotency key/request hash; failed probes remain visible
  and never become READY by manual state mutation.
- Existing workflows with no plan use the legacy one-shot path unchanged. New plan-backed requests
  never silently fall back to legacy execution.
- Rollback disables new preset selection and plan-backed creation while preserving all immutable
  rows. It does not delete history or reinterpret old workflows.

## 10. Bootstrap and deployment

The initial bootstrap is a reviewed, commit-pinned operator command. It creates one bounded capacity
policy, instruction bundles, one approved Markdown Reference Bundle, five sanitized auth bindings,
capability observations, and one `standard-item` preset. Artifact bytes are committed once through
the orchestrator boundary; PostgreSQL receives pointers and hashes only. The bootstrap is
idempotent by logical key/version/hash and fails closed on any conflict.

Deployment order is: dual-read code/contracts; migrations 0009 and any additive Phase 5 relation;
bootstrap artifacts/data; fixed helpers/units/policy; API/workflow runner; GUI; non-generating
identity/capability/fake-worker smoke; separately authorized one-shot live acceptance. Rollback
never removes additive tables or immutable history.

## 11. Security and acceptance gates

- exact five configured identities and global maximum three active Codex leases;
- credentials absent from DB/API/GUI/log/Slack/artifacts/manifests;
- new requests pin one `standard-item` revision and exact reference Markdown revisions;
- worker invocation includes `--ephemeral --ignore-user-config` and exact plan model/effort;
- only job-local references are readable; NAS/DB/repository/other homes remain inaccessible;
- API runtime grants are table- and verb-specific; no schema/function/role authority;
- old workflows and protocol/resource hashes replay unchanged;
- default tests never invoke live Codex;
- live acceptance remains a separately authorized, exactly-once operation.

## 12. Simpler alternative and why it is insufficient

A YAML preset read directly by the GUI/runner would be simpler, but it cannot provide immutable
workflow provenance, concurrent-safe current pointers, pointer/hash validation, or historical
replay. Letting the API start systemd units directly would avoid a command queue, but it broadens
the internet-facing service authority and bypasses the orchestrator. Reusing session context would
reduce startup work, but it makes item independence and reproducibility unverifiable. The selected
design adds only the persistence and queue boundaries required by these current, demonstrated use
cases; it does not introduce a generic plugin or scheduler framework.
