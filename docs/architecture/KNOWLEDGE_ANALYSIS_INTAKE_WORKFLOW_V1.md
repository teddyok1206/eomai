# Knowledge Analysis Intake and Workflow V1

Status: `SOURCE_COMPLETE`. The Phase 7 producer, orchestration, artifact, review, persistence, API,
and operator boundaries are implemented and verified in source and a disposable PostgreSQL
harness. Production migration, deployment, live Codex execution, and graph publication remain
separately authorized gates.

Date: 2026-08-23 UTC

Related contracts and decisions:

- [`CODEX_KNOWLEDGE_CONTROL_PLANE_IMPLEMENTATION_PLAN.md`](CODEX_KNOWLEDGE_CONTROL_PLANE_IMPLEMENTATION_PLAN.md)
- [`CODEX_KNOWLEDGE_PROTOCOL_COMPATIBILITY.md`](CODEX_KNOWLEDGE_PROTOCOL_COMPATIBILITY.md)
- [`CODEX_EXECUTION_RESOLUTION_AND_MATERIALIZATION.md`](CODEX_EXECUTION_RESOLUTION_AND_MATERIALIZATION.md)
- [`EDUCATION_KNOWLEDGE_ITEM_GRAPHRAG.md`](EDUCATION_KNOWLEDGE_ITEM_GRAPHRAG.md)
- [`CODEX_SESSION_PRESETS_AND_CAPACITY.md`](CODEX_SESSION_PRESETS_AND_CAPACITY.md)

## 1. Decision Summary

Phase 7 adds one versioned, single-agent knowledge-analysis workflow to the existing Orchestrator.
It uses the existing `support` pool and fixed `slot05`; it does not add slot 06. The worker receives
one exact immutable source plus reviewed instructions in a fresh, read-only, network-disabled
workspace. It returns one bounded structured proposal. Only the Orchestrator may validate,
materialize, and commit proposal members to canonical Artifact storage.

The following decisions are fixed:

1. The existing `knowledge-analysis-request/1.0`, `knowledge-analysis-result/1.0`, shared knowledge
   types, and every historical workflow-role schema remain byte-identical.
2. Additive V2 analysis contracts separate a worker-local proposal from a canonical accepted result.
3. A worker never invents a canonical Artifact ID, Artifact Revision ID, or storage path. Those IDs
   are allocated by the Orchestrator before execution and verified at commit.
4. Large normalized Markdown and graph proposal collections are Artifact members, not PostgreSQL
   JSON payloads. Database rows contain only identities, state, counts, hashes, and typed pointers.
5. Content Intake's existing `ContentIntakeAnalysisRecord` remains the manual Content Pack mapping
   proposal. Knowledge analysis gets its own run, review, and event records.
6. There is no fake Item Content Pack. Knowledge analysis uses a V2 resolved execution plan that
   pins the request and source instead of a Content Pack release.
7. The workflow has one `support` agent step followed by a terminal step. Review and corpus
   acceptance are owned by the knowledge-analysis application service, not by worker-to-worker
   communication or Catalog repair logic.
8. A proposal Artifact is not a published graph delta. A separate immutable acceptance record and
   accepted-result Artifact pointer make it eligible for Phase 8 publication.
9. General model knowledge is either denied or recorded as auxiliary and unattributed. It never
   becomes a citation, anchor, or source pointer.
10. Retry reuses the same immutable request and creates a new workflow attempt/job; it never mutates
    a prior proposal or silently substitutes a newer source revision.
11. The workflow permits one step attempt and zero rework cycles. A retry is a new analysis run with
    an explicit predecessor pointer, never an implicit second execution inside the failed workflow.

## 2. Responsibility and System Boundary

```text
ADMIN-only application command for the initial rollout
  -> KnowledgeAnalysisApplicationService
      -> validates source/preset/request and records KnowledgeAnalysisRun
      -> creates versioned knowledge-analysis WorkflowInstance
  -> Workflow Runner
      -> resolves exact Execution Preset Revision and analysis execution plan
      -> capacity/auth/capability admission (`KNOWLEDGE_ANALYSIS`, max 1)
  -> Orchestrator
      -> materializes one pinned source + instruction/reference Markdown
      -> launches fixed slot05 support worker, fresh and one-shot
      -> validates worker-local proposal
      -> splits accepted local values into a proposal Artifact file set
      -> commits the proposal Artifact Revision to NAS
  -> KnowledgeAnalysisApplicationService
      -> applies deterministic risk policy
      -> auto-accepts or opens immutable human review
      -> publishes a small accepted-result Artifact after acceptance
  -> Phase 8 graph publisher
      -> consumes accepted-result pointers only
```

