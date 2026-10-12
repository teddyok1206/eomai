# Fixed native embedding Runner implementation boundary

2026-10-12 UTC. **SOURCE_PROTOCOL_ONLY** for the two receipt contracts; all Runner, publisher,
admission, migration and runtime behavior below remains proposed and unimplemented by this phase.
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
| `migrations/versions/<root-assigned-next>_local_embedding_stage.py` | Next post-0052 migration, exact revision assigned by root only after approval. |
| `services/orchestrator/eom_orchestrator/embedding_artifact_store.py` | Separately reviewed owner leaf publishes sole fixed `receipt.json` through existing `ControlFileSetPublisher`; no second publisher or DTO-approved Job. |

Migration **is necessary**: `ck_workflow_instances_stage` excludes `LOCAL_EMBEDDING`; the last stage
DDL is `20261010_0051`, and current source head is `20261012_0052`. Native SQL would otherwise fail.
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
Read-only source search currently finds no0053 revision, and the native/backend agent owns no
migration. Root still assigns the exact revision after protocol review; no DDL source is added now.

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
