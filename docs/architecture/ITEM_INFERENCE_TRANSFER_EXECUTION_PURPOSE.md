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
    purpose, provenance and permissions. A standalone V21 plan and two-step
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