Ownership follows the existing dependency direction:

| Concern | Owner |
| --- | --- |
| analysis domain schemas and frozen models | `packages/catalog_contracts` |
| workflow support input/result protocol | `packages/workflow` |
| preset resolution, source materialization, worker launch, Artifact commit | `services/orchestrator` |
| workflow lifecycle and one-agent advancement | `services/workflow_runner` |
| run/review/event persistence and source resolution | `services/catalog_service` |
| HTTP DTOs and permissions | `packages/api_contracts`, `apps/application_api` |
| operator commands | `apps/eomctl` |
| initial administrator read/write surface | ADMIN-only `apps/application_api` routes |

A dedicated GUI surface is not required for the Phase 7 source gate and remains an additive later
adapter. It must call the same application commands rather than reimplementing lifecycle rules.

Workers do not import application, persistence, Catalog, NAS, Slack, or another worker package.
Domain and contract packages do not import infrastructure adapters.

## 3. Canonical Sources and Source Eligibility

There is currently no implemented `Document` or `DocumentRevision` aggregate. Phase 7 must not
invent a path-shaped document identity or pretend that a Content Intake row is a Document Revision.
The initial source union therefore names only boundaries that currently exist.

### 3.1 Content Intake source file

Canonical identity:

```text
ContentIntakeBatch.intake_batch_id
  + ContentIntakeSourceFile.source_file_id
  + source Artifact.logical_artifact_id
  + source ArtifactRevision.revision_id
  + exact member path, media type, size, and SHA-256
```

Eligibility requires:

- the batch and source-file rows exist and agree;
- the source-file Artifact and Artifact Revision exist, are approved, and agree;
- the Artifact manifest identifies exactly one matching member;
- member path, media type, byte size, and SHA-256 all match the source-file row;
- the batch is not `RECEIVED`, `REJECTED`, `SUPERSEDED`, or `FAILED`;
- the source is within the analysis media/size allowlist;
- the member is a regular non-symlink beneath the canonical Artifact root.

The existing `ANALYSIS_PENDING` state remains the Content Pack intake mapping state. A knowledge
analysis request does not advance or overwrite that state.

### 3.2 Approved Item Revision

Canonical identity:

```text
Item.item_id
  + ItemRevision.item_revision_id
  + exact ITEM_CONTENT component Artifact Revision
  + exact component member path, media type, schema, and SHA-256
```

Eligibility requires the immutable revision to be `APPROVED`. It need not be the Item's current
revision: historical approved Item Revisions are valid graph sources when explicitly pinned. The
resolver must not replace a requested historical revision with `current_revision_id`.

### 3.3 Future Document Revision

A later additive source variant may point to a real `Document` and `DocumentRevision` aggregate.
Until that domain exists, `DOCUMENT_REVISION` is not accepted merely because an Artifact contains a
PDF or Markdown file. The initial implementation exposes `CONTENT_INTAKE_FILE` and
`APPROVED_ITEM_REVISION` only.

## 4. Additive Protocol Families

### 4.1 Historical preservation

The following remain immutable:

- `knowledge-analysis-request/1.0`;
- `knowledge-analysis-result/1.0`;
- `knowledge-types-v1`;
- `resolved-execution-plan/1.0`;
- `workflow-role/1.0.1` through `workflow-role/1.3.0`;
- all existing generic item workflow definitions and Content Pack releases.

Regression tests pin canonical and packaged bytes and the historical workflow protocol bundle
hashes. An additive reader may read V1, but new Phase 7 writes use the contracts below.

### 4.2 Knowledge analysis request V2

`knowledge-analysis-request/2.0` contains:

- immutable `analysis_request_id`;
- discriminated `source` pointer (`CONTENT_INTAKE_FILE` or `APPROVED_ITEM_REVISION`);
- exact Execution Preset logical ID, revision ID, and content hash;
- exact expected worker proposal and accepted-result schema refs;
- optional prior Graph Snapshot pointer;
- bounded requested output kinds;
- `general_knowledge_mode`;
- immutable risk-policy revision ID;
- UTC creation timestamp and canonical request hash.

The request hash excludes only its own hash field. Duplicate requested outputs and incoherent source
pointer families fail before persistence.

