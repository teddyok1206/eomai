# Inference-transfer resolver and protected preset composition

Status: **SOURCE_IMPLEMENTATION — resolver, released-instruction helper and
Runner purpose composition**. The protected bootstrap proposal below is a
separate source task; none of these paths is installed or activated functionality.
This note publishes no
controls, selects no operating model and authorizes no live worker. The original
design and released support/PDF/authoring meanings remain unchanged. It extends
`ITEM_INFERENCE_TRANSFER_EXECUTION_PURPOSE.md` without editing that concurrently
maintained implementation record.

## Verified boundaries and current gaps

- `execution_resolver.lock_current_execution_preset` already locks the logical
  preset with `FOR UPDATE` and validates the exact released V1 revision, owner,
  protocol and document/record SHA. It is suitable for the first V21 resolution.
- `ResolvedExecutionPlanRecord` already has a real Workflow foreign key and a
  unique `workflow_id`; the existing step table has a `(plan_id, step_key)` key.
  No new plan table, queue, index or migration is required for this task.
- The generic `record_resolved_execution_plan` and its dependency value require
  authoring Content Pack fields. They cannot record V21 honestly without a
  separate Pack-free purpose path. Changing those predecessors or inventing a
  Pack is not proposed.
- The old customer-support resolver/bootstrap fixes a historical model/effort,
  `workflow-role/1.22.0` and diagnostic semantics. It must not be repurposed for
  `compare_pair` / `workflow-role/1.29.0`.
- `preset_model_options` already computes fresh native-catalog intersected with
  reviewed capability and admitted role/pool membership, including `support`.
  `non_live_invocation_cases` checks adapter arguments without starting a model.
  `validate_model_selection` additionally requires an authoring/review-only
  model successor; that separate invariant does not admit a new support preset.
- `ControlArtifactPublisher.publish_bytes` supports safe nested logical names.
  Legacy bootstrap helpers normally publish a basename such as
  `customer-support.md`; V21 instead requires the Artifact logical name itself
  to be `instructions/transfer-rubric.md`, not just its destination path.
- V21 materialization, actual wrapper/policy/input/prompt binding, prelaunch
  ordering, the dedicated first-plan resolver and Runner purpose composition
  are source-tested. Purpose preset publication and the source composition are
  not yet an installed or activated path.

## Required 11-point design

1. **Responsibility and boundary.** Add one purpose-specific infrastructure leaf
   inside Orchestrator, `inference_transfer_resolution.py`. It resolves and
   persists one V21 plan using existing control/plan models and public services.
   Runner owns the actual persisted Workflow request, definition and operator;
   Catalog owns exact source authorization. The resolver inserts no Workflow,
   changes no foreign component table, launches no worker and commits no Item.
2. **Canonical source.** The actual schema-validated immutable
   `InferenceTransferWorkflowRequest`, released definition, prepared core/full
   prompt, exact released preset/instruction bundle and registered control
   Artifact members are authoritative for this boundary. A supplied actor,
   callback, candidate string or the plan itself is not an authorization proof.
3. **Identity and revision.** V21 retains the logical Workflow/plan/preset IDs,
   exact preset/capacity/instruction revisions and independent hashes. Resolve
   the preset's current pointer only for first creation. Historical reuse pins
   the stored V21 plan without consulting current or replacing a model, rubric,
   Graph, access policy or source revision.
4. **Pointers and checks.** Use the existing protected control pointer resolver
   for approved lifecycle, revision owner, schema/media/member and hash checks.
   Build the rubric Artifact pointer from the pinned released instruction
   manifest, not arbitrary caller input. Call the existing
   `validate_inference_transfer_rubric_instruction` and
   `validate_inference_transfer_workflow_plan` after constructing the document.
   The wrapper supplies policy revision/hash and captured permissions SHA
   independently; the plan never provides its own expected values. Materializer
   independently verifies actual manifest/Markdown and staged input/prompt bytes.
5. **Access patterns.** Indexed Workflow/plan/preset lookup, one preset-current
   lock, one bounded role/instruction membership lookup, six-slot capability
   metadata and ordered one-step persistence. No corpus or all-pairs scan.
