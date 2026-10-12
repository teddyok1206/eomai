# Fixed native embedding Runner implementation boundary

2026-10-12 UTC. **SOURCE_PROTOCOL_ONLY** for the two receipt contracts and **SOURCE_GUARD_ONLY**
for the first Runner migration/model/admission/interface phase. Actual Runner dispatch, publisher,
current authority, migration execution and runtime activation remain unimplemented/unadmitted here.
This advances the approved
[admission proposal](INCREMENTAL_EMBEDDING_RUNNER_ADMISSION_PROPOSAL.md), not a service grant or
runtime activation. Per-encoding owner source is committed at `bc973084`; root subsequently ran
the eight encoding-owner and six Identity-fence disposable DB tests: PASS, guarded cleanup PASS.
These synthetic/limited-role results are not actual source, binary, session or runtime admission.
Existing protected-runtime, Identity, Catalog and
Artifact leaves are not permission or production-composition substitutes.

## Eleven decisions

1. **Responsibility.** Extend the existing Runner with exactly `local-embedding-index@1.0.0` /
   `LOCAL_EMBEDDING`, one required owner-admission port and one required injected native executor.
   Catalog still owns source/projection/registration; Orchestrator owns reservations, launch and
   publication. No handler registry, queue, worker role, Codex fallback or scheduler is introduced.
   Default production composition remains native-unavailable until both concrete owners are admitted.
2. **Canonical source.** The immutable Workflow request is existing
   `LocalEmbeddingWorkflowRequestV11`; resolve its committed `source-plan.json`, `policy.json`, runtime
   bundle and exact configured definition. Use public `validate_local_embedding_request_references`
   and official Catalog `capture_in_session`/missing-binding/registration operations, not a parallel
   eligibility query. Audit actor/hash is provenance only. A zero-demand plan returns coverage-only
   before native Workflow/launch creation; it is not a zero-row native input or successful index.
3. **Identity/revisions.** Keep original all-demand request separate from owned launch association.
   Reuse Workflow/step/attempt/command IDs, `CommandLeaseIdentity` and committed encoding-job1.0
   contracts. Existing definition1.1, request1.0, four admission schemas, native input/result1.0 and
   legacy definition/execution hashes remain byte-identical. Add a native request arm only to the
   Runner repository's accepted storage union; do not add native requests to Codex `WorkflowRequest`,
   `RoleWorkerInput`, role result inventories or `RoleExecutionPolicy`.
4. **Resolution/authority.** New `local_embedding_admission.py` defines the required
   `LocalEmbeddingOwnerAdmission` port: `resolve_submission(session, request)`,
   `resolve_claim(session, candidate)` and `fence_mutation(session, request, lease)`.
   Resolution returns only existing typed request/plan/policy closure; fencing returns no grant.
   Resolve/fence submission and exact claim in their caller-owned root Sessions; candidate peek
   itself only reads metadata and never acquires IAM/source fences or updates session activity.
   Native executor readiness inspects configured immutable runtime/control pins, not saved caller
   authority. Actual current caller/session/source checks happen before claim assignment and repeat
   in every mutation root transaction. No inspected/captured context is a reusable grant. Return typed
   request/plan/policy metadata, never a boolean grant. Each operation binds an independently
   authenticated current operator/session, current `workflow:start`, configured native-purpose policy,
   current official source/read policy and Catalog's `knowledge_graph:publish` registration guard.
   `require_local_embedding_operator_seed` rejects the service branch. The concrete
   `PostgresOperatorAuthorizationFence` is Catalog-role-specific and requires admitted routine/ACL;
   it fences an operator row, not session freshness or Runner privileges. Do not reuse its role,
   grant IAM UPDATE, accept an old ActorContext, or weaken its root-transaction rules to compose.
5. **Access pattern.** Replace `run_once`'s current “has work → global Codex readiness → claim any
   FIFO row” with a read-only exact candidate snapshot followed by purpose-specific readiness and
   an exact-ID claim. Candidate includes command ID/hash/state/generation and Workflow
   identity/definition/request pins. Under `FOR UPDATE SKIP LOCKED`, refresh with
   `populate_existing=True`, compare those pins, re-evaluate claimability and fence the actual native
   caller/source/policy before assigning token/generation. A changed/lost candidate is not replaced
   by another row inside that claim. Existing `claim_next_command` remains supported for old callers.
6. **Structures/indexes.** Add a frozen internal `CommandCandidate` and fixed repository
   `peek_command_candidate` and
   `claim_command_candidate` operations; no persistent candidate/permission cache. For a poll, use
   bounded FIFO peeks (native and non-native) through existing command claimability indexes and the
   Workflow PK/FK join. An unavailable native candidate stays unclaimed; the first eligible legacy
   candidate can proceed, using legacy readiness. Do not scan/re-authorize every source plan in the
   queue or suppress legacy work behind an unconfigured native purpose. Workflow-specific polling
   reports native-unavailable without mutating attempts, leases, events, steps or Jobs.
