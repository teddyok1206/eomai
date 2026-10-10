# Inference-transfer Workflow request and admission foundation

Status: source-only foundation implemented after boundary approval on 2026-10-10.
This is the next foundation after
`ITEM_INFERENCE_TRANSFER_EXECUTION_PURPOSE.md`. It does not activate a resolver,
materializer, preset, worker, endpoint or UI.

## Existing ownership and findings

- `eom_workflow.models.WorkflowRequest` is a closed legacy request model with
  authoring/analysis/support/PDF-specific fields. It must not acquire fake Pack,
  image, PDF or ticket fields for comparison.
- `workflow_request_storage_document` and
  `load_persisted_workflow_request` preserve immutable legacy requests and repair
  only documented historical null omissions. Many authoring/API consumers rely
  on the legacy loader's return type. Changing it globally to a new union would
  unnecessarily spread comparison behavior into unrelated modules.
- `create_workflow_instance` owns transaction/idempotency/history persistence,
  but currently does not match request kind to definition purpose. A generic
  request can therefore reach a newly admitted definition unless the application
  boundary rejects it before creation.
- The existing business fingerprint omits actor identity; `_active_equivalent`
  is keyed only by that fingerprint. Comparison must not reuse another actor's
  active Workflow for identical profile input. Old fingerprint semantics remain
  unchanged; the new purpose gets an actor-scoped fingerprint.
- Real source access remains Catalog's `authorize_pair` responsibility. A
  request hash, profile `APPROVED` value, supplied permission hash or frozen
  admission context is not a permission grant.

## Required design decisions

1. **Responsibility and boundary.** Define a standalone
   `InferenceTransferWorkflowRequest` for application submission. It constructs
   the already defined `InferenceTransferPairWorkerRequest` only at the local
   worker-input boundary. Runner admission matches the application request to
   `item-inference-transfer-comparison@1.0.0` and protocol `workflow-role/1.29.0`
   before Workflow, command or job creation. Actual source authorization remains
   a separately composed Catalog application boundary.
2. **Canonical source.** Exact approved source/accepted solution/Graph pins in
   the two derived profiles remain canonical. The wrapper records the comparison
   and released access-policy pins, plus an initial server-captured permission
   snapshot hash. It carries no replacement source, vector, latest pointer,
   independent permission list or model-generated authority.
3. **Identity and revision.** Existing Workflow logical identity is generated
   by the repository and stored with the authenticated operator in
   `created_actor_id`; the wire request does not choose that identity. The pair
   retains its request ID/SHA, profiles retain logical/revision/SHA and rubric
   retains its exact pointer. Wrapper SHA is a separate canonical digest, not a
   new registry or mutable request entity. Actor scoping is part of this new
   purpose's submission fingerprint, not part of the worker's source authority.
4. **Pointers and resolution.** Schema and frozen model validate full context,
   exact request/profile reference closure, nested hashes and a 64 KiB boundary.
   Reparse model dumps before admission so copied frozen values cannot bypass
   literal, length or nested field validation. Catalog must independently resolve
   both sources/reports and validate actual actor, policy, lifecycle, schema,
   media and bytes/hash before the feature is activated. Missing or revoked
   sources never resolve to latest.
5. **Primary access patterns.** Constant-time purpose/request-type dispatch;
   canonical bounded serialization; idempotency lookup; actor-scoped active
   fingerprint lookup; immutable request reload; append-only creation event.
6. **Structures and indexes.** Reuse typed frozen request/context, a small
   explicit purpose guard and the existing indexed request-hash/idempotency
   queries. Actor identity in the new fingerprint allows the existing active
   uniqueness constraint to remain sufficient. No table, queue, index, generic
   registry or Content Pack is added.
7. **Scale and complexity.** Exactly two profiles; wrapper and worker input
   each stay at most 64 KiB. Validation/serialization/hash are O(input bytes +
   claim references). New immutable request storage preserves explicit nulls
   because omission would change profile identity. Existing legacy serialization
   and fingerprints remain byte-compatible. Small application/worker values are
   intentionally materialized at their respective bounded history/input
   boundaries; full report or binary files are not copied into DB values.
8. **Transaction and concurrency.** Admission runs before the first repository
   query or write. The same existing create transaction, active unique constraint,
   IntegrityError replay and append-only event own concurrent submission. The
   server-owned context must match `actor_type=human`, a real operator-shaped ID,
   `created_actor_id`, and the wrapper's initial permission snapshot. No actor
   from the request/model substitutes for authenticated context. Current source
   access must be reauthorized on replay; the initial snapshot is audit history,
   not a durable permission grant.
9. **Dependency and adapter ownership.** The request contract module imports
   Catalog/workflow value contracts only, not SQLAlchemy or service adapters.
   A Runner-owned pure admission module accepts definition identity/protocol,
   typed request and server context. Repository calls that rule and persists the
   resulting validated values. Catalog/identity adapters supply actual actor
   authorization in the later application composition. Existing legacy API,
   retirement and authoring consumers retain their loader/type behavior.
