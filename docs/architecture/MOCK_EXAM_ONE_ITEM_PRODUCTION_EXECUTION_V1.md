# Mock Exam One-Item Production Execution V1

## Responsibility and boundary

This application use case executes one released 25-slot mock-exam production plan by starting the
existing `generic-item-development@1.8.0` one-Item workflow once per planned call. It does not query
an approved bank, choose legacy Items, call workers, write NAS, or mutate service databases. Existing
workflow, Catalog, assembly, and HWPX application services remain the only side-effect owners.

The coordinator performs one reconciliation pass and returns an immutable pointer checkpoint. The
operator runner persists every changed checkpoint before returning. A caller invokes separate typed
phase methods; there is no flag-driven catch-all operation and no background loop hidden in the API.

## Canonical source and revision model

The released `MockExamProductionPlanV1` is the canonical ordered set of 25 workflow calls. Each call
contains the exact Content Team V3 Item brief and its mock-exam slot. A production execution is one
caller-authorized `productionreq_*` occurrence, mapped with the immutable plan ID/hash to one global
logical `productionexec_*` entity with append-only `productionexecrev_*` checkpoints. The operator is
the immutable owner but is deliberately absent from the execution-ID derivation, so a second operator
cannot reserve a parallel execution for the same occurrence. Every revision pins the predecessor and
predecessor checkpoint hash. A checkpoint self-hash covers its complete pointer-only state.

Generated content remains canonical in existing services:

```text
production plan call -> Workflow occurrence -> zero-blocking review artifact
                     -> human approval -> new V2 Item Revision (revision 1)
                     -> accepted analysis -> one atomic Graph publication (25)
                     -> explicit human rating -> exact-cohort assembly -> HWPX artifact
```

The checkpoint contains identities, pinned revisions, hashes, small state values, and sanitized error
codes only. It contains no prompt, Item body, image bytes, HWPX bytes, credentials, or long logs.

## Pointer resolution checks

- Preflight resolves the generation block to exact workflow definition, Content Pack release/source
  tree, and execution-preset identities and hashes. Every start command carries those expected
  pointers plus the caller's production occurrence; the workflow creation transaction rejects
  drift. Every later read must expose the same accepted resolution.
- The V3 Item brief is mapped intact, including `mock_exam_slot`; the coordinator rejects a missing
  slot.
- Before approval, each workflow must expose exact knowledge provenance for the authorized retrieval
  intent: execution plan, preset revision, Graph snapshot, Evidence Bundle, retrieval request,
  access policy, manifest hashes, and resolved time. The per-call checkpoint preserves this pointer
  and rejects disappearance or change.
- Approval uses the official Catalog eligibility observation. It requires the exact review artifact,
  zero blocking findings, a pending approval before the command, and the same artifact plus atomic
  approved human gate afterward. The command pins the observed approval request and resource version
  for row-lock validation. The reviewer must be the execution operator.
- Registration must be revision 1 from that Workflow occurrence. Analysis must bind that exact Item
  Revision and risk-policy revision/hash. A nonterminal run is reconciled through the Catalog
  application boundary. `NEEDS_REVIEW` can advance only from a self-hashed, caller-supplied decision
  set that pins each analysis run and expected resource version.
- One Graph publication contains positions 1-25 and pins the observed current snapshot revision/hash,
  access-policy revision/hash, aligned Workflow IDs, and authorization time. There is no intermediate
  snapshot where another publisher can interleave. The caller supplies the authorization time in a
  self-hashed immutable input, so a response-loss retry reuses the exact same command hash. Only the
  official `KNOWLEDGE_GRAPH_STALE_CURRENT` no-commit outcome permits a replacement authorization;
  that replacement must cite the predecessor authorization hash, preserve the access-policy pointer,
  and itself survive a write-ahead checkpoint before publication. Unknown outcomes cannot be rebased.
- Ratings are accepted only as a complete operator-supplied set over the exact 25 generated Item
  Revisions. The checkpoint pins the self-hashed decision set, operator, authorization time, and
  rating-policy revision/hash. No rating default or model inference exists.
- Assembly must be READY for the exact ordered cohort; any external, missing, stale, or reordered Item
  fails. The checkpoint pins the operator intent, cohort identity/hash, plan hash, and assembly
  idempotency identity. At Assembly creation it also derives and pins the HWPX item-set hash from each
  ordered placement's position, derived placement ID, Item ID, Item Revision ID, and Item-manifest
  hash. HWPX must return that exact hash, bind the Assembly/manifest/policy/Graph/operator and ordered
  25-Item pointers, pass 25-item/25-section validation, and expose a downloadable output.

Missing, stale, mismatched, dangling, or hash-invalid pointers produce stable errors. The coordinator
never substitutes an implicit latest revision.

## Access patterns and data structures