7. **Scale/cost.** Candidate lookup/claim is bounded indexed SQL; control/source work retains existing
   1,024-demand and request/plan byte bounds. Admission loads each exact control member once per
   operation, with request-local maps, not per encoding. Execution uses the existing linear owner
   batch validation; no vectors, texts, reports, tokens, runtime proofs or full control documents
   enter new DB values. Store existing request snapshots, typed pointer receipts and audit IDs only.
8. **Transactions/concurrency.** Submission resolves/fences before its first savepoint and atomically
   creates Workflow + START command, with actor-bound native fingerprint and exact-key conflict checks.
   Replays reauthorize before returning old identity. Claim retains current authority fences until
   commit. Native execution receives the real lease identity and Runner fenced-transaction callable;
   every short mutation rechecks token/owner/generation/expiry plus current actor/session/source,
   including a late wall-clock expiry check before commit. No SQL transaction spans inference.
   Owner9 remains authoritative for sorted reservation/savepoint races, allocation preservation and
   whole-owned completion. Lease expiry is not nonexecution; uncertain launches retain ownership.
9. **Execution/dependencies.** New `local_embedding_execution_port.py` defines
   `LocalEmbeddingNativeExecutor.evaluate(request)` and `execute(...)`: the latter accepts the exact
   typed request, detached Workflow/step identity, live command identity and fenced transaction.
   Evaluate returns existing `RuntimeReadinessReport` for installed numerical/launcher/resource pins;
   execute includes exact-key reconciliation, not a second recovery framework. No default exists.
   Engine adds a
   fixed `LocalEmbeddingStep` branch: READY/RUNNING, `worker_role=None`, fixed result schema and
   original request pins. After all demanded bindings resolve and register, the executor returns the
   new schema-first native **pointer carrier** below, not raw registration JSON. Pending/uncertain
   returns ordered existing `EmbeddingEncodingReadResult` values in an internal frozen outcome and
   schedules only an idempotent existing ADVANCE command. Native step output/terminal explicitly
   parse the carrier and resolve its canonical receipt Artifact; they never feed it into generic
   `ArtifactPointer`/item-registration handling. `result_schema` remains the unchanged worker-output
   semantic; the carrier's separate `receipt_schema` identifies completion/registration provenance.
   Worker output remains canonical under its owned association. Borrowed-only work may publish a
   legitimate registration receipt, never a fake native input/result; zero demands publish neither.
10. **Failure/retry.** Missing executor, current authority, runtime/configuration pin or fence fails
    before creation/claim. After claim, a lost command/current authority cannot commit step success.
    Exact completed receipt replay preserves history and never rewinds index current; CAS conflict,
    revoked source, invalid output and uncertain execution are explicit. No automatic new encoding
    key, reset, CPU fallback or Codex execution. Native APPROVE/REWORK/RETRY remain unsupported; CANCEL
    cannot imply unit/cgroup termination or release native capacity. Reject a native active-launch
    cancellation until the required owner proves its supported cancellation/reconciliation outcome;
    preserve all legacy command behavior.
11. **Simpler alternative.** One injected executor and two candidate repository operations are smaller
    than a generic application dispatcher. Reusing the Codex executor/readiness lies about role/auth/
    slots; readiness then unconstrained FIFO claim has a real candidate-swap race. A fake receipt or
    rewriting request1.0 to owned inputs loses reproducibility. Required owner ports keep unavailable
    composition explicit while permitting focused source tests, not runtime authority simulation.

## Exact source seams and migration

