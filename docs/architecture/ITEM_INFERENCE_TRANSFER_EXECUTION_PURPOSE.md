# Inference-transfer comparison: dedicated execution purpose

Status: source-only foundation. Runtime activation remains
`UNSUPPORTED_PENDING_COMPATIBLE_RELEASE` until the request, resolver,
materializer and Catalog authorization boundary are connected and verified.

This extends `ITEM_INFERENCE_TRANSFER_WORKER_BINDING.md`; it does not change
released authoring, PDF review or customer-support semantics. A machine pair
comparison is a hypothesis, not a human-confirmed transfer label.

## Required design decisions

1. **Responsibility and boundary.** Catalog prepares and authorizes two exact
   profiles; Workflow Runner coordinates one `compare_pair` step; Orchestrator
   owns execution, validation and Artifact commit. The new purpose is
   `item-inference-transfer-comparison@1.0.0`, using the existing `support` role
   and `workflow-role/1.29.0`. It is neither a support ticket nor PDF review.
2. **Canonical source.** Approved Item/accepted analysis revisions, their exact
   solution evidence and Graph snapshot remain authoritative. Profiles are
   explicitly derived immutable values. The released preset and instruction
   bundle determine execution behavior. No Content Pack is required: existing
   support-purpose infrastructure already supports instruction/preset plans,
   while authoring Pack profiles have a different responsibility.
3. **Identity and revision.** Keep workflow/plan/preset/capacity identities and
   revisions separate from hashes. `resolved-execution-plan/21.0` pins the
   comparison request hash, two profile pointers, Graph, access policy, rubric,
   instruction bundle and actual prompt hashes. Previous plan schemas remain
   byte-for-byte unchanged. No manufactured Workflow FK is allowed.
4. **Pointers and resolution.** Resolve existence, revision, lifecycle,
   permission, schema/media and hash before staging. The rubric uses a logical
   rubric/revision/hash pointer plus a `ControlArtifactPointer` to one immutable
   Markdown member in the existing instruction bundle, layer `ROLE`, path
   `instructions/transfer-rubric.md`. The rubric content hash equals that
   member's SHA. Materialization must verify bundle membership; this pointer
   does not authorize itself. No new rubric registry or source-rights bundle
   is needed. Catalog independently reauthorizes both exact sources for the
   original authenticated actor before execution, historical replay and commit.
5. **Primary access patterns.** Exact plan/workflow/preset lookup; O(1)
   admission by purpose/version; two-source authorization; one atomic queue
   claim; ordered bounded profile input; append-only execution history.
6. **Structures and indexes.** Reuse existing indexed command queue, unique
   workflow plan row, atomic capacity/lease records and immutable Artifact
   manifest. Add `INFERENCE_TRANSFER` to the stage enum/transition table and
   its existing DB CHECK only. No table, queue or new index is required.
7. **Scale and complexity.** One comparison has exactly two profiles and one
   support step. Input/result remain bounded to 64 KiB at the worker boundary.
   Source membership/hash checks use maps/sets, O(claims + references), not
   all-pairs Graph scans. Two-source authorization must not reload an entire
   embedding corpus. Existing capacity ceilings continue to bound concurrency.
8. **Transaction and concurrency.** Existing Workflow creation/command
   transaction owns request persistence and idempotency. Existing plan resolver
   locks the released preset once and persists a plan under its Workflow FK.
   Runner step CAS/command fencing and Orchestrator claim/lease prevent duplicate
   execution. `before_execute` binds a job; a separate transfer-source
   authorization callback is mandatory and is not replaced by that binder.
9. **Dependency and adapter ownership.** Contracts import contracts/value
   objects only. Runner uses a typed Catalog application port for preparation
   and authorization. Catalog resolves source permissions through its official
   retrieval boundary. Orchestrator materializes protected controls and commits
   results. Workers receive local JSON/Markdown only, never DB/NAS access.
10. **Failure, retry and idempotency.** Missing/revoked/stale/hash-mismatched
    sources, incompatible protocol/preset or changed exact replay pins fail
    explicitly. No latest fallback, alternate identity or direct row update.
    Historical failures remain recorded. Terminal replay rechecks current
    authorization before returning an old result. A failed source check consumes
    no worker slot and commits no new result.
11. **Simpler alternative.** Reusing customer-support/PDF plans or constructing
    a fake authoring Pack would be smaller in lines but would falsely describe
    purpose, provenance and permissions. A standalone V21 plan and single-step
    definition are the smallest semantically correct extension. A generic new
    framework or separate queue is unnecessary.

## V21 contract