6. **Structures and indexes.** Reuse plan/preset unique constraints, existing
   Workflow FK and step primary key. Map instruction members by exact relative
   path and model/effort pairs by a set. Keep one `compare_pair` step and a
   frozen small resolution context. No parallel registry, cache or queue.
7. **Scale and complexity.** One request has two bounded profiles and one
   selected candidate. Work is O(control members + request bytes + admitted
   slot metadata); space is the same bounded metadata. Persist pointers and
   small existing plan JSON only, not reports, PDF/PNG or embedding corpus bytes.
8. **Transaction and concurrency.** Runner owns Workflow creation/idempotency
   and holds its existing Workflow/command fence while calling the resolver in
   the same transaction. First resolution locks the current preset, validates
   it and inserts the plan plus one step atomically. The existing plan unique
   key is a second guard, not permission to create two plans or catch arbitrary
   integrity failures as success. Concurrent resolution must replay the exact
   winner or return a classified conflict. Artifact publication remains the
   publisher's separate advisory-lock/idempotent commit boundary; publication
   cannot be described as atomically rolling back with a later DB transaction.
9. **Dependency and ownership.** Public pure workflow validators retain all
   purpose/context rules. The leaf resolver owns only orchestration of those
   rules and Orchestrator persistence. A single purpose-control validation
   helper feeds both new-plan construction and exact replay; the recorder is
   private and accepts only that admitted plan, not an independent untrusted
   document requiring duplicated role/policy rules. No cross-package private
   helper imports or changes to legacy authoring/PDF/support contracts.
10. **Failure, retry and idempotency.** Missing/unpublished/stale controls,
    changed wrapper/prompt/policy pins, unsupported model/effort, missing exact
    rubric and incompatible protocol fail with stable `ControlPlaneError`
    before job/claim. Stored row, canonical plan and step projection must agree;
    inconsistent history is not repaired. A bootstrap retry resumes exact
    publisher history and exact draft/release policy, not a new identity or
    rewritten failed receipt. Source revocation remains a separate mandatory
    Catalog check before execution, replay and commit.
11. **Simpler alternative.** Reusing the old support resolver is smaller but
    mislabels purpose and fixes an old model; adding V21 to the authoring
    recorder forces a fake Pack. A single-purpose leaf adapter plus the existing
    pure validators and control publisher is the smallest honest alternative.
    A new execution framework or generic plugin system is unnecessary.

## Proposed APIs and ownership

The resolver API below is source-implemented. Its name is not proof that an
installed runtime exposes this execution purpose.

```text
Orchestrator leaf: inference_transfer_resolution.py

resolve_inference_transfer_execution_plan(
    session,
    workflow_id,
    workflow_definition_version,
    workflow_definition_sha256,
    workflow_role_schema_version,
    workflow_request: InferenceTransferWorkflowRequest,
    core_prompt_sha256,
    prompt_sha256,
    resolved_at,
) -> ResolvedExecutionPlanV21

_record_validated_inference_transfer_plan(session, admitted_plan)
    -> ResolvedExecutionPlanRecord
```

The Runner must obtain all inputs from its actual persisted/validated Workflow
and Catalog-prepared prompt; do not derive expected policy/permissions from a
stored plan. The resolver performs no source permission impersonation. Exactly
one `support` policy/candidate is required, with the existing `customer-support`
pool, no reference bundle, bounded timeout, read-only/disabled-network and
general knowledge `DENY`. Candidate model/effort are data from reviewed controls,
not constants, guessed defaults or an automatic fallback list.

Reuse `lock_current_execution_preset` only on first resolution. A private
purpose-control validator resolves the preset/instruction, checks exact policy
and step bindings and uses `preset_model_options` for a fresh available selected
candidate. The same validator checks exact pinned revisions on replay, without
following current. It does not silently substitute a candidate if availability
changes. Runtime claim/compatibility guards remain responsible for whether an
actual worker can currently run that exact plan.