| Proposed owner paths | Bounded change |
| --- | --- |
| `schemas/workflow/local-embedding-step-output-v1.schema.json`, `local-embedding-workflow-receipt-v1.schema.json`; exact mirrors under `packages/workflow/eom_workflow/resources/` | Two closed2020-12 types in one fixed receipt family, before any behavior. |
| `packages/workflow/eom_workflow/local_embedding_workflow_receipt.py` (new), `schemas.py`, `__init__.py` | Frozen types, bounded parsers/canonical hashes and one pure expected-context/receipt semantic validator; existing schema bytes untouched. |
| `packages/workflow/eom_workflow/admission.py` | Add exact native definition/protocol admission; not a service grant. |
| `services/workflow_runner/eom_workflow_runner/local_embedding_admission.py` (new) | Fixed owner port, strict request/purpose/actor/control closure, additive operator seed use case. |
| `services/workflow_runner/eom_workflow_runner/local_embedding_execution_port.py` (new) | Required native-only readiness/execution interface; existing contracts/receipt types. |
| `services/workflow_runner/eom_workflow_runner/repository.py` | Native storage/load/fingerprint/create arm, shared public definition protocol calculation, exact candidate operations; retain old request serialization/fingerprints. |
| `services/workflow_runner/eom_workflow_runner/engine.py` | Purpose readiness + exact candidate claim, fixed native step/terminal/reconcile guards, existing heartbeat/fence/state/event reuse. |
| `services/workflow_runner/eom_workflow_runner/composition.py`, `__init__.py`, `errors.py` | Explicit paired injection/public exports/content-free native-unavailable errors; no implicit concrete/default owner. |
| `services/workflow_runner/eom_workflow_runner/models.py`, `state_machine.py` | Native stage and total-boolean step guards only. No new state/command/lease tables. |
| `migrations/versions/20261012_0053_local_embedding_stage.py` | Exact post-0052 revision assigned by root after protocol approval; source only here. |
| `services/orchestrator/eom_orchestrator/embedding_artifact_store.py` | Separately reviewed owner leaf publishes sole fixed `receipt.json` through existing `ControlFileSetPublisher`; no second publisher or DTO-approved Job. |

Migration **is necessary**: `ck_workflow_instances_stage` excludes `LOCAL_EMBEDDING`; the last stage
DDL before this phase was `20261010_0051`, and source head at initial review was `20261012_0052`.
Native SQL would otherwise fail. Root now owns the coordinated exact0053 head/release successor.
`workflow_step_runs.step_type` is `String(32)` with **no enum CHECK**, while role/schema already permit
NULL; there is no type enum to widen. Add stage literal and exactly:

```sql
(step_type = 'application') =
  (result_schema IS NOT DISTINCT FROM 'incremental-embedding-result@1.0')
AND (step_type <> 'application' OR (worker_role IS NULL AND step_key = 'encode_batch'))
```

Use total booleans; nullable ordinary equality is unsafe in CHECK. No cross-table CHECK invents
parent-purpose authority. Downgrade first refuses *any* remaining native definition/Workflow/step
history (including COMPLETED whose current stage no longer identifies the purpose), then restores
old constraints; never deletes history. Existing attempts, Job FK, command enums/indexes and states
need no migration. Advancing source head also requires a separately root-reviewed exact release
callback/context successor; do not edit historical0051/0052 callback semantics or dynamic “head”.
At protocol review, read-only source search found no0053 and the native/backend agent owned no
migration; root subsequently assigned the source revision below. No migration is executed here.

## Resolved carrier, reader and claim closure

Both new schemas are closed2020-12, canonical-hashed frozen values with existing public pointer/
identifier/registration `$ref`s. **All** fields below are required; only the two launch fields allow
explicit NULL. No arbitrary dictionaries, executable, role, token, grant or source/body field exists.

| Type / hard canonical byte cap | Exact required fields |
| --- | --- |
| `LocalEmbeddingStepOutput`, schema `local-embedding-step-output/1.0`, ≤8 KiB | `schema_version`; `purpose=LOCAL_EMBEDDING`; `workflow_id`; `step_run_id`; `step_key=encode_batch`; `attempt=1`; `receipt_owner_job_id`; `execution_result_schema=incremental-embedding-result@1.0`; `receipt_schema=eom://schemas/workflow/local-embedding-workflow-receipt/1.0`; `receipt` (ArtifactMemberPointer fixed `receipt.json`, JSON media, that schema_ref); `receipt_sha256` (semantic); `output_sha256` (hash excluding itself). |
| `LocalEmbeddingWorkflowReceipt`, schema `local-embedding-workflow-receipt/1.0`, ≤64 KiB | `schema_version`; `purpose=LOCAL_EMBEDDING`; `workflow_id`; `workflow_definition_sha256`; `workflow_request_sha256`; `source_plan` (exact request member); `source_plan_sha256`; `step_run_id`; `step_key=encode_batch`; `attempt=1`; `receipt_owner_job_id`; `execution_result_schema=incremental-embedding-result@1.0`; `native_launch_job_id` (nullable JobId); `launch_association_sha256` (nullable semantic SHA); `registration_command` (one existing RegisterEmbeddingIndexCommand); `registration_result` (one existing EmbeddingIndexRegistrationResult); `registration_observed_at` (UTC); `receipt_sha256` (hash excluding itself). |