### 4.3 Worker-local proposal

`knowledge-analysis-worker-proposal/1.0` is a bounded, ephemeral value embedded in the workflow role
result. It contains:

- normalized Markdown text;
- source anchors;
- proposed nodes, edges, and claims;
- component observations;
- unresolved ambiguities;
- provenance flags indicating whether auxiliary general knowledge influenced reasoning;
- completion timestamp.

It contains no canonical Artifact pointer or filesystem path. Initial total serialized output is
bounded below the fixed worker result limit. The authoritative schema has tighter element/string
limits than the broad V1 placeholder contract. The worker output schema projection may omit Codex-
unsupported assertion keywords, but the canonical schema and frozen model are always applied after
execution.

### 4.4 Proposal receipt

`knowledge-analysis-proposal-receipt/1.0` is the small value stored in
`ArtifactRevisionRecord.result`. It points to members of one committed proposal Artifact Revision:

```text
proposal-receipt.json
normalized/document.md
normalized/anchors.jsonl
normalized/nodes.jsonl
normalized/edges.jsonl
normalized/claims.jsonl
normalized/components.jsonl
normalized/ambiguities.jsonl
```

Every member pointer carries the same Artifact and Artifact Revision identity plus its exact schema,
media type, member path, size, and SHA-256. The receipt includes counts and a content-set hash over
the ordered member descriptors. It does not recursively claim its own file hash.

### 4.5 Accepted result V2

`knowledge-analysis-result/2.0` is a small immutable acceptance manifest. It contains:

- request and source identities/hashes;
- proposal Artifact/Revision pointer and proposal content-set hash;
- review policy and optional human decision Artifact pointer;
- acceptance mode (`AUTO_POLICY` or `HUMAN_APPROVED`);
- counts and confidence/risk summary;
- exact accepted-result content hash and UTC acceptance timestamp.

It duplicates no Markdown, node, edge, claim, image, table, or equation payload. Phase 8 accepts only
this V2 result in `ACCEPTED` state.

### 4.6 Workflow protocol and execution plan

New writes use:

- `workflow-role/1.4.0`;
- `knowledge-analysis-proposal-result@1.0` for role `support`;
- `resolved-execution-plan/2.0` with workload class `KNOWLEDGE_ANALYSIS`;
- workflow definition `knowledge-analysis@1.0.0`.

The V2 plan reuses the existing plan/step persistence but replaces the mandatory Content Pack
dependency with one exact analysis request and source pointer. It still pins:

- workflow definition key/version/hash;
- preset logical/revision IDs and hash;
- capacity policy revision;
- selected model and reasoning effort;
- instruction/reference bundle revisions and hashes;
- worker pool, timeout, sandbox, network, and general-knowledge modes;
- request ID/hash and source Artifact Revision/hash;
- resolver version and plan hash.

Item workflows continue writing `resolved-execution-plan/1.0`. Materialization dispatches by schema
version and never rewrites old plans.

## 5. Workspace and Local Result Boundary

The Orchestrator prepares a fresh slot05 workspace under the existing private worker root:

```text
worker-input.json
worker-result.schema.json
prompt.txt
codex-invocation.json
AGENTS.md
instructions/platform.md
instructions/knowledge-analysis.md
references/...                 # optional reviewed Markdown only
source/<normalized-name>       # exactly one pinned source member
```

Materialization checks, in order:

1. resolve the exact V2 plan and verify its canonical hash;
2. resolve the exact request, preset, bundles, and source records;
3. require every resolved Artifact and Artifact Revision to be approved and mutually consistent;
4. require a normalized relative destination beneath an allowlisted root;
5. open canonical sources without following symlinks;
6. require regular files, bounded size, matching media type, byte count, and SHA-256;
7. copy into the private workspace with reviewed owner/group/mode;
8. verify the copy hash before worker launch;
9. record only bounded, path-free materialization evidence in events.

The fixed worker remains `--ephemeral --ignore-user-config --strict-config`, read-only sandbox,
network disabled, no previous Codex conversation, no database access, and no NAS access.

## 6. Proposal Validation and Artifact Commit

The Orchestrator validates the local proposal before any canonical commit:

- JSON Schema 2020-12 and frozen-model validation;
- exact job/workflow/step/artifact identifiers;
- serialized size and collection-count limits;
- unique anchor, node, edge, claim, component, and ambiguity IDs using sets/maps;
- every edge endpoint resolves to a proposed node;
- every anchor reference resolves to a source anchor;
- every anchor pins the analyzed source revision, Artifact Revision, member path, and excerpt hash;
- self-edges and unknown enum values fail;
- normalized Markdown is valid UTF-8 and contains no prohibited control bytes;
- component observations have compatible source/member media;
- auxiliary model knowledge cannot supply an anchor or be labeled source evidence;
- deterministic member ordering and canonical JSON Lines serialization;
- no symlink, absolute path, `..`, duplicate member, or unlisted output is accepted.

Validation uses dictionaries and sets, making relationship validation `O(n + e)` time and `O(n)`
memory for `n` proposal entities and `e` edges. It does not repeatedly scan lists.

After validation, the Orchestrator writes the normalized member file set to its own staging area,
computes member hashes, creates the pointer-only proposal receipt, then atomically commits the file
set through the existing Artifact adapter. A database transaction records the Artifact rows and
job success only after the final Artifact directory is verified. A commit failure leaves the job
failed and creates no accepted analysis result.

## 7. Knowledge Analysis Run Lifecycle

Knowledge analysis uses an explicit state machine rather than Content Intake state reuse:

```text
REQUESTED
  -> RESOLVED
  -> QUEUED
  -> RUNNING
  -> VALIDATING
  -> AUTO_ACCEPTED -> ACCEPTED
  -> NEEDS_REVIEW -> ACCEPTED | REJECTED

REQUESTED|RESOLVED|QUEUED|RUNNING|VALIDATING|NEEDS_REVIEW
  -> FAILED | CANCELLED
```

`AUTO_ACCEPTED` is an event, not a long-lived row state. Terminal states are `ACCEPTED`, `REJECTED`,
`FAILED`, and `CANCELLED`.

The run row stores only:

- analysis request ID/hash and canonical request JSON (bounded);
- source-kind indexed columns and immutable source pointers;
- workflow, plan, job, preset, and policy pointers;
- proposal and accepted-result Artifact pointers/hashes;
- state, counts, timestamps, error code, and optimistic lock version.

The append-only event table uses `(analysis_run_id, sequence)` uniqueness. Human review is a separate
immutable record with a unique run ID, decision, actor, policy revision, decision Artifact pointer,
and UTC timestamp. Reviews never update proposal bytes.

## 8. Risk Policy and Human Review

The first deterministic policy sends a proposal to review when any of these holds:

- a blocking ambiguity is present;
- an edge or claim falls below the policy's minimum confidence;
- auxiliary unattributed knowledge influenced a source-dependent claim;
- the source class or source-lifecycle policy requires review;
- the proposal reaches a configured count/size safety threshold;
- a component/media observation cannot be deterministically classified.

The policy revision is immutable and pinned in the request. Auto-acceptance is allowed only when no
review rule fires. A human can approve or reject, never edit, a proposal. Corrections require a new
request/attempt with an explicit predecessor pointer.

## 9. Workflow State Extension

The generic workflow engine gains an additive `KNOWLEDGE_ANALYSIS` stage. The new workflow is:

```text
analyze (agent, role=support, result=knowledge-analysis-proposal-result@1.0)
  -> completed (terminal)
```

Required transitions are:

```text
Workflow: REQUESTED -> RUNNING -> COMPLETED
Stage:    KNOWLEDGE_ANALYSIS -> COMPLETED
```

Historical item transitions remain unchanged. Initial stage derives from the validated request
kind, not a string convention in an adapter. The terminal manifest calls the final pointer an
`analysis_proposal`; it does not populate `registration` or `item_registration`.

The support role submission uses workload class `KNOWLEDGE_ANALYSIS`, existing pool `support`, and
slot05. Capacity admission enforces both host-wide maximum active Codex processes and
`max_active_knowledge_analysis = 1` in one transaction.

## 10. Access Patterns, Data Structures, and Indexes

Expected initial scale is up to 10,000 source revisions and tens of thousands of analysis attempts;
proposal payloads remain outside PostgreSQL.

