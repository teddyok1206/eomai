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

## 13. Administrator model selection (2026-10-09 UTC)

Extend the existing preset lifecycle, not the item request or worker protocol. Administrators edit
authoring, ordinary review and enhanced review model/effort pairs independently. Preserve all
instruction/reference pointers, pool/capacity, isolation, protocol and V2 retrieval/evidence
policies from the pinned released baseline. Existing execution plans remain immutable.

The native per-slot `model/list` catalog is discovery metadata, never proof of entitlement or an
operator allowlist. Observe it through the existing Orchestrator-owned OBSERVE worker handoff.
Keep its source, observation/expiry, CLI version and hash separate from reviewed capability
snapshots. Offer only current reviewed role/pool combinations for execution. Unsupported efforts,
including `max` and `ultra`, remain excluded; missing catalog data is explicit, not a fallback to
the root account. No external LLM API, credential transfer, new dependency or inference is needed
for discovery.

The canonical configuration remains the immutable preset revision. Dominant operations are keyed
revision lookup, set membership of model/effort pairs, ordered candidate iteration and idempotent
validation. Execution chains remain bounded by six slots/five roles/four candidates per role.
Native discovery is separately bounded to 64 models; a role options projection has at most 320
model/effort pairs. Use indexed IDs and maps; do not perform one query per candidate or copy
bundles/content into a new registry.

Validation binds an exact draft, released baseline, policy SHA and evaluator release. Check
baseline preservation, schema/self-hash, released pointer resolution, role/capacity policy and
fresh reviewed capabilities. Non-live invocation acceptance additionally executes the production
CLI argument builder against positive/negative deterministic cases, checking model, effort,
isolation, schema-output and independent-session pins. It consumes no model generation and does
not claim scientific quality, account entitlement or successful inference. Report the exact
executed cases; never turn a few static checks or a browser assertion into a fabricated live
acceptance. Quality remains NOT_EVALUATED.

The API inserts a bounded, immutable `execution_preset_validations` metadata command only; its
reserved `job_` identity becomes the existing structured Job identity when the Orchestrator claims
it. Reuse the existing control-command pattern rather than granting API INSERT on `jobs` or
`protocol_versions`, adding a privileged SQL function, or launching workers from HTTP. API grants
are SELECT/INSERT only on this relation. The Orchestrator owns state, Job/event creation, non-live
cases and canonical Artifact commit. Actor/key transaction advisory locks plus the unique key
serialize concurrent replay; FIFO partial `(requested_at, validation_id)` indexing and one
processor advisory lock protect claiming. The metadata is bounded to 8 KiB per command; the
report and a separately hashed executed-case member live in one canonical Artifact Revision.
Small immutable event checkpoints permit identical-byte recovery, not a second result store.
Runtime evaluator source identity, request, baseline, draft, policy and case hashes are checked
before publication and replay. An uncertain COMMITTING boundary retains its identity and staged
evidence with bounded recovery backoff; it is never reinterpreted as failed or resubmitted.
Release still requires matching approved NON_LIVE/LIVE_ONE_SHOT evidence and creates a successor
revision atomically. Missing/stale pointers, unrelated evidence, altered fixed fields and failed
cases fail closed. Only explicit administrator release advances the current pointer.
For this new validation lineage, release checks the exact baseline under the existing logical
row lock, fresh role/catalog admission and both report/cases member pins. Historical evaluation
families keep their existing meaning; new provenance requirements are not retroactive.

The GUI uses separate model/effort controls, V1/V2-safe cloning, server-owned validation results,
CSRF/role checks, stable per-intent idempotency and stale-response cancellation. A changed base or
unsaved edit clears prior validation/release targets. Rollback disables the new entry point and
leaves preset, job and Artifact history intact. A dropdown directly forwarded to a worker is
simpler but bypasses provenance, evaluation and permission boundaries and is therefore unsuitable.

### Candidate verification and coordinated activation

Implementation state as of 2026-10-09 UTC is a **source candidate**, not an active model change.
The request schema identity remains `preset-model-validation-request/1.0`; the existing Job
envelope protocol is the separate, column-bounded `preset-model-validation/1.0`. Migration
`20261009_0050` adds only the immutable small-command relation and its pending keyset index.
The API still cannot insert Jobs, protocol versions, Artifacts or evaluations.