Receipt command counts remain strict1–1,024: eligible count equals exact plan source count, binding
count equals exact demanded source-binding count (not unique encoding count). Pure closure compares
all request/plan/namespace/Graph/policy/source-set pins, carrier/receipt/actual expected Workflow and
step identities, and existing `validate_embedding_registration_result(command, result)`. Resolve all
bindings before receipt success. Launch fields are both NULL only for borrowed/reused-only work;
otherwise both pin the one exact owned association. Pure validation revalidates that association;
the required owner separately proves its actual Job/current-command/source/binary/Artifact lifecycle.
Receipt producer identity is not an authorization field. Actual publisher/resolver checks its
canonical Job allocations and approved committed Artifact metadata; do not manufacture an approved
Job from a receipt DTO. Receipt pointer raw SHA and receipt semantic SHA remain distinct.

Store only the new pointer carrier in native `output_pointer_manifest`, with
`platform_job_id=receipt_owner_job_id`. Registration JSON lives once at its receipt materialization
boundary, not as a replacement worker result/DB blob. Publish sole `receipt.json` as fixed
`control_local_embedding_workflow_receipt`, manifest `control-file-set/1.0`, same immutable owner/key;
use existing publisher and no-clobber retained canonical bytes. Replays resolve the exact published
bytes rather than rebuild the receipt's historical `replayed/is_current/current_lock_version`
observations. These are explicitly as-of `registration_observed_at`, never current permissions/head.
A future native read reauthorizes and separately reads the actual current Catalog head; it never
rewrites this receipt or returns its old current observation as fresh.

Consumer trace: engine `_upstream_pointers`, review correction/rework/escalation binding and generic
terminal consume old `ArtifactPointer`; native branches bypass them. Catalog inference-transfer,
knowledge-analysis, legacy editorial/promotion and mock-exam review readers validate their own
purpose/step/role/schema/Job and remain unchanged. API support/PDF/paired result readers likewise
remain purpose-scoped. Generic `WorkflowStepView` exposes **no output pointer/result**; `WorkflowView`
does not expose `final_pointer_manifest`. eomctl `_step_dict` emits raw pointer metadata; Observe's
repository selects it but snapshot/details expose redacted Job/Artifact metadata summaries, not a
role-result parser. Therefore no released generic API
schema needs widening: an eventual native result API requires a separate explicit native projection.
Native terminal uses the same validated carrier under `final_pointer_manifest.embedding_receipt`,
not `artifact_pointers`, `registration`, `analysis_proposal` or `comparison_result`. New readers parse
this new schema family explicitly; no existing role wrapper or definition/result-schema changes.

Candidate inspection is a **nonlocking read-only operation**, not a PostgreSQL READ ONLY transaction
in which the Identity fence might be attempted. No row fence, session last-seen update, permission
grant or readiness success is retained from peek. Exact-ID claim uses an ordinary writable root
READ COMMITTED transaction: refresh candidate, resolve current authenticated session + Identity +
source/policy fences before lease assignment, repeat late before commit. Existing generic heartbeat
and `_command_fenced_transaction` token/generation/expiry checks remain unchanged; native mutations
add owner fences, never replace the late command check or carry captured authority across roots.
The first native fence is acquired before savepoints, and root rollback releases it.

## Focused gates and next actual integration

New tests: `tests/unit/test_local_embedding_runner_admission.py`,
`tests/unit/test_local_embedding_runner_execution.py`,
`tests/integration/test_local_embedding_runner.py`, and
`tests/integration/test_local_embedding_stage_migration.py`. Extend existing
`test_workflow_composition.py`, `test_workflow_state_machine.py` and compiler/admission tests only
where required. Required cases: no creation/claim side effects on missing owner/executor; service
audit denied; copied/forged request rejected; raw/semantic pins; before/after-readiness candidate swap;
competing exact claims; stale loaded ORM row; native unavailable with legacy work behind it; zero
demands; borrowed-only/pending/full registered outcomes; late command/session/source revocation
rollback; replay without head rewind; no role/slot/prompt fallback; native cancellation uncertainty;
no text/binary DB payload. Root-only disposable gates additionally cover constraints, up/down/up,
nonempty downgrade refusal, limited roles, independent-process claims and actual indexed query plans.
The protocol-first phase adds `tests/unit/test_local_embedding_workflow_receipt.py`: exact canonical
and packaged schema SHA, closed fields/caps, raw versus semantic hash, command/result/count closure,
borrowed-only NULL association, copy/construct rejection, wrong owner/step/request/schema/member,
and historical receipt versus fresh-current read separation. No migration/Runner behavior precedes it.
Run explicit-env Ruff/format, strict mypy including tests and focused pytest before source freeze.