| Access pattern | Structure/index | Expected cost |
| --- | --- | --- |
| idempotent request lookup | unique request hash and idempotency key | `O(log n)` |
| exact run/review lookup | primary/unique key | `O(log n)` |
| all-run admin timeline | B-tree `(created_at desc, analysis_run_id desc)` | `O(log n + k)` |
| state-filtered admin timeline | B-tree `(state, created_at desc, analysis_run_id desc)` | `O(log n + k)` |
| runs for one source revision | B-tree `(source_kind, source_revision_id, created_at desc)` | `O(log n + k)` |
| runs for one intake file | partial B-tree on `source_file_id` | `O(log n + k)` |
| runnable state claim | partial B-tree `(state, created_at, analysis_run_id)` | `O(log n)` |
| workflow/job reverse lookup | unique workflow ID; indexed job ID | `O(log n)` |
| append-only event replay | unique `(analysis_run_id, sequence)` | `O(log n + k)` |
| proposal identity validation | in-memory maps/sets | `O(n + e)` |

No GIN index is added to canonical request JSON until a measured query requires it. Frequently used
source/preset/state fields are typed columns, not JSON scans.

## 11. Transactions, Concurrency, Retry, and Idempotency

1. Create-run locks or uniquely inserts the request hash and idempotency key. Identical replay
   returns the same run; a changed request under the same key fails closed.
2. Plan resolution and plan-step persistence occur in one transaction. A workflow has exactly one
   immutable plan.
3. Worker capacity claim uses the existing transactional lease controller and a unique active slot.
4. Proposal Artifact commit is externally atomic: stage locally, verify, move to final NAS revision,
   then record immutable pointers/job success in a transaction.
5. Risk evaluation locks the run and accepts exactly one proposal pointer. Concurrent evaluation is
   rejected by optimistic version or unique constraints.
6. Human review has one immutable row per run. Duplicate identical submission replays; conflicting
   submission fails.
7. A failed run never points to an accepted-result Artifact. A new attempt pins the failed run as
   predecessor but receives a new request ID, workflow ID, job ID, and Artifact Revision.
8. Reconciliation derives state from exact workflow/job/artifact pointers. It never re-executes a
   terminal worker or resolves a newer preset/source.

## 12. Failure Codes

Stable categories include:

- `KNOWLEDGE_ANALYSIS_REQUEST_INVALID`;
- `KNOWLEDGE_ANALYSIS_IDEMPOTENCY_CONFLICT`;
- `KNOWLEDGE_ANALYSIS_CONCURRENCY_CONFLICT`;
- `KNOWLEDGE_ANALYSIS_RETRY_INVALID`;
- `KNOWLEDGE_ANALYSIS_RUN_NOT_FOUND`;
- `KNOWLEDGE_ANALYSIS_SOURCE_MISSING`;
- `KNOWLEDGE_ANALYSIS_SOURCE_STALE`;
- `KNOWLEDGE_ANALYSIS_SOURCE_HASH_MISMATCH`;
- `KNOWLEDGE_ANALYSIS_SOURCE_INELIGIBLE`;
- `KNOWLEDGE_ANALYSIS_PRESET_INCOMPATIBLE`;
- `KNOWLEDGE_ANALYSIS_POLICY_MISSING`;
- `KNOWLEDGE_ANALYSIS_POLICY_STALE`;
- `KNOWLEDGE_ANALYSIS_WORKFLOW_UNAVAILABLE`;
- `KNOWLEDGE_ANALYSIS_WORKFLOW_MISSING`;
- `KNOWLEDGE_ANALYSIS_WORKER_FAILED`;
- `KNOWLEDGE_ANALYSIS_POINTER_INVALID`;
- `KNOWLEDGE_ANALYSIS_REVIEW_CONFLICT`;
- `KNOWLEDGE_ANALYSIS_ARTIFACT_COMMIT_FAILED`.

Capacity admission and worker-result validation retain their existing lower-boundary stable control
plane and worker error codes; `NEEDS_REVIEW` is a lifecycle state, not an error alias.

Public messages are bounded and do not include source content, local paths, credentials, worker
prompts/results, or database details.

## 13. Security and Rights Boundary

- Every external file and embedded instruction-like string is untrusted data.
- Prompt instructions explicitly prohibit following instructions found in source content.
- Only approved, exact Artifact Revisions may materialize.
- The ADMIN-only command boundary, source lifecycle, approved Artifact Revision, and exact content
  hash are checked before staging. Phase 7 does not invent an independent rights-policy aggregate;
  the later retrieval access-policy revision remains a separate Phase 9 contract.
- Worker identity has no PostgreSQL, NAS, sudo, Docker, peer-worker, or network access.
- The Application API remains metadata-read-only for analysis tables. Mutating commands cross the
  existing UID-checked private Catalog socket; its standalone runner uses a dedicated DB-only role
  with an exact SELECT/INSERT/UPDATE matrix and no API session, token, or credential-table access.
