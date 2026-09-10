# Mock-exam trusted-RAG production protocol V3

Status: contract-only additive successor. Runtime resolution, orchestration, persistence, and live
production are intentionally deferred.

## 1. Responsibility and system boundary

This successor defines the immutable messages needed to produce a fresh 25-Item mock exam through
`generic-item-development@1.10.0`, `workflow-role/1.20.0`, and
`generated-knowledge-item@1.15.1`. Catalog contracts own the production plan and the review
eligibility/decision/publication values. API contracts own the public review observation and the
append-only execution checkpoint. Workers continue to communicate only with the orchestrator,
materialize local results, and never write Catalog state or NAS.

The V3 contract does not start workflows, resolve releases, publish reviews, register Items, write
Graph nodes, assemble a form, or build HWPX. Those application behaviors require a separate
reviewed change. For the same reason, the active V1/V2 production-plan, checkpoint, and Catalog
application unions do not yet dispatch V3; callers must use the exported V3 models directly until
an immutable application-envelope successor and runtime selection branch are released together.

## 2. Canonical source and immutable family

Files under `schemas/` are the canonical JSON Schema 2020-12 documents. Package resources are
byte-exact mirrors. Frozen Pydantic models provide the corresponding in-process representation.
The generation block closes over this exact family:

- workflow definition `generic-item-development@1.10.0`;
- role protocol `workflow-role/1.20.0` and its pinned schema-bundle SHA-256;
- Content Pack `generated-knowledge-item@1.15.1` and its pinned source-tree SHA-256;
- `authoring-result@10.0` and `review-result@10.0`; and
- one orchestrator-issued `evidence-usage-validation-receipt/1.0` for each of those two results.

The plan deliberately names the released execution-preset key as unresolved intent because a plan
is created independently of an environment's released preset revision. Before the first Workflow
start, the executor must create one immutable generation-block resolution child that pins the exact
workflow-definition hash, Content Pack release ID/hash, and execution-preset ID/revision/hash. Every
started call and retry in that execution must reuse that one resolution; resolving the mutable key
again is forbidden.

V1 and V2 schema bytes, constants, unions, and validation meaning remain unchanged. The successor
uses new `/3.0` discriminators and never widens an old schema identity.

## 3. Logical entities, revisions, and canonical receipts

The production plan, Workflow, step run, job, logical Artifact, Artifact Revision, Item Revision,
review decision, and execution checkpoint remain distinct identities. Each content hash describes
the exact immutable value or bytes named by its adjacent revision pointer. A path is never used as
identity.

The orchestrator terminal `ARTIFACT_COMMITTED` event remains the canonical source of each trusted
evidence-usage receipt. V3 messages carry only a small typed receipt-pair pointer: exact Workflow,
step-run, job, logical Artifact, Artifact Revision, result hash/schema, and receipt hash for the
authoring and review results. They do not copy either complete receipt, evidence manifest, evidence
context, worker result, or binary artifact.

The publication receipt keeps the historical `review_artifact_*` fields with their established
meaning: they point to the canonical human review-decision Artifact stored by `ItemReviewRecord`.
V3 adds separately named `source_review_artifact_*` fields for the worker review result. The
trusted receipt pair binds only that source review, preventing a decision-Artifact hash from being
misinterpreted as worker evidence.

## 4. Pointer and resolution checks

The pair is ordered and closed: authoring must be `authoring-result@10.0`, review must be
`review-result@10.0`, both must name one Workflow, and their job, step-run, Artifact, and revision
identities must be distinct. Eligibility, source-review, publication, and execution pointers must
match the same review member byte for byte by identity and SHA-256.

Calling a value "trusted" does not make caller input authoritative. A future application service
must extend or wrap the existing trusted receipt resolver. For each compact pointer it maps
`artifact_id`, `artifact_revision_id`, and `sha256` to the existing `ArtifactPointer` fields,
resolves the succeeded job, approved Artifact/revision, manifest/content hashes, and the single
terminal event, then compares the returned receipt's self-hash with `receipt_sha256`. It must also
parse the persisted `RoleWorkerInput` in `JobRecord.request` and require its `workflow_id`,
`step_run_id`, `attempt`, `job_id`, role, protocol version, and Artifact pointer to equal the compact
pointer. The current read-side resolver does not by itself perform all three execution-context
comparisons, so it is not sufficient as the V3 trust boundary without that wrapper. Receipt
validation then closes the Graph/evidence pins and authoring-to-review chain. For an execution
checkpoint, the application service must additionally compare the resolved receipt pair's shared
plan ID/hash, Evidence Bundle revision, retrieval request ID/hash, Graph snapshot revision/hash,
and evidence-manifest hash to that Item run's `knowledge_provenance`; the compact pair deliberately
does not duplicate those full receipt values. A valid receipt placed beside unrelated provenance
must fail. Missing, dangling, stale, duplicated, mixed-family, unauthorized, or hash-mismatched
pointers fail closed; there is no implicit latest-revision substitution.