The minimal practical first seed is the new **in-session Runner-owned start use case**, invoked by an
actual authenticated owner operation with fresh session/Identity/source checks—not eomctl actor text,
queued saved credentials or a permanent operator continuation. Existing API reference points are
`get_authentication`, `PermissionDependency(WORKFLOW_START)`, `RequestContext.actor`, and the
purpose-specific `InferenceTransferSubmissionApplicationService`/`InferenceTransferStartAdapter`
pattern. Current `AuthService.authenticate_access` commits before submission; its returned
`AccessAuthentication`/ActorContext alone cannot fence a later root transaction. An Identity-owned
current-session continuation/reauthorization operation and admitted owner transport must close that
gap, without persisting or forwarding raw tokens to workers. Missing continuation leaves native work
unavailable rather than treating the queued initiating operator as authority.

When exposed, add a **separate closed native seed API schema/DTO/route** before behavior plus a narrow
start adapter/service and explicit lifespan injection; preserve generic workflow-start1–6 and
`CommandAdapter` item/Codex conversion. That API successor is a reviewed next vertical, not part of
this source-only Runner change. Background reconciliation additionally needs actual official
Identity service-principal registration/revocation and released retrieval-policy1.1
`LOCAL_EMBEDDING_INDEX` scope, transport/session semantics, model/resource/processing grants and
owner composition. Request1.1 service-audit parsing does not provide them. Operator seed is the first
bounded integration, **not completion** of automatic indexing or the overall goal.

## Protocol-only source gate

Canonical schemas were added before models, with exact packaged mirrors and a separate two-resource
receipt inventory. The old four admission schema bytes/hashes/inventory and Codex role inventory
remain unchanged. New resource raw SHA pins:

- Step output: `sha256:369ac4f4d72a55b7b19483f3a2dc8b52ad37bf35c590aaf0487dd50154d8a772`.
- Workflow receipt: `sha256:16a18269d60ef05e2868b96682af48d9ea0c4a54a766c49dea46f9750fb3bdc3`.

`local_embedding_workflow_receipt.py` adds the two frozen models, public parsers/canonical serializers,
`validate_local_embedding_step_output` (exact raw-member/carrier closure) and
`validate_local_embedding_workflow_receipt` (existing request/plan/policy and optional exact owned
association/input closure, with independently supplied expected Workflow/step/receipt-owner IDs).
It reuses public Catalog registration and Workflow launch validators; no second source, Artifact or
numerical resolver is implemented. Bounded keyed plan/association validation remains linear in
sources/owned keys and canonical metadata bytes; there is no per-row repeated full-batch parse.

Initial protocol gate: **87 PASS in24.28s**. Expanded eight-file native/legacy source regression:
**382 PASS in47.34s**. Ruff check/format and strict mypy including both new test files: **5 files PASS**,
using explicit Conda environments/source PYTHONPATH. The initial focused run was80 PASS/1 fixture
failure (a nonexistent Graph field name); correction used actual `graph_snapshot_revision_id`, with
no product or DB repair. Tests include closed frame/caps, required nullable fields, copied/constructed
bools, raw-versus-semantic pins, exact namespace/counts1–1,024, zero-demand refusal, forged registration,
historical as-of observations and old role/schema separation. New synthetic fixtures prove metadata
closure only; they are not current source/Artifact, binary, session, device or production authority.

Crash/reclaim may change the actual command generation. The receipt pins the **original** launch
association; it contains no current command/token or recovery grant. A later actual owner must link
that immutable history to its fresh command/Identity/session/source authority and supported uncertain
outcome recovery. Do not overwrite the original intent, equate generations, reset encoding ownership
or treat a persisted receipt as continuation authority. Linked recovery behavior remains unimplemented.
No Runner, admission/executor, publisher, DB/migration0053, service registration, runtime, NAS, model,
GPU, install or Git action was performed for this protocol phase.

Root review then identified a narrower direct-API bound gap: the new
`validate_local_embedding_receipt_message` serialized its value before applying the existing raw-tree
depth/object/collection guard. The parser/model path already applied that guard; this was not a DB or
state defect. The new direct validator now calls the **same** `_native_contract_values` leaf first,
then canonical byte/schema checks. No new walker or change to the old four-family validator/schema
was made. Eight direct-call tests prove depth>32, cycles, object>64 and collection>1,024 fail before
serialization (instrumented serializer call count zero). Final follow-up: **95 focused PASS in24.46s**,
**390 eight-file regression PASS in47.15s**, Ruff/format/strict typing on all5 Python files PASS.

## Approved first Runner guard phase (not dispatch)

Root assigned source migration `20261012_0053`, predecessor `20261012_0052`, after committing the
receipt protocol at `36041ea5`. Scope is only the native stage/one combined total-boolean step CHECK,
one enum/terminal-map entry, exact definition admission, required typed owner/executor interfaces
and pure request/control/audit validation. Downgrade preflight recognizes exact native definition,
stage/protocol/request-schema and application/result-schema markers before any DDL; any such history
refuses downgrade without deletion. No current actor/session/source permission is provided by a
resolved metadata value or static definition admission. Ports have no default implementation.