10. **Failure, retry and idempotency.** Wrong purpose/version/protocol,
    generic-request/new-purpose, comparison-request/other-purpose, missing server
    context, actor mismatch, bad hash or oversized data fail before creation.
    The same exact actor/request reuses existing idempotency; a different actor
    cannot obtain the same active comparison Workflow through fingerprint
    deduplication. Reusing a global idempotency key with another actor conflicts.
    Legacy failed/history/released schema semantics are preserved. Permission
    changes cannot be treated as source authorization merely because the request
    stores an older permission snapshot.
11. **Simpler alternative.** Adding optional comparison fields and dummy
    authoring/PDF/ticket values to the large legacy model would create misleading
    contracts. Globally replacing every legacy loader with a union would require
    unrelated API/authoring rewrites before there is an activated comparison
    feature. A standalone model, dedicated loader and explicit repository
    purpose guard are the smallest coherent foundation; later execution
    composition can opt into a new union loader deliberately.

## Proposed wire and internal interfaces

JSON Schema 2020-12 first:
`eom://schemas/workflow/inference-transfer-workflow-request/1.0`.

Frozen wrapper fields:

- `schema_version = inference-transfer-workflow-request/1.0`
- `request_name = ITEM_INFERENCE_TRANSFER_PAIR_REQUEST`
- `execution_preset_key = item-inference-transfer-comparison`
- `comparison: PairComparisonRequest`
- `left_profile`, `right_profile: InferenceTransferProfile`
- `access_policy_revision_id`, `access_policy_sha256`
- `requester_permissions_sha256` (initial server-captured snapshot, not authority)
- `request_sha256` (wrapper digest, distinct from `comparison.request_sha256`)

No `actor_id`, role/permission list, Workflow ID, Pack, image mode, registry
intent, PDF path, source Intake batch or ticket appears in this wrapper.
`worker_request()` returns the existing typed comparison worker value without
policy or identity fields that could masquerade as worker authority.

Internal server-owned frozen context:
`InferenceTransferSubmissionContext(operator_id, requester_permissions_sha256)`.
It is not serialized in the worker request, and is not a signed authorization
receipt. The future authenticated application composition constructs it only
after actual identity/Catalog admission. A caller cannot make an unapproved
source authorized by constructing this value.

Repository changes remain additive:

- Storage and creation accept the legacy model or the new dedicated model.
- Legacy `load_persisted_workflow_request` continues returning the legacy type.
- New dedicated loader validates only the new schema; an optional explicitly
  named union loader is for future purpose-aware consumers, not an implicit
  replacement throughout the system.
- The new fingerprint includes the actual actor supplied by the application;
  old fingerprints do not change. New request snapshots are stored with their
  required explicit nulls intact.
- Creation's optional typed submission context is required only for the new
  purpose. It does not become a Boolean authorization flag and cannot replace
  the future Catalog source port.
- Creation uses `INFERENCE_TRANSFER`, not `AUTHORING`; no command or executor
  connection is activated in this foundation.

## Ownership, tests and remaining activation boundary

Implemented files:

- `schemas/workflow/inference-transfer-workflow-request-v1.schema.json`, its
  identical installed package mirror, and the public loader/validator in
  `eom_workflow.schemas`. The installed immutable schema is parsed once per
  process; public reads return isolated copies. Its file SHA-256 is
  `08fb3b9eef4488c0831ac826fe346541976b41dc4637df17dcb9f17847f9a2a0`.
- New `eom_workflow.inference_transfer_workflow` public contract module.
- New `eom_workflow_runner.inference_transfer_admission` pure application rule.
- Existing Runner repository storage/fingerprint/create boundary, narrowly
  changed for this purpose; additive stable errors if needed.
- Focused wrapper/hash/null/purpose/actor/idempotency tests. Existing legacy
  storage/fingerprint and submission suites must continue to pass unchanged.

Tests prove copied-model rejection before query/write, preserved
legacy fingerprints, exact new null-bearing snapshots, actor-local active
deduplication, cross-actor idempotency conflict, exact purpose/protocol guards
and no new queue/table or runtime Git dependency. Disposable PG concurrency
tests remain explicitly opt-in and are separate from pure source tests.

Source regression on 2026-10-10: 173 focused tests PASS across the new wrapper,
legacy persistence/fingerprint/start/admission, worker/V21/preparation and
dependency suites; strict mypy for the nine changed/new source and test files,
Ruff and diff checks PASS. One broad invocation initially used a nonexistent
test filename, collected no tests, and was corrected before this PASS report.
The new disposable PostgreSQL test file is
`tests/integration/test_inference_transfer_workflow_admission.py`: actor-local
coexistence/replay, global-key conflict, actual unique constraints and two-worker
same-key creation. It requires the existing database/user/schema/head marker
guard and never falls back to an ambient database. Ordinary fixtures use outer
rollback; the concurrency seed/results are explicitly disposable-only committed
metadata and remain until the entire guarded database is removed. Its live test
execution evidence is recorded by the owning test runner, not inferred here
from unit PASS or unconfigured opt-in SKIP.

Not connected by this task: API/GUI/CLI comparison submission, actual Catalog
identity/permission snapshot composition, V21 resolver, preset/bootstrap,
materializer, runner execution/preparation and live model canary. Until those
are verified, activation remains `UNSUPPORTED_PENDING_COMPATIBLE_RELEASE`.
The new definition must not be imported/activated for production merely because
its source admission and request contract exist.