- Standalone runtime composition explicitly registers every SQLAlchemy foreign-key target before
  any flush, and a clean-process regression dereferences the complete Catalog runner FK graph.
- General model knowledge is never rendered as a source anchor.
- Slack reports only milestone status and stable error codes.
- Secrets, Codex authentication material, source excerpts, and proposal content never enter Slack.
- PostgreSQL contains no original file bytes, normalized Markdown, images, tables, equations, or
  full node/edge/claim collections.

## 14. Required Tests

### Protocol and compatibility

- canonical/package schema bytes and Draft 2020-12 validation;
- historical V1 bytes and workflow protocol bundle hashes pinned;
- V2 schema/model parity and canonical hashing;
- unknown fields/enums and mixed pointer families rejected;
- old item workflows and resolved plan V1 remain replayable.

### Source resolution and materialization

- missing/stale/unapproved Artifact or revision;
- mismatched logical/revision IDs, member path, media type, size, or hash;
- rejected/superseded intake source;
- approved historical Item Revision remains resolvable without implicit latest substitution;
- malformed/oversized input, archive traversal, absolute path, symlink, and hard-link escape;
- source text prompt injection remains inert data;
- exactly one source and bounded reviewed instructions are staged.

### Proposal validation and Artifact commit

- duplicate IDs, illegal node/edge types, missing endpoints/anchors, self-edge;
- forged source anchors and auxiliary-knowledge-as-citation rejection;
- deterministic JSON Lines and member hashes across two runs of the pure serializer;
- DB result contains only the bounded receipt and no Markdown/full collections;
- failed validation or commit publishes no accepted result;
- committed proposal files are regular, non-symlink, immutable, and hash-correct.

### Lifecycle and concurrency

- idempotent request replay and conflicting replay;
- concurrent create/claim/review;
- exact chronological and state-filtered B-tree index definitions for ADMIN pagination;
- one support slot and one active knowledge-analysis lease;
- stale/uncertain lease reconciliation without double execution;
- auto-accept, needs-review, human approve, human reject, retry, cancel, and failure transitions;
- rejected review never becomes graph-publishable.

### Isolation and dependency direction

- worker cannot access DB, NAS, network, another worker, or arbitrary repository paths;
- no direct worker communication;
- only Orchestrator code commits the proposal Artifact;
- standalone Catalog runner resolves every registered SQLAlchemy foreign-key target;
- contract/domain packages import no infrastructure;
- analysis source/result schemas have no runtime Git/source dependency;
- no large binary or proposal collection is stored in PostgreSQL.

## 15. Deployment and Live-Run Gates

Deployment order is intentionally separate from live analysis authorization:

1. additive schemas/models and dual-read application code;
2. source tests and immutable compatibility hashes;
3. additive migration in a disposable PostgreSQL harness;
4. reviewed support instruction bundle and analysis Execution Preset Revision;
5. workflow definition installation and runtime package deployment;
6. non-generating capability/auth observation for slot05;
7. fake-worker and local artifact-commit smoke;
8. separately authorized one-shot live knowledge analysis on a disposable approved source;
9. human review/acceptance verification;
10. proof that failed analysis publishes no graph delta.

Phase 7 does not publish a Graph Snapshot. Phase 8 is the first authority allowed to consume an
accepted V2 result and atomically publish graph state.

## 16. Rejected Simpler Alternatives

### Mutate the V1 knowledge-analysis schemas

Rejected because the V1 resources are already published contract identities. In-place change would
reinterpret historical hashes and persisted messages.

### Require the worker to return canonical Artifact pointers

Rejected because the worker neither owns nor commits canonical Artifacts. Such pointers would be
forged or circular before commit.

### Store nodes, edges, claims, and Markdown in PostgreSQL JSONB

Rejected because it duplicates large canonical payloads, creates unindexed scans, and violates the
Artifact pointer boundary.

### Reuse `ContentIntakeAnalysisRecord`

Rejected because that record owns manual Content Pack mapping evidence and has a different
lifecycle, inputs, outputs, and review rule.

### Create a fake Content Pack for analysis

Rejected because analysis is not item production. It would pollute compatibility semantics and
couple the knowledge pipeline to unrelated authoring profiles.

### Add slot06 or let analysts run concurrently without a distinct workload class