This phase does **not** edit engine, repository, composition, public publisher, source head, release
callbacks, credentials, DB roles, protected runtime or installer. Root owns the explicit release0053
context/callback/deploy/head successor; no migration is executed here. State-machine scope is one
`LOCAL_EMBEDDING` stage with only COMPLETED/FAILED/CANCELLED targets; old transitions remain exact.
The later exact-candidate/native dispatcher and actual session/service/Artifact composition remain
required subsequent gates, not activated by these source guards.

First-phase freeze: new0053 source +Runner model CHECK/stage +minimal state-map addition +exact
Workflow admission +`local_embedding_admission.py`/`local_embedding_execution_port.py` interfaces
and pure guards are implemented. `ResolvedLocalEmbeddingAdmission` revalidates controls and denies
future service audit; `validate_local_embedding_runner_admission` recompiles exact native definition,
checks canonical/typed/hash/control/operator-audit closure, and rejects zero-demand native starts.
This is not authentication: actual root-session current authority remains the required owner port.
`resolve_claim` takes the actual refreshed locked command/Workflow rows and typed request, not a new
candidate/grant DTO; the immutable peek header remains next-phase repository work. Internal pending
reads are bounded/sorted/unique existing encoding-job values; FAILED/CANCELLED cannot hide as pending,
while completed computation can still wait for real registration. No executor implementation exists.

Source regression: **430 PASS in45.19s** across the12 listed native/legacy test files; Ruff/format and
strict mypy including unit/integration tests: **11 files PASS**. Guarded migration integration:
**18 collected, NOT_EXECUTED** here (existing official disposable-owner fixture). Root owns actual
up/down/up, current constraints and nonempty native-history checks. The pre-edit legacy source matrix
was1 FAIL because transfer1.1 was omitted; old mapping remains intact with explicit successor/native
additions. First WIP guard run had10 failures from passing a typed model to the old wire-only parser;
the new adapter now revalidates the raw typed tree before its canonical wire projection, without
changing that released parser. No rows, history, schema bytes or production state were repaired.

No engine/repository/composition, publisher, Orchestrator head, release callbacks, DB/runtime/NAS,
model/GPU, install or Git changes were performed by this agent in the guard phase. Root's separately
owned head/release source work is not a production migration or native/service activation claim.

## Next exact-candidate/dispatch phase — final design-only plan

Root independently reviewed the guard/release source:579 tests PASS, strict/style PASS; committed
`9d72c7c2`. Root then ran supported disposable0053 up/down0052/up0053 and **18 migration tests PASS
in0.35s**, exact DB/owner cleanup PASS; evidence pushed at `73e499e8`. Production/model/GPU were
unchanged. This section is a plan only: no queue/dispatcher behavior is edited before root approval.

| Stage / exact paths | Exact symbols and protected responsibility |
| --- | --- |
| A: `repository.py` | `workflow_request_storage_document`, new `load_persisted_local_embedding_workflow_request` and `local_embedding_business_fingerprint`, `create_workflow_instance`; add request1.1 only to repository storage union with required owner/executor guard before lookup/create/replay. Preserve role request union, all legacy serialization/fingerprints, request1.0 history and nullable pins. `_compiled_role_protocol` delegates validated definitions to public `definition_execution_protocol`; `_stored_role_protocol` handles fixed native snapshot separately while retaining old inactive historical projection behavior. |
| A: new `local_embedding_submission.py`; existing admission/execution port modules | `start_local_embedding_in_session` is the single Runner-owned atomic Workflow+START use case: mandatory actual owner and native executor, current root-session resolution/fences and exact definition/control validation; zero demands return existing coverage-only plan without Workflow/command/Job. Ports' `CommandLeaseIdentity` imports become type-only where necessary to prevent repository/interface import cycles, not a new lease abstraction. |
| B: `repository.py` | Frozen internal `CommandCandidate`, fixed `CommandExecutionFamily`, `_native_workflow_filter`, `peek_command_candidate`, `claim_command_candidate`; existing `claim_next_command`/`claimable_command_exists` become **legacy-only**, including workflow-specific calls. No include-native boolean or unfenced fallback. |
| B/C: `engine.py`, `errors.py` | `WorkflowRunner.__init__` accepts explicit paired owner/native executor or neither; `run_once` uses purpose peek/readiness/exact claim and existing lease scope. `_advance` delegates fixed native steps before generic role/terminal handling. `reconcile(workflow_id)` must reject native `command_id=None`; native reconcile requires existing queued command with a live lease. Add stable native unavailable/invalid-outcome codes only. |
| C: new `local_embedding_step_execution.py` | `advance_local_embedding_step`, `complete_local_embedding_terminal`, native fenced-transaction wrapper; fixed two-step use case owns Runner step rows/events only. Reuse repository/state-machine primitives and required public executor/owner ports; no source/Artifact/kernel resolver is copied into Runner. |
| C: `composition.py`, supported Runner exports | Explicit removable paired injection with default native-unavailable; leave Codex construction/readiness/execution unchanged. No configured factory, operator/session continuation, service grant or privileged installation is inferred from a source interface. |