Do not grow the generic Pack-required recorder contract. A private persistence
function in the leaf writes only existing `ResolvedExecutionPlanRecord` and
`ResolvedExecutionPlanStepRecord`, with `graph_snapshot_revision_id` from the
full pinned Graph and `evidence_bundle_revision_id=None`. Its only rule is
immutable insert/exact replay; purpose/preset/role rules run once through the
authoritative validator. Verify exact row/plan/step closure on replay.

The public `control_service.resolve_released_instruction_bundle(session, pointer)`
shares released bundle-pointer/manifest schema, identity, revision and hash
checks between the resolver and V21 materializer. It reuses existing approved
Artifact metadata resolution. Purpose-specific rubric membership is checked
before resolving component pointers, preserving stable wrong-rubric failures.
Actual manifest/Markdown bytes are still verified only by protected
materialization. V1–V20 materializer dispatch and the generic Pack-required
recorder are unchanged. This is one existing infrastructure boundary with two
concrete consumers, not a new registry or framework.

## Source-only implementation evidence

- `inference_transfer_resolution.py` exposes the resolver above and a private
  admitted-plan recorder. First creation retains `FOR UPDATE`; replay checks
  all stored plan-row and step projections without following current.
- Public wrapper/policy/permission/core/full-prompt and rubric validators are
  reused. Fresh availability is checked through `preset_model_options`; empty
  or changed availability fails explicitly without a guessed replacement.
- Only existing plan/step rows are inserted in the caller-owned transaction.
  Runner's Workflow fence and the existing Workflow FK/unique constraint are
  retained. A named `uq_execution_plan_workflow` race becomes a conflict, never
  a successful receipt; other integrity failures propagate for caller rollback.
- Focused source tests plus legacy materializer/resolver/model-selection
  regressions: **186 PASS** in the explicit `eom-core` environment. Tests use
  synthetic controls/fake sessions and temporary protected staging only.
  Ruff check/format and strict mypy cover all three modified source files.
- This stage ran no production/disposable database, NAS access, model inference,
  control publication, runtime deployment or activation. Actual database
  concurrency and installed purpose execution remain separate pending gates.

## Protected bootstrap: prepare and release are separate gates

Propose a small closed JSON Schema 2020-12 bootstrap manifest **before** behavior,
mirrored as an installed workflow resource, plus its frozen model. It declares
the fixed purpose/protocol/member paths, reviewed UTC/source identity, exact
capacity revision/hash, rubric logical/revision/hash pointer and a typed
`ModelCandidate`. It does not pin a model name as a schema Literal, carry auth
secrets or allocate another slot. Existing capacity and actual fresh capability
records are inputs; do not manufacture READY/auth/capability observations.

An `inference_transfer_bootstrap.py` leaf can use public
`ControlArtifactPublisher.publish_bytes`, `record_bundle_revision`,
`publish_bundle_revision`, `create_execution_preset_draft`,
`record_execution_preset_evaluation` and `release_execution_preset`:

1. Validate the exact published Workflow definition/protocol, capacity and
   supplied model/effort using actual fresh native/reviewed role availability.
2. Publish reviewed Platform Markdown and the Role rubric. The latter uses both
   logical name and component relative path
   `instructions/transfer-rubric.md`, schema
   `eom://schemas/workflow/instruction-member/1.0`, media `text/markdown`, and
   exact bytes/SHA equal to the requested rubric pointer. Use purpose-specific
   immutable publication keys and source provenance; never edit old controls.
3. Publish/register the exact instruction manifest through existing APIs and
   create only the dedicated V1 preset draft under
   `item-inference-transfer-comparison`, protocol `workflow-role/1.29.0`.
4. Record only checks actually executed. Fresh candidate mapping and
   `non_live_invocation_cases` can produce honest NON_LIVE adapter/contract
   evidence with `quality_score_permille=None`; they are not model inference,
   scientific comparison quality or entitlement evaluation. A pytest PASS or
   copied legacy `_evaluation_report` is not a measured model evaluation.
5. Release only with exact accepted technical evidence and a recheck of fresh
   candidate/control pins inside the existing release transaction/lock. Keep
   preparation/draft publication separate if required evidence is absent.
   Retain published immutable Artifacts when a later release fails; no cleanup
   by DB-row mutation, historical success rewriting or implicit current swap.