The fixed plan is traversed in stable position order. A dictionary keyed by `workflow_call_id` gives
O(1) call lookup during reconciliation, and sets provide O(1) membership/uniqueness checks for Graph
and assembly cohorts. Ordered tuples preserve reproducible 25-slot and atomic publication manifests. At this fixed
scale each phase is O(25) time and O(25) checkpoint space.

The V1 runner adds no database table or index. Existing application services own their indexed
workflow, Item, analysis, Graph, rating, and assembly lookups. If checkpoint storage later moves to a
shared database, it requires a unique revision ID, unique `(execution_id, checkpoint_sequence)`, and
an indexed mutable head row updated with compare-and-swap.

## Transaction, concurrency, and persistence

External service commands retain their existing transaction boundaries. Deterministic idempotency
keys bind the execution, plan call, phase, and relevant immutable pointer. An unknown start outcome is
retried with the same key, so one plan call cannot intentionally create a second Workflow occurrence.
Generation resolution is committed in a checkpoint-only pass before any of the 25 Workflow starts.
The analysis policy/mode, every explicit analysis-review set, the atomic Graph authorization, and the
explicit rating authorization are likewise checkpointed before their first Catalog command. Assembly
uses two write-ahead passes: first the operator intent, then the
READY plan containing the exact cohort and derived idempotency-key hash; creation happens only after
both survive compare-and-swap. This prevents a crash plus active-release, policy, decision, or planner
drift from stranding a deterministic operation key against a different request.

Graph publication idempotency additionally includes the self-hashed authorization. If a concurrent
publisher advances the Graph after write-ahead pinning, Catalog's stable stale-current result proves
that no publication committed for this command. The next checkpoint may then replace the singular
authorization only when it cites that predecessor hash; the immutable checkpoint revision chain
retains the superseded authorization evidence.

`AtomicJsonMockExamProductionCheckpointStore` is an infrastructure adapter for a configured absolute
runtime directory outside Git. It appends one immutable revision file, fsyncs it, and atomically
replaces a validated `current.json` materialized cache under an advisory file lock. Compare-and-swap
requires the exact current revision, predecessor hash, sequence, plan, and operator. A crash may leave
an unreachable but valid immutable revision, never a partially published current checkpoint. The
caller can retry safely.

For production deployment, the checkpoint directory should be an orchestrator-owned local runtime
path such as `/var/lib/eom/mock-exam-production`; it is not an artifact store and must not be exposed
to workers. HWPX and other binary artifacts remain in their existing NAS-owned services.

V1 resolves the production plan from packaged released resources. Therefore an operations guard must
block application deployment or released-plan replacement while any execution is nonterminal; the
sample run is explicitly operated under that guard. The durable follow-up is an immutable production-
plan registry addressed by `production_plan_id` plus `plan_sha256`, allowing resumes to resolve the
historical plan rather than the newly packaged current plan. Silently substituting the current plan is
forbidden. Likewise, pinned Workflow definition/pack/preset revisions must remain resolvable until all
25 starts have been durably observed; deactivation must not delete immutable revisions.

## Dependency direction and adapter ownership

API contracts contain frozen pointer/value models. The coordinator depends on narrow application
ports. Concrete adapters call `CommandAdapter`, `QueryAdapter`, `CatalogApplicationClient`, the
existing assembly service, and `ExamHwpxApplicationService`. The local checkpoint adapter implements
the application store port. Domain/contracts do not import infrastructure, workers do not orchestrate,
and services do not communicate through private tables.

## Failure, retry, and idempotency

Every unknown or blocked stage is recorded with a sanitized code and retryability. Start, approval,
analysis creation, atomic Graph publication, rating, assembly, and HWPX requests reuse deterministic
keys or the existing content-addressed identity. Workflow and analysis polling/reconciliation preserve already
observed pointers. `NEEDS_REVIEW` is actionable and resumable through an explicit operator review;
the coordinator never invents an analysis approval. Resumption loads the validated current checkpoint
and advances only the requested phase.

A review with blocking findings remains deliberately fail-closed in V1. A future explicit rework
boundary must first add a typed blocking-review pointer and append-only attempt/rework history so the
original review is never overwritten; it may then issue the standard `REQUEST_REWORK` action to the
fixed `authoring` target within the pinned workflow's three-cycle limit. V1 does not silently infer or
submit that decision.

## Rejected simpler alternative

Selecting 25 already approved Items would be simpler but violates the production-plan semantics and
cannot prove that the sample exam was newly authored. Starting 25 workflows in one uncheckpointed
loop would lose response-outcome evidence and make retries duplicate-prone. Storing full Item or HWPX
payloads in the checkpoint would duplicate canonical artifacts. The bounded coordinator plus immutable
pointer checkpoints is the smallest design that preserves exact provenance and resumability.
