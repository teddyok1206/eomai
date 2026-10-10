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

### Installed rollout acceptance — 2026-10-10 UTC

The coordinated executable release is
`7de886f19b6ad41886b1e03bc7cc06513bfeb027`, source tree
`282f7f65acd76816781e5d3bbca8b726af5056e0`. API/platform consumers, the fixed worker
observation helper and Web were installed as a compatible set. Production migration advanced
from `20261008_0049` to `20261009_0050` through the supported migration command; narrow runtime
grants and installed wheel RECORD/isolation checks passed. The exact predecessor migration
identity is retained in the deployment baseline rather than inferred from its numeric suffix.
The deployment receipt is
`/var/lib/eom-api/deployments/7de886f19b6ad41886b1e03bc7cc06513bfeb027.json`;
the temporary sanitized operation record is
`/tmp/eom-model-selection-release.ac9SHpsb/deployment.log`.

Subsequent authenticated application acceptance checks, separate from the installer log,
used supported OBSERVE commands to refresh slots 01–04 after helper installation. Each native catalog
was OBSERVED with seven advertised models, CLI `0.160.0`, a pinned hash and one-hour expiry.
The four commands were `codexcmd_a381a6b0601f45b599290b25c7601aa6`,
`codexcmd_de55448c5f3b48ddacecc5cadb8f529d`,
`codexcmd_45346ff4e0314b1f9fafec05ea83723d`, and
`codexcmd_021c73fddc024dc9a76d6f724b647833`. Native discovery advertised
`gpt-5.6-luna`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-6-astra`, `gpt-6-luna`,
`gpt-6-sol`, and `gpt-6.1-sol`. Discovery does not admit those models: the installed role-option
endpoint correctly returned only the reviewed Terra medium/high/xhigh pairs for each required
role. Unsupported metadata efforts such as max/ultra were not forwarded into execution presets.

One application canary cloned the exact knowledge-grounded released V2 baseline, changed only
authoring high to medium, and saved **an inactive draft**. The installed API enqueued validation
`job_749c06ae499b43649cc115f960bdcc58`, which the installed Orchestrator completed at
`2026-10-10T02:43:32.981399Z`: NON_LIVE, 35/35 PASS, quality_evaluated=false. Its immutable
draft is `execpresetrev_c764a753c90e48ce87d7774194c419c9`, evaluation
`preseteval_42aea34dfbca4535b813780b7681b5ca`, policy SHA-256
`d0b5dbc2738f6e0388dd2bd3a486cbd29c9b9ef6f29c1449b3a850a44f8e3430`, and report pointer
`artifact_f32591744ae9441e8839fdfd53f9cb32` /
`rev_fea8435690c0454c91c9b3b0d7c7b07e` /
`5bdc5c4e7da5db415a5c99c920d80828311c59374270a12d2c84202d164c7380`.
No release/application command was sent. The exact current baseline remained
`execpresetrev_8dcefbb3518c4d7d8b3289d7f154414c`; the canary remains DRAFT. This exercises
the non-generating invocation builder and result/Artifact boundary, not live model inference.

All seven preset current pointers and all four active Content Pack activation pointers matched the
pre-deployment baseline. Pack `1.20.15` remains active; `1.20.16` is an inactive source candidate.
Chat retained model `gpt-6.1-sol`, protocol 4 and its exact retrieval-policy revision/hash while
only its executable release advanced. API liveness returned LIVE; API readiness, chat slot and
HWPX capability returned READY. The previously accepted HWPX was still securely downloadable with SHA-256
`b229ba6d0c7941d036686adcfab285543f9b013a5124184288c5dd6e1f32fe57`.
Model/GPU submissions and new Item/HWPX builds for this acceptance: **zero**. The marker-guarded
test database was removed through its supported cleanup command. Documentary commits after
this executable commit do not mean runtime source advanced again.

Final documentation parity checks exposed the missing full `generated-knowledge-item@1.20.16`
candidate identity in README after the independent successor commit. It is now explicitly
separated from active `1.20.15`; runtime-version documentation tests passed 3/3. An initial
documentation-test invocation used the core interpreter without its source path, so collection
failed; the installed compatible API interpreter ran the corrected checks. Neither issue
required runtime changes. Authenticated smoke should reuse one session: successful admin
logins also count against the existing five-per-900-second limit. No limiter was reset or
relaxed for this deployment.

### HTTPS browser discovery and bounded read-projection correction

After natural login-throttle expiry, the real HTTPS session successfully initialized ADMIN,
but the preset selector remained empty. The existing HTTP BFF adapter applied scalar-only
`sanitize_mapping` to the preset list and therefore removed its nested `revisions`. Source UI
fixtures supplied complete preset objects directly and did not exercise this adapter, so their
PASS was insufficient to establish this installed boundary. This is not a reason to recursively
relax redaction or copy arbitrary API dictionaries into the browser.

The correction belongs to the existing Application API HTTP adapter: validate and project the
released preset read contract using typed nested revision, role-policy, bundle-pointer, retrieval
and evaluation values. Reuse the Web's existing small pointer/policy models; add no platform import
or dependency to the isolated Web runtime. Canonical presets and all bytes/hashes remain owned
by the API/Orchestrator. Ordered revision iteration and keyed current-revision lookup are linear
in the bounded response, with no DB writes, duplicate artifacts, cache or new queue. Unknown or
malformed nested input fails explicitly rather than silently dropping fields or selecting latest.
Fake-gateway UI tests remain useful but must be supplemented with the real HTTP projection and
actual HTTPS browser. The read-projection correction itself is Web-only; the accompanying
current-default admission correction below requires a coordinated API/platform/Web successor.
Retain migration `0050` and all active pins. No new model validation or generation is needed.

### Request-only selector removal and current-default admission

The request form's former "검증된 실행 설정" field was a legacy quality-profile choice, not a
released-revision selector. Remove that presentation control and its help entry, preserving
saved-draft quality metadata internally for existing integrity/replay contracts. The existing
BFF continues to select its supported logical default (`standard-item` or
`knowledge-grounded-item`); browser users cannot supply a model or revision. "Latest" means the
logical preset's **current RELEASED pointer**, never the largest revision or an inactive draft.

The responsibility for default resolution remains in API admission and the supported
Orchestrator resolver; completed-occurrence reuse remains in the workflow repository. Canonical
request bytes and `workflow_business_fingerprint` are unchanged, because Catalog publication
recomputes that exact hash. The selected preset revision and the accepted execution plan are
separate immutable identities. After an administrator applies a new current revision, a fresh
transport submission must not reuse a completed occurrence carrying the old preset revision.
Add only an optional exact revision constraint to completed-equivalent lookup for auto-current
item admission. Legacy calls retain their existing meaning. Missing plan pointers do not qualify
as matching completed work; do not repair or overwrite the old row.

Choose the standard current pointer under the existing logical-preset row lock before occurrence
lookup, and resolve the new execution plan under that same transaction/lock. The knowledge path
retains its already selected, validated preflight revision. The existing request-hash B-tree
restricts completed candidates before the small execution-plan pointer predicate; candidate lookup
is `O(log N + k)`, with up to `O(k log k)` ordering for the small matching history, not a full scan.
The existing active partial unique index
still forbids concurrent duplicate execution. No DB migration, hash reinterpretation, binary
copy, new schema family, cache, queue or worker protocol is required. Existing public resolver
and repository boundaries own their adapters; domain code gains no SQL, NAS or HTTP access.

Exact transport replay remains the first check and returns the original receipt even after
activation changes. An in-flight business-equivalent occurrence also retains its original pin
and is not forked or reconfigured. Same-current completed work remains reusable. Tests must
cover changed-current completed work, same-current reuse, absent/mismatched old pins, immutable
transport replay and concurrent admission. Always reusing completed work is simpler but defeats
an explicitly changed default; changing the stored business hash is unnecessary and would break
the existing Catalog integrity contract. No live generation is required to verify this boundary.

Follow-up source validation: API 762 PASS, one explicitly opt-in real-systemd skip and 17
integration/live deselections; Web 379 PASS including real Chromium and the real HTTP projection;
execution/admission/publication boundary unit suite 81 PASS. Disposable PostgreSQL workflow
submission regressions passed 12/12; all three concurrency cases passed five additional rounds.
The same restricted API runtime grants permit the new standard-preset row lock without broader
privileges. Canonical request hashes, prior payloads and old completed/active/replay histories
are asserted unchanged. Ruff format/lint, strict type checks and diff whitespace checks passed.
One initial unit-test invocation referenced two nonexistent test filenames; the corrected service
test paths produced the 81 PASS above. No production pytest or new model/HWPX generation occurred.

### Coordinated correction release, 2026-10-10 UTC

API/platform, Web, runner observation helper and the unchanged chat model/policy executable
were installed from `d265a0d04c7298f9223d9828cccc191ea5f180d6`, tree
`bf91e49358bf590a5b7817b22ff6a19400b9671a`. API three-wheel RECORD and installed service identity
checks, runtime isolation and Web's 47-file inventory/RECORD checks passed. All nine existing
services are active. Receipt:
`/var/lib/eom-api/deployments/d265a0d04c7298f9223d9828cccc191ea5f180d6.json`.
Migration remains `20261009_0050`; no new migration ran. Pre/postflight confirms exact preset
and Pack pointers, chat model `gpt-6.1-sol`, protocol 4 and its RAG policy revision/hash are
unchanged. Both protected request entrance services were stopped before rechecking executable
work quiescence; pending preset validations and all nonterminal HWPX rendering states were
included. No in-flight request was reconfigured.

The initial follow-up API options check returned no authoring/review candidates under the
fresh-observation guard. Four supported metadata-only OBSERVE commands refreshed slots01–04:
`codexcmd_c72b5b2f7d7a4075baac2e9ad38ac7bf`,
`codexcmd_c762b2c4291540c79ea14731a1fb0a83`,
`codexcmd_58a91d19c4c04eb69f1b0ee05be93dee`,
`codexcmd_9f21a64207b94462bbf84b6aaf4a6581`. All succeeded; no stale observation fallback,
manual DB update, policy broadening or model inference was used. Subsequent installed API checks
passed: exact current pointers, Terra medium/high/xhigh role options, existing inactive
35/35 NON_LIVE validation, health LIVE/READY and unchanged accepted HWPX download SHA.
The second marker-guarded disposable database was removed through its supported cleanup command;
production data and canonical artifacts were not deleted. Prior compatible 0050 wheels remain
available for rollback; this release does not authorize a downgrade of immutable DB history.

Final actual HTTPS Chromium acceptance passed on this installed release: seven presets retain
their nested revisions (29 for knowledge-grounded), exact released base and capacity pointers
are visible, and 출제/기본 검토/강화 검토 expose Terra medium/high/xhigh. Baseline high/high/xhigh
remains unchanged. The changed-effort review was client-only: confirmation unchecked, draft
submission disabled, no preset/model/generation writes. Request quality/preset/revision selectors
are absent. Both 320px and 390px layouts fit without horizontal overflow; navigation, console,
page errors, HTTP reads and explicit logout passed. The first browser harness incorrectly
required login HTTP 200 instead of the documented successful 201; its corrected replacement
session passed without changing runtime code or authentication policy. Sanitized admin-only
screenshot was visually inspected; no credentials or item content were retained in it.

Final read-only postflight again found executable work quiescent and all preset/Pack/chat pins
preserved. Model submissions, GPU submissions and new Item/HWPX builds across both installations
remain zero. Documentary commits after `d265a0d0` are not a second executable deployment.