Verification used explicit source paths/Conda interpreters, not accidentally older installed
modules: core/API focused 414 PASS, Web 341 PASS including actual Chromium, and marker-guarded
disposable PostgreSQL 14 PASS. The latter covers concurrent transport replay, two Orchestrators,
actual restricted API enqueue, immutable/terminal guards, native metadata fixtures through the
real validation/report/release pipeline, unchanged existing plans, identical-identity uncertain
commit recovery, permanent rejection without deleting candidate bytes and indexed queue lookup.
Empty disposable migration upgrade/downgrade/upgrade and exact table/column grants also passed.
No production migration, deployment, preset activation or model generation was performed.

Deployment must coordinate the platform/runner/API/Web packages, migration and narrow runtime
grants, plus the hash-verified fixed worker observation helper. Afterwards use existing account
OBSERVE controls for every required role/slot (current item presets include authoring, image,
review and item_management; support only when present). Auth refresh/rebinding and expiry require
a new catalog observation before model selection, validation or release; an empty list means
UNKNOWN/re-observation needed, not proof that the current model cannot run. Do not relax this
guard, auto-launch inference or adopt a model solely because native discovery advertised it.
The current reviewed allowlist remains authoritative and unchanged.

The independent `generated-knowledge-item@1.20.16` candidate clarifies review evidence union,
subset and purpose rules without weakening validation or editing released `1.20.15`/team-lead
originals. It is not activated by saving or releasing a model preset. The investigated recent
workflow completed normally after protocol-output retries, so no duplicate item/retry was made.

### Completion audit — 2026-10-10 UTC

The resumed implementation remains a source candidate until the coordinated rollout below is
recorded. Independent audits corrected empty native catalogs to UNKNOWN/re-observation required,
and reject logical Artifact or revision drift in acceptance evidence at release. UI regression
coverage now includes exact preserved fixed-role admission, late responses after navigation or
logout, out-of-order refresh, malformed release acknowledgements, and timeout-after-commit replay
with the same intent identity. No policy allowlist or existing preset current pointer changed.

Explicit Conda/source-path verification: core 340 PASS; full non-live API 757 PASS (18 opt-in cases
deselected); Web 346 PASS including real Chromium. Do not add overlapping focused-suite counts.
An initial broad API collection omitted the Web source root; the corrected invocation completed
the full suite. A new marker-guarded disposable PostgreSQL database passed empty-schema upgrade /
downgrade / upgrade to `20261009_0050`, narrow runtime grant reconciliation, and 14 persistence /
restricted-role tests. Production DB pytest is forbidden and was not used. Schema-generator
check, OpenAPI export parity, Ruff formatting/lint and focused strict mypy are required before the
release commit. The existing Starlette/httpx deprecation warning is not a failed test or a reason
to add an unrelated dependency.

Administrator operation: choose a released item preset in **관리자 설정 → 실행 설정**, select the
authoring / ordinary review / enhanced review pairs, inspect and save the draft, run its
non-generating validation, then explicitly apply it. "실행 전달 검증" proves the actual CLI argument
builder and control/pointer invariants, not subscription entitlement, inference or educational
quality. A missing/expired list requires the supported account OBSERVE action; refresh may
invalidate an unsaved choice. The reviewed allowlist currently contains only `gpt-5.6-terra`
`medium/high/xhigh`. Other discovered models require a separately reviewed admission decision;
the feature must never quietly widen the policy to populate a dropdown.

Rollout must preserve current Pack `1.20.15`, preset and workflow pins and the recently verified
HWPX literal internal-member references. Coordinate API/platform/runner and Web, the additive
`0050` migration and narrow grants, plus the hash-pinned native observation helper. The shared
API interpreter also hosts chat owner/worker and the auth broker: check executable work before
stopping those resident consumers, replace the compatible wheels while they are stopped, and
advance only their exact executable-release pin using the supported installer while preserving
the model, protocol and RAG-policy pins. Preserve rollback wheels and configuration. Once `0050`
contains immutable validation history, fallback disables the new entrypoint/restores a compatible
Web release while retaining the new platform/schema; old `0049` wheels alone are not a safe full
rollback. Re-observe
required slots through Orchestrator commands, check HTTPS role-protected model options and one
inactive draft validation, and verify no preset or Pack activation changed. No new item, HWPX,
GPU output or model generation is needed for this rollout acceptance.
