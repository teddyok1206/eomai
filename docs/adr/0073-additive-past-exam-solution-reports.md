# ADR 0073: Additive past-exam solution reports

Status: Accepted

Date: 2026-09-12

## Responsibility and boundary

Knowledge Analysis owns a new, additive solution-report pass for approved past-exam Item
Revisions. The pass records a concise, externally reviewable solution rationale and connects its
steps to the concepts, assessment patterns, and item elements already accepted for the same Item.
It does not request or persist a model's hidden chain of thought. Workers still receive staged
local inputs and return one typed result; the Orchestrator alone validates and commits Artifacts to
NAS.

The existing `knowledge-analysis-request/9.0`, worker proposal 7.0, proposal receipt 8.0, accepted
result 9.0, and all of their Artifact bytes remain immutable. A successor request points at one
exact accepted V9 run and asks only for the new solution report. Future past-exam ingestion first
produces the existing complete analysis and then produces this additive successor. Backfill of the
completed 520-Item corpus skips the first pass and reuses those exact accepted results.

## Canonical source and revision model

The approved Item Revision and its problem/answer page Artifact members remain the source evidence.
The accepted V9 analysis result and its proposal receipt are the canonical base analysis. The new
solution report is a separate immutable Artifact Revision. Its proposal receipt references the
base result and base member pointers instead of copying their bytes:

```text
Item -> immutable Item Revision
     -> accepted Knowledge Analysis V9 -> base proposal member pointers
                                      -> additive solution report Artifact Revision
                                      -> accepted enriched-analysis result
```

Logical IDs, revision IDs, Artifact IDs, member hashes, semantic self-hashes, and mutable current
pointers remain distinct.

## Pointer checks

Before a solution request is created, the Catalog resolves the base run, accepted-result Artifact,
proposal receipt, and all base members. It checks source identity, lifecycle, schema, media type,
member path, byte count, SHA-256, proposal content-set hash, and accepted-result self-hash. The
request pins those pointers and one bounded reference index derived from the base anchors and typed
nodes. The index is a small frozen value object, not a second canonical copy; its hash is bound to
the request and it is invalidated only by creating a new immutable request.

Before NAS commit, the Orchestrator requires every report anchor and node reference to resolve in
that index, every step dependency to point to an earlier step, and every concept-to-assessment link
to reference at least one solution step and one item element or assessment pattern. Missing,
dangling, stale, duplicated, reordered, wrong-type, or hash-mismatched references fail explicitly.

## Access patterns and data structures

The dominant read is an indexed lookup from Item Revision or base analysis run to the one accepted
solution-report successor. The 520-Item backfill is deterministic ordered iteration with membership
and deduplication. In memory, reference validation uses maps keyed by node ID and anchor ID, plus
sets for uniqueness, so validation is O(nodes + anchors + steps + links). Step dependencies are a
small ordered DAG represented by predecessor ID tuples; the earlier-step rule makes cycle detection
O(steps) without a second traversal.

Persistence reuses `knowledge_analysis_runs.predecessor_analysis_run_id` and its index. A partial
unique index over accepted solution-report successors prevents more than one accepted report for
the same base run and report schema. PostgreSQL stores pointers and bounded JSON contracts only;
report text remains in the NAS Artifact.

Expected scale is hundreds to low thousands of reports per corpus. Each report is bounded to 64
steps, 32 concept links, 16 choice diagnostics, and 256 KiB canonical JSON.

## Transaction, concurrency, retry, and idempotency

Request identity is derived from the base accepted result, exact source, report schema, preset
revision, risk policy, and general-knowledge mode. The durable idempotency key uses that identity.
Concurrent creation is serialized by the existing source-history and idempotency constraints; a
conflicting payload fails rather than selecting a latest revision. Artifact commit precedes the
existing transactional Artifact registry transition. Acceptance creates a new immutable result and
never mutates its predecessor.

Backfill uses the existing bounded support-worker capacity and ordered orchestration. A retry keeps
the same immutable dependencies and uses the existing failed-run successor rules. One systematic
failure stops new scheduling; completed reports remain valid and replay is idempotent.

## Dependency direction and ownership

JSON Schema and Pydantic contracts define the value objects. Knowledge Analysis application
services resolve accepted base pointers and construct requests. The execution resolver pins the
plan; the materializer stages source and base members; the worker emits only the report; the
Orchestrator validates and commits it; Catalog acceptance and Graph publication consume the typed
receipt. RAG retrieval resolves the accepted report pointer and combines it with base evidence at
the presentation boundary. No worker talks to another worker or writes PostgreSQL/NAS.

RAG preserves Evidence Bundle manifest versions 1 through 4 and introduces manifest/result version
5 only when the retrieval boundary can pin additive solution evidence. Catalog performs one
set-based lookup from candidate base analysis run IDs to accepted version-10 successors by the
indexed predecessor relation, then resolves exact result, receipt, and report member pointers.
The lookup and in-memory merge are O(candidates + accepted successors); there is no per-candidate
query. PostgreSQL stores only bounded pointer metadata and never the report body.

The detailed report is answer-bearing canonical evidence and is not copied into an item worker's
workspace. The immutable Evidence Bundle V5 manifest pins it for audit and reproducibility, while
the bounded generated context includes only the explicitly reusable `assessment_design_summary`
and `reusable_generation_guidance` fields. The Catalog validates the complete report before that
projection. Missing additive reports remain an explicit null pointer during bounded backfill; new
corpus completion requires both passes before publication is considered complete.

## Decision

- Add immutable request 10.0, worker proposal 8.0, proposal receipt 9.0, and accepted result 10.0.
- Store structured reasoning steps, concept-to-assessment links, optional choice diagnostics,
  official-explanation comparison, a short solution summary, and a reusable assessment-design
  summary.
- Treat step explanations as concise submitted rationale, never as hidden chain of thought.
- Require future past-exam learning completion to include both the base analysis and its accepted
  solution report.
- Backfill the exact completed 520-Item set by referencing existing V9 results and producing only
  the new Artifact.
- Keep internal batch identifiers private in user projections while retaining ID-based operator
  queries.

## Simpler alternative

Appending free-form text to `normalized/document.md` is simpler, but it would mutate or duplicate
accepted evidence, provide no stable step/concept/item links, and make completeness impossible to
validate. Re-running the complete V9 analysis would waste model work and could drift previously
accepted graph identities. A sidecar successor is the smallest design that preserves the completed
corpus and adds uniformly retrievable solution evidence.