An eventual CLI is a thin explicit wrapper. It must not silently run bootstrap
when a comparison request encounters `CONTROL_PRESET_NOT_PUBLISHED`, and must
not publish or activate a draft just because source unit tests passed.

## Verification and remaining gates

Source/fake-session tests: exact first-plan pins; actual wrapper policy/permission
and prompt mismatch; absent/extra/wrong rubric; unavailable candidate; missing
released preset/protocol/capacity; retired/stale control; replay after current
changes; corrupt persisted plan/step; stable conflict/error codes; no Pack/no
model-name constant; actual nested rubric logical name; publication replay; and
honest evaluation labels with no manufactured capability records.

Disposable PostgreSQL opt-in tests: real Workflow FK, one concurrent immutable
plan/step, replay identity, current-preset lock/release race and exact bootstrap
draft/release history. Tests must not use the production DB. Publisher filesystem
and actual installed compatibility remain separately scoped opt-in gates.

Actual worker comparison and human transfer judgments remain **NOT_EVALUATED**
by these source/non-live adapter checks. New controls, runtime migration,
deployment, activation and any usage-consuming canary require their own explicit
scope; this proposed note executes none of them.

## Next proposal: narrow Runner purpose composition

This section is **PROPOSED**, not an implemented execution path. Source reading
identified three concrete legacy assumptions in `engine._execute_agent`:
generic persisted-request loading, unconditional `content_pack` access and
authoring-material preparation. The existing terminal manifest also calls every
non-knowledge-analysis result a `registration`. A pair-comparison result must
not inherit that Item-registration meaning.

The approved source composition is:

1. Load the exact wrapper with the existing
   `load_persisted_inference_transfer_workflow_request` for the dedicated
   definition, preserving the generic legacy loader's behavior for old purposes.
   Validate the stored definition and actual `created_actor_id`, not the command
   processor's system actor or a model-provided identity.
2. Add one optional purpose execution port to Runner. At the execution-selection
   point, an `InferenceTransferWorkflowRequest` invokes that port; all legacy
   requests continue through existing prompt/material preparation and executor.
   An absent port reports a stable purpose-unavailable error before any job or
   worker claim. Do not add synthetic `content_pack` or `item_brief` properties.
3. The purpose leaf adapter prepares the existing bounded pure worker comparison
   prompt, obtains actual Catalog authorization for both exact profiles and uses
   the resolver in Runner's existing fenced transaction. Record only the small
   exact plan/core/full-prompt pins in the step/Workflow context. Actor and
   authorization information come from installed Identity/Catalog composition;
   a request hash or callback's presence is not an authority proof.
4. The leaf invokes existing `Orchestrator.submit_workflow_role` with the exact
   worker request, wrapper/core/full pins, one result schema and a mandatory
   Catalog source reauthorization callback. Preserve the existing platform-job
   binder as a separate callback, current step/attempt identity and idempotency
   key. Supply a Runner-owned fenced-transaction callable rather than importing
   an engine-private transaction helper or bypassing command lease fencing.
5. Reuse the existing execution-result value, `QUEUED` capacity-command path,
   step success/failure transitions, Artifact pointer construction,
   `_move_after_agent` and terminal transitions. Do not duplicate those state
   machines in the leaf. Comparison runs no authoring classification,
   image materialization, rework directive or Item registration.
6. Keep the result value/protocol in a small public Runner interface module if
   required to avoid an engine↔leaf import cycle. Existing engine imports can
   re-export the unchanged value for legacy compatibility. This extraction has
   two real adapter consumers and adds no DI or plugin framework.
7. For this purpose only, terminal output records the validated comparison
   Artifact pointer under `comparison_result` and leaves `registration=None`.
   Preserve old terminal meanings. If this shape crosses an existing API/read
   boundary, define its additive schema before writing it; do not silently expose
   an arbitrary new dictionary as a public contract.