Common pins: `plan_id`, `workflow_id`, preset ID/revision/SHA, exact Workflow
definition key/version/SHA, capacity revision, UTC resolution time and canonical
plan SHA. Purpose is fixed; exactly one `compare_pair` support step is allowed.

Purpose pins: `comparison_request_sha256`, `left_profile`, `right_profile`, full
`graph_snapshot`, `access_policy_revision_id`, `access_policy_sha256`,
`requester_permissions_sha256`, `rubric`, `rubric_artifact`,
`core_prompt_sha256`, `prompt_sha256`. Distinct profiles are required. Rubric
artifact SHA and rubric SHA must match. The plan does not carry full profiles,
report text, PDF/PNG bytes or model-supplied authority.

The step uses a released model/reasoning candidate, protected instruction bundle,
the existing `customer-support` operational capacity pool, a bounded timeout,
read-only sandbox, disabled network, no reference bundle and general knowledge
`DENIED`. Model names are not hardcoded to a historical Codex model; compatibility
and actual runtime pins remain the existing preset/materializer's responsibility.

## Source-only implementation and remaining ownership

Foundation: V21 JSON Schema then frozen model and registry entry; dedicated
Workflow YAML/exact admission; additive stage transition/CHECK migration; tests.
The source migration successor is `20261010_0051` after `20261009_0050`.

Follow-on, separately verified before activation:

- A schema-first dedicated Workflow request (not a ticket/PDF wrapper), bounded
  worker context and exact access-policy pins. The authenticated actor remains
  application-owned, not model input.
- Runner persistence/discriminated loading, correct `INFERENCE_TRANSFER` stage,
  terminal `comparison_result` pointer (not false `registration`), and an
  explicit Catalog preparation/authorization port.
- Purpose-specific protected instruction/preset bootstrap and V21 resolver,
  with one-time current-preset locking and exact historical replay.
- V21 materializer/result-plan guard support, rubric member checks, actual
  runtime provenance and separate source-authorization callback composition.
- Installed package/protocol compatibility, disposable DB replay/concurrency
  and revoked-source tests, then an explicitly opt-in bounded worker canary.

No UI, deployment, published preset/Pack change, operating DB migration, model
invocation or human quality acceptance is implied by this foundation.

## Source-only materialization implementation

The V21 materializer and application context are implemented and verified with
synthetic protected-file fixtures. Both
`authorized_execution_artifact_revisions` and `materialize_execution_step`
dispatch V21 explicitly; they no longer attempt V1 parsing for that purpose.
This is not installed-runtime or live Artifact evidence. Dedicated resolver/
Runner execution composition, installed compatibility and activation still need
their own gates. `UNSUPPORTED_PENDING_COMPATIBLE_RELEASE` remains the runtime
status.

### Ownership and exact inputs

- Keep the existing Runner application, Orchestrator, control resolver and
  `CodexWorkerAdapter`. Do not create an inference-transfer executor, queue,
  cache, capability-boolean framework or Content Pack wrapper.
- The materializer's supported frozen plan union and both exact schema dispatch
  sites include `ResolvedExecutionPlanV21`; V1–V20 behavior is preserved. An
  unknown schema does not become a permissive V21 or latest-version fallback.
- The public `eom_workflow.inference_transfer_materialization` module owns
  `InferenceTransferMaterializationContext`: the actual validated
  `InferenceTransferWorkflowRequest`, exact complete `RoleWorkerInput`,
  Workflow/step identity and the prepared core/full prompt hashes.
  This is a small command value for an existing adapter boundary, not a new
  independently persisted entity. Its full prompt hash is over the exact UTF-8
  text passed to `prepare_structured_workspace`, without an added newline.
- `validate_inference_transfer_workflow_plan` is the public pre-job pure
  validator: it needs the actual Workflow request and prepared prompt pins, not
  an ephemeral job or output Artifact identity. It reuses the existing execution
  plan/context helpers and independently compares policy revision/hash and
  requester-permissions SHA from that request, never from the plan itself.
  `validate_inference_transfer_materialization_plan` additionally revalidates
  the frozen context, support/protocol/no-upstream rules and exact role input.
  Copied frozen models are reparsed; a caller's nominal type or matching
  self-hash is not enough. Retain the existing persisted
  plan-row/document checks, including Workflow, preset, capacity and resolver
  pins. Terminal replay uses those checks even when no materializer runs.
- The separate source-authorization callback remains mandatory before
  execution, replay and commit. It must be composed with the actual Catalog
  actor/policy/source resolver. Callback presence, a worker-supplied actor or
  successful control-artifact resolution is not evidence of Item permission.

### Protected instruction and rubric resolution