**Exact claim sequence:** two nonlocking LIMIT1 peeks (native/legacy), compare existing FIFO order;
inspect only bounded pointer/request metadata, close that Session → evaluate the selected purpose's
configured readiness without IAM/source fences, session activity writes or permission caching →
fresh root READ COMMITTED transaction locks/refreshes **that Workflow and command only** with
SKIP LOCKED and `populate_existing=True` → compare immutable header and re-evaluate claimability →
mandatory `owner.resolve_claim` on actual root-session rows **before** token/generation assignment →
assign existing lease fields → late live lease/owner/expiry fence before commit. No second candidate
is silently substituted in that claim. Lost/busy header rolls back/releases locks and returns to peek.
Native mutations use the same Workflow→command lock order, preserving the existing final command
row fence; claim never holds a command lock while waiting on an inversely locked Workflow.

Candidate captures command ID/type/hash/state/generation/attempts/availability/expiry/FIFO position
and Workflow ID/definition ID+hash/request hash/current step/state/lock version; no lease token or
actor-authority value. The null-safe total native routing predicate checks exact supported definition,
protocol/request-schema and native step markers, including malformed native snapshots, through
existing Workflow/definition PK joins and indexed step Workflow FK EXISTS. It never uses substring
matching, JSON grants or a full event scan. The legacy claim query excludes those markers itself:
an old caller cannot bypass the native owner by calling it directly. Existing indexes suffice for
this bounded phase; prepare actual query-plan/statement-budget evidence before proposing an index.

An unavailable/busy native purpose leaves its command unclaimed or records typed pending reads with
a bounded existing ADVANCE backoff; the first ready legacy candidate still proceeds. No full queue
source-plan capture loop or global Codex readiness gate disables native purpose readiness, and native
unavailability never disables legacy readiness. Expired native command reclaim requires actual linked
recovery admission before assignment; missing recovery evidence stays unavailable/uncertain, not a
fresh encoding or mutated original launch association. Header/hash/readiness success is never a
current operator/session/source grant.

The native step stores only the original existing source-plan member pointer as input metadata and
the new receipt **carrier** as output, with receipt-owner Job FK. Pending readings must exactly cover
the unique original-plan computational keys/space, with no missing/duplicate/foreign keys; borrowed
readings retain their original winner's Workflow/intent, not the current Workflow as a forged owner.
Completed compute may remain pending registration. Success parses/binds the carrier to the expected
Workflow/step/attempt and requires the executor's actual canonical receipt/producer/registration proof;
then late current-owner/live-command fencing commits existing step/Workflow transitions and
`final_pointer_manifest.embedding_receipt` only. No raw registration JSON/vector/text enters step DB.
The helper calls inference outside **all** SQL transactions/fences; the transaction callable is for
short owner mutations, never a context held around synchronous execution.

CANCEL keeps supported durable Workflow/command/step cancellation semantics and current actual
operator cancel authorization; it is a stop-request/history boundary, not unit/cgroup completion.
It never releases launch capacity/GPU lease, resets reservations or marks outputs successful. Later
results still fail their invalidated command/Workflow fence; supported owner cleanup/reconciliation
must independently prove outcome. Native RETRY/REWORK cannot bypass fixed max-attempt1/no-rework,
terminal state or uncertain ownership; reject unsupported operations explicitly without changing
legacy commands. No new command/state/queue/schema/migration or generic dispatch framework is needed.

Focused next tests: extend `test_local_embedding_runner_admission.py`; new
`tests/unit/test_local_embedding_command_claim.py`, `test_local_embedding_runner_execution.py`,
`tests/integration/test_local_embedding_runner.py`; extend existing composition/lease tests narrowly.
Cover legacy claim native exclusion, native-unready/busy before legacy, exact candidate swap/competing
claim/stale identity-map refresh, unchanged legacy FIFO/lease generations, missing owner/executor
before create/claim, zero-demand no rows, late lease/session/source revocation rollback, exact pending
keys/borrowed ownership, immutable receipt replay/no head rewind, direct-reconcile refusal, cancellation
without cleanup/reset, and reclaim without actual recovery. Independent-process/query-plan DB tests
are prepared for the guarded root harness only. Operator seed/API/current-session integration and
scoped background `LOCAL_EMBEDDING_INDEX` authority remain required overall, not completion here.