That first immutable execution resolution is the only dereference boundary for the plan's preset
key. Once any call is started, a checkpoint without that resolution or with a different resolution
is invalid.

## 5. Primary access patterns

Contract dispatch is key lookup by `schema_version`. Receipt resolution is exact lookup for two
result pointers. A production checkpoint validates an ordered 25-row sequence, membership and
uniqueness of Workflow/Item/revision IDs, and receipt coherence for completed review rows. Review
eligibility and publication inspect one bounded finding set and one receipt pair.

## 6. Data structures and indexes

Discriminated unions and immutable tuples preserve stable family and output order. Dictionaries
provide O(1) per-key checkpoint and receipt lookup; sets detect duplicate step, job, Artifact,
revision, call, Workflow, and Item identities. Existing primary/foreign keys and indexes on
Workflow, job, step-run, Artifact, Artifact Revision, approval, Item Revision, and review records
serve the future resolver. This contract-only change adds no table, index, cache, queue, or large
JSONB value.

## 7. Scale and complexity

Let `n` be the number of production calls (`n = 25`) and `f` the number of review findings
(`f <= 20`). Plan and checkpoint validation use one ordered pass plus maps/sets, taking O(n) time
and O(n) auxiliary space. Receipt-pair validation is O(1). Eligibility and publication projection
are O(f) time and space. Canonical serialization and hashing are linear in their bounded small
payloads. There is no repeated list scan, N+1 query, or O(n-squared) deduplication.

## 8. Transaction and concurrency boundary

Contracts have no side effects. A later executor must retain the existing boundaries: immutable
plan creation, one idempotent Workflow-start operation per call, orchestrator validation and NAS
commit in its Artifact-success transaction, Catalog registration/review publication in Catalog
application transactions, and append-only execution checkpoints with compare-and-swap on the
current revision. Workers own none of those transactions.

## 9. Dependency direction

Catalog contracts define the presentation-neutral receipt-pair value. API contracts may depend on
that stable value. Application services will orchestrate through ports; SQLAlchemy, filesystem,
NAS, Codex, and HWPX adapters remain infrastructure. Contract and domain modules import no
infrastructure implementation, and no component bypasses the orchestrator or another service's
private tables.

## 10. Failure, retry, recovery, and idempotency

Unknown `/3.0` discriminators, mixed V1/V2/V3 members, wrong workflow/role/pack pins, absent receipt
pairs, authoring/review swaps, receipt/result mismatches, and checkpoint identity drift are explicit
validation failures before state change. A production plan remains content-addressed; a checkpoint
pins its predecessor revision/hash; a review decision self-hash includes the receipt-pair pointer.
Exact retry therefore reuses the same plan, Workflow-call, result, receipt, decision, and checkpoint
identities. A conflicting replay cannot overwrite historical bytes or silently create a competing
decision.

Recovery must resume from the last validated checkpoint and re-resolve the same immutable receipt
pointers. It must not infer success from worker output, select a newer receipt, or repair a broken
chain. Runtime activation tests must include tampered or missing `JobRecord.request` context,
attempt drift, compact-to-full receipt hash drift, and a valid receipt pair combined with unrelated
knowledge provenance. Existing V1/V2 replay continues through its original contract family.

## 11. Rejected simpler alternative

Reinterpreting production plan/execution/review V2 as accepting `@10` results would require fewer
files, but would mutate already released meaning and make historical replay non-reproducible.
Carrying only a boolean such as `rag_validated=true`, trusting worker citation fields, or storing
only a receipt SHA-256 would omit the exact result/job/revision lookup needed to re-establish trust.
Embedding complete receipts or evidence bytes would duplicate canonical data. The additive V3
family with a compact, resolvable receipt-pair pointer is the smallest safe boundary.