Rejected because the measured host boundary is five identities, three active Codex processes, and
one active knowledge-analysis process. Existing slot05/support is the correct bounded pool.

### Let the worker write Markdown or graph files directly to NAS

Rejected because workers cannot validate canonical identity, rights, lifecycle, path safety, or
atomic publication. Only the Orchestrator commits validated artifacts.

### Treat every PDF/Markdown Artifact as a Document Revision

Rejected because a storage Artifact is not a domain Document identity. A real Document aggregate
may be added later without rewriting the initial source union.

## 17. Phase 7 Exit Evidence

Phase 7 is complete only when all of the following are proven:

- one source request resolves to exact immutable source/preset/plan pointers;
- support slot05 runs through the Orchestrator with knowledge-analysis capacity at most one;
- the proposal validates and commits as a pointer-oriented Artifact file set;
- risk policy yields either immutable acceptance or an explicit review gate;
- one accepted result is reproducible from pinned inputs;
- one malformed or failed result publishes no accepted delta;
- historical V1/protocol/item workflow bytes and replay remain intact;
- source, worker, DB, NAS, auth, and Slack security boundaries remain intact;
- migrations, deployment, and any live Codex use each have separate reviewed authorization.

## 18. Source-Completion Evidence

The 2026-08-24 UTC source gate established the following without using the production database,
starting a live Codex worker, publishing a Graph Snapshot, or deploying runtime packages:

- migration `20260823_0011` completed upgrade, downgrade, and re-upgrade in a guarded disposable
  PostgreSQL database;
- the disposable runtime-role reconciliation and API/workflow integration matrix completed with
  58 tests passing and one environment-inapplicable approval test skipped; the guarded database and
  roles were then removed;
- the complete non-live platform matrix completed with 671 tests passing and 23 opt-in tests
  deselected;
- the complete in-process Scientific Studio matrix completed with 59 tests passing;
- the focused schema/resource/deployment-boundary matrix completed with 66 tests passing;
- Ruff formatting and linting passed for 607 files, and strict mypy passed for 258 source files;
- changed shell syntax, OpenAPI source/hash parity, canonical/package JSON Schema parity, staged
  diff checks, and the repository-owned secret/boundary scan passed.

Disposable integration exposed and now regresses five concrete boundaries: additive registration
of `workflow-role/1.4.0` with its immutable schema-bundle hash, reuse of the published evaluation
report enum, JSON-mode UTC timestamp serialization before JSON Schema validation, Orchestrator
ownership of the per-job staging root, and one-flush transition of `ACCEPTED` state with its result
pointers and append-only event. These checks preserve the DB rule that a non-accepted run cannot
carry an accepted-result pointer.

`SOURCE_COMPLETE` is not runtime acceptance. The deployment plan, production migration, preset and
workflow bootstrap, non-generating slot05 observation, and any one-shot live analysis remain later
operator-controlled steps. Phase 8 has not started and is the first phase allowed to publish an
immutable graph snapshot.

## 19. Deployment RBAC Closure

The first production deployment of migration `20260823_0011` established that the schema migration
did not seed the three additive `knowledge_analysis:*` permissions required by the already frozen
`PermissionKey` and `ROLE_PERMISSIONS` contracts. Migration `20260823_0011` is immutable after
publication and production application; it is not edited in place.

The canonical permission inventory remains `eom_operator_identity.PermissionKey`, and the canonical
role mapping remains `ROLE_PERMISSIONS`. Additive migration `20260824_0012` materializes only the
missing permission identities and their ADMIN mappings using the same deterministic ID derivation as
the original RBAC migrations. PostgreSQL remains the canonical persistence boundary; no permission
document or large payload is introduced.

The dominant access patterns are exact permission-key lookup, ADMIN membership lookup, and
readiness cardinality comparison. Existing unique B-tree constraints on `permission_key` and the
`(role_id, permission_id)` primary key provide `O(log n)` lookup and set membership. The migration
runs in one transaction, fails on an unexpected pre-existing identity, and is idempotent through the
Alembic revision boundary. Downgrade removes only the three new ADMIN mappings and permissions.

The Application API runtime role receives no new write authority from this data migration. Its
separate table-grant reconciliation remains authoritative. Calling a general identity service from
deployment was rejected because it would hide a production mutation behind a read command; editing
`0011` was rejected because it would reinterpret an applied migration; and weakening readiness was
rejected because missing RBAC rows are a real authorization defect.