Source acceptance should use fake purpose/source/Orchestrator ports for absent
port, forged/stale wrapper, actual-actor separation, policy/permission mismatch,
revocation before launch/replay/commit, same-key replay, `QUEUED` binding,
terminal comparison-vs-registration meaning and legacy executor selection.
Guarded PostgreSQL tests must use only a disposable database for actual
Workflow/plan/step identity and lease fencing. No source-only test proves that
the composition or protected controls are installed, authorized or activated.

### Runner source implementation and authority closure

The dedicated `PlatformInferenceTransferExecutor` implements the optional
`InferenceTransferRoleJobExecutor` port. Composition constructs it with the same
Orchestrator and current actor authorizer as the legacy executor, plus the
existing Catalog exact-profile source adapter. This construction activates no
preset, imports no model and creates no command, worker or Item.

The leaf locks and validates the actual stored Workflow, definition and step in
the Runner-owned fenced transaction. It loads the exact dedicated wrapper,
checks canonical definition key/version/hash against its row and Workflow,
requires the actual human Operator creator and the `compare_pair` agent step,
then authorizes both exact profiles before prompt preparation and V21 resolution.
Only plan identity and core/full/wrapper prompt hashes are added to existing
metadata. Historical replay neither repairs stale request/prompt/plan pins nor
follows a new current preset.

The initial `requester_permissions_sha256` remains an immutable audit pin bound
by the wrapper and V21 validators. It is not a digest of mutable current
permissions: adding a permission does not rewrite or invalidate old history.
Current Identity permission and Catalog source authorization are rechecked with
the actual creator before preparation and by the separate Orchestrator owner
callback at replay/prelaunch/commit. An Identity denial inside that callback is
normalized to the existing ValueError owner boundary so the platform records
its failed-job state; arbitrary programming exceptions are not caught or called
authority failures.

`RoleExecutionResult` and the exact running-step job binder/result projection
are small public Runner modules used by both real executors. The generic
authoring/support/PDF path keeps its original prompt, material and registration
semantics. The dedicated comparison branch reuses existing `QUEUED` retry
commands, step/workflow transitions and Artifact pointer handling. Its final
internal manifest contains one validated `comparison_result` pointer and no
Item registration. The existing public Workflow DTOs do not expose that
internal manifest; a future public comparison result must first define its
closed contract.

Source-only tests cover current authority versus the initial audit pin,
revocation at every owner callback, actual-actor separation, stale/forged
context, canonical definition row drift, missing purpose adapter, the unchanged
legacy executor selection, common success/queue/failure handling and comparison
terminal meaning. `test_inference_transfer_plan_persistence.py` additionally
defines eight opt-in cases using the existing marker-guarded owner DB fixture:
native Workflow FK, exact plan/step replay, immutable UPDATE/DELETE, concurrent
unique conflict and the real Runner lease fence. Its candidate availability and
control file metadata are explicitly synthetic; collect/source PASS is not a
PostgreSQL execution or published-control acceptance.

## Bootstrap manifest input identity decision

The reviewed bootstrap manifest does not predetermine Artifact or Artifact
revision UUIDs that the existing publisher has not issued. Each reviewed
instruction is a small frozen file value: exact source-commit/tree provenance,
expected raw-byte SHA, fixed logical name/relative member path, schema and media
type. Platform uses `instructions/platform.md`; the role rubric uses
`instructions/transfer-rubric.md`. The rubric's existing domain logical ID,
revision ID and hash remain separate from the actual publisher-produced
`ControlArtifactPointer`. Its expected hash must match the reviewed role member.
The publisher output, not this input manifest, establishes the actual Artifact
identity and immutable revision.

Capacity is an existing native control document in
`WorkerCapacityPolicyRevisionRecord`, with a logical capacity ID, exact revision,
schema version and canonical content SHA. This record has no Artifact pointer;
the bootstrap manifest must not invent one. The owner resolves this typed pin
and checks released lifecycle, exact canonical bytes and the compatible existing
pool before any draft/release. Review timestamps and source provenance are audit
values, not authentication or release authorization. The selected typed
`ModelCandidate` similarly records a reviewed candidate without asserting fresh
availability, entitlement, invocation success or educational quality.