Derive the artifact-revision allowlist only from the pinned released instruction
bundle. V21 has no reference bundle, PDF/image members, authoring evidence bundle
or Content Pack to stage. Do not add `rubric_artifact.artifact_revision_id` to the
allowlist merely because the plan mentions it.

Use the existing bundle record/manifest checks and
`resolve_control_artifact_pointer` to check exact identity, approved lifecycle,
revision owner, schema/media and manifest/member hash. After the protected
instruction manifest has been resolved, call
`validate_inference_transfer_rubric_instruction(plan, instruction)`. This helper
adds the V21-specific check: the exact `ROLE` component at
`instructions/transfer-rubric.md` equals the entire planned rubric artifact
pointer, and its SHA equals the rubric SHA. The helper does not replace the
control resolver, bundle manifest pointer or allowlist checks.

Stage that component through the existing `_materialize_member` boundary. It
already verifies the allowed revision, canonical Artifact location, bounded
regular-file bytes, exact SHA and UTF-8 Markdown before a private exclusive
workspace write. The actual JSON instruction manifest is read through the same
verified Artifact-file boundary and compared to the protected manifest document;
matching typed-record metadata alone is insufficient. Compose `AGENTS.md` using
the existing ordered instruction
composition; the rubric is included once as its `ROLE` member, not appended a
second time. Verify the actual staged `prompt.txt` bytes against the full prompt
pin. Keep the core prompt hash separate: it is bound by the prepared prompt
context, not reconstructed from the concatenated instruction bundle.

The existing `MaterializedExecution` receipt can retain the plan SHA, instruction
SHA, `AGENTS.md` SHA and invocation SHA: the immutable V21 plan already contains
the purpose-specific pins. A new generic receipt registry or duplicated profile
payload is unnecessary. Any additive receipt field must be justified by an
actual consumer, rather than repeating every plan field.

### Preflight, materialization and launch ordering

Pure schema/context and released-control metadata checks belong in the existing
Runner/Orchestrator admission boundary before submitting a job or claiming
capacity when those inputs are already available. They must produce a stable
`ControlPlaneError` for an unsupported/stale/invalid V21 plan, not leak a raw
Pydantic exception. Admission is not a reusable authorization grant: exact
source authorization and protected control checks are repeated at their
existing execution/commit boundaries.

Actual filesystem bytes can only be verified at the explicit staging boundary.
The adapter already exposes the necessary public split:

```text
prepare_structured_workspace -> materialize_execution_step -> run_prepared
         no unit started             no unit started          launch boundary
```

Use that split in the existing application composition. Set
`worker_start_attempted` only immediately before `run_prepared`, after all
preparation/materialization checks and receipt construction succeed. Merely
entering `run_resolved_structured` is not a launch attempt: that convenience
method prepares and materializes before calling `run_prepared`. Keep its frozen
`PreparedWorkerWorkspace`/`ResolvedWorkerRun` values and generic callback
boundary; it does not need a second plan parser or untyped V21 payload API.

A preparation/materialization failure after job creation is recorded through
the existing terminal failure transition, preserves its audit history, commits
no comparison result and releases a lease whose worker was never started. It
must not be classified as an uncertain external process. Errors after the real
launch boundary retain the existing uncertain-process reconciliation rules;
do not release a possibly live worker merely because an exception occurred.
No direct row correction, duplicate job identity or automatic policy widening
is permitted.

### Source-only verification and remaining installed activation

The focused source suites pass 77 tests: 16 pure context tests, 35 V21 protected
materialization tests and 26 existing materializer regression tests. They cover
V21 in both dispatch sites; absent/wrong-layer/wrong-path/
wrong-member rubric; a matching self-hash with mismatched request/profile/
Graph/policy/core/full prompt; stale persisted row; unapproved or disallowed
artifact revision; actual Markdown/prompt byte mismatch; and an unexpected
reference bundle. Assert that each prelaunch failure starts no worker unit,
commits no Artifact, and uses the existing classified failure/lease boundary.
The Orchestrator owner separately verifies that the source callback is distinct
from job binding, exact Catalog authorization is required for replay and commit,
and the launch flag is not set by workspace preparation alone. These source
checks do not claim that a live worker or installed protected Artifact ran.

Access remains indexed plan/bundle lookup and bounded ordered member iteration,
with a set for revision membership: O(members + context bytes), not a corpus
scan. The materializer/context source task adds no DB migration, new schema family,
model invocation, NAS access or runtime activation. Installed compatibility,
actual protected-artifact materialization and disposable-DB concurrency remain
separate opt-in release evidence; unit fixtures do not claim those gates PASS.