### Stage A approved source boundary — storage and atomic submission only

Exact owned files: `services/workflow_runner/eom_workflow_runner/repository.py`, new
`local_embedding_submission.py`, existing `local_embedding_admission.py` and singular
`local_embedding_execution_port.py`; existing `tests/unit/test_local_embedding_runner_admission.py`,
new `tests/unit/test_local_embedding_submission.py`, and this note. No claim, engine, composition,
execution, migration, schema, API or runtime activation changes belong to this stage.

Repository symbols: add exact1.1 `load_persisted_local_embedding_workflow_request` (no repair/latest),
`local_embedding_business_fingerprint`, additive storage union/native `create_workflow_instance`
arm, and fixed native protocol handling in `_compiled_role_protocol`/`_stored_role_protocol`.
Fingerprint fields are definition key/version/hash, the complete nullable-preserving canonical1.1
request, and `{actor_type, actor_id}`. Therefore replay/active-equivalence cannot cross operators;
per-encoding computational deduplication remains the separate owner9 identity, unchanged.

Add pure `validate_local_embedding_submission_controls` for exact compiled definition, request/
plan/policy and operator-audit closure even with zero demands; existing
`validate_local_embedding_runner_admission` calls it and retains its nonempty compute rejection.
Required owner/executor presence is checked before **any** lookup/create/replay. The actual injected
owner resolves the same active root Session and exact request before persistence and repeats its
current authorization fence late; metadata cannot grant authority. Native stored definition identity,
hash, exact snapshot and current active admission are checked for zero and nonzero outcomes alike.
The caller retains root transaction ownership; a bounded savepoint makes Workflow+START atomic,
and a late failure rolls both back without committing or changing a pre-existing replay.

`start_local_embedding_in_session` returns an internal frozen typed union, not a new wire schema:
`LocalEmbeddingCoverageOnly(plan: LocalEmbeddingSourcePlan)` reuses the already verified immutable
zero-demand plan and creates no Workflow, command or Job; `LocalEmbeddingWorkflowSubmitted` carries
the exact Workflow and START command records plus separate `workflow_created`/`command_created`
observations. It creates/enqueues only after exact closure; replay still reauthorizes actual current
operator/source and compares the actor-bound fingerprint. Executor presence is not runtime readiness,
permission or a call to inference; candidate readiness remains Stage B. Type-only imports of existing
`CommandLeaseIdentity` avoid a repository/interface cycle without creating another lease abstraction.

Focused tests: exact request1.1 storage/reload including required nulls; no1.0 upgrade/repair; native
and legacy definition/protocol projections; actor-bound fingerprints; missing either port and foreign
purpose before SQL/replay; owner-denied source/session; valid zero demand no writes; zero demand
invalid definition/hash/operator/control rejection; one Workflow+START; same-key replay/mismatch,
same-actor active reuse versus cross-actor separation; late owner failure savepoint rollback; unchanged
legacy fingerprint/storage/create and transfer1.0/1.1 behavior. All are source unit tests; no DB,
current source authority, runtime composition or background service grant is claimed by this stage.

Stage A source freeze: the exact seven owned paths above are implemented; no Stage B/C path changed.
One added repository leaf, `validate_local_embedding_workflow_submission`, refreshes the exact
Workflow PK with `populate_existing=True` and validates definition/request/actor/protocol closure
inside native create's savepoint. The submission use case reuses that result; it does not duplicate
Workflow validation. Original START is read/checked on replay; missing or corrupted history refuses
without creating a replacement START or changing completed state. Definition admission is read with
SHARE locking and identity-map refresh. The current owner is invoked before savepoints and late;
composed nonzero submission makes four bounded owner calls (root, native create entry, native create
late, submission late), zero demand two. Nested calls must reuse retained root fences, never create a
nested authorization grant. No runtime readiness/inference runs inside any of these transactions.

Final source gate: **584 tests PASS in39.15s** across17 native/legacy unit files; Ruff/check-format and
strict mypy on all6 Python files PASS. Earlier focused gate139 PASS12.30s; intermediate broader
527 PASS37.72s plus55 legacy persistence/dispatch PASS5.17s. Initial strict run exposed one test
operator/service-union attribute error, corrected with the existing pure operator-audit extractor;
no runtime defect/DB repair was inferred. All six frozen native control/receipt schema raw hashes
were independently rechecked unchanged. Tests use explicit synthetic Session/owner/executor spies:
they prove source validation/order/savepoint intent, not PostgreSQL rollback or actual permissions.
No DB/root/IAM/NAS/model/GPU/install/Git actions were executed. Real authenticated session/source
composition, protected executor, exact-candidate claims and service admission remain pending.
