# Knowledge Analysis Quality Observation V1

Status: reviewed implementation design

Scope: Scientific Studio read-only observation of existing Knowledge Analysis batches

## 1. Responsibility and boundary

This feature helps an administrator answer three questions without changing a running analysis:

1. how much of the selected textbook page scope has reached each lifecycle state;
2. whether the batch range topology contains gaps, overlaps, or reused result pointers;
3. which curriculum unit keys are connected to which pinned document revisions.

The Application API remains the source of truth. Scientific Studio reads the existing batch and
range projections and derives an ephemeral quality report. The report is neither an accepted
Knowledge Graph nor a Graph Snapshot, and it cannot approve, retry, cancel, publish, or persist
analysis work.

The boundary is deliberately presentation-local:

```text
Application API batch/range projections
    -> Web GUI HTTP gateway
    -> pure quality-report function
    -> read-only Scientific Studio view
```

No worker, preset, database schema, Graph publication service, NAS object, or Application API
contract changes in this feature.

## 2. Canonical source and revision model

Canonical state is the persisted `KnowledgeAnalysisBatch` and its ordered immutable range inputs,
plus the lifecycle pointers returned by the Application API. The quality report contains only a
bounded projection of those values. It is recomputed on request and is not stored.

Document identity remains:

```text
educational document -> immutable document revision
                     -> source Artifact revision -> source SHA-256
```

Analysis identity remains the range's pinned analysis run and Artifact revision. A path is never
used as identity, and the GUI never resolves storage URIs.

## 3. Pointer checks

The gateway validates every range against a frozen Pydantic projection before the report builder
sees it. The report then checks:

- every range points back to the requested batch;
- ordinals are unique and contiguous from zero;
- one document revision does not drift between source Artifact revision or source hash;
- physical page intervals are ordered and non-overlapping;
- accepted analysis run and Artifact revision pointers are not reused by distinct ranges;
- the observed range count agrees with the batch total.

Missing fields, invalid identifiers, unsupported schemas, invalid media types, cursor cycles, and
more than 1,000 returned ranges fail closed as an upstream contract error. Topological anomalies in
otherwise valid projections are returned as explicit quality findings.

## 4. Primary access patterns and data structures

The dominant operations are ordered iteration, key lookup, membership/deduplication, and sparse
relationship projection.

- ranges are sorted once by ordinal;
- document aggregation uses a map keyed by immutable document revision ID;
- covered pages use per-document sets;
- duplicate run and Artifact-revision checks use maps keyed by immutable IDs;
- curriculum relationships use a set of `(unit_key, document_revision_id)` edges;
- output uses frozen tuples with deterministic sorting.

The page-level set is bounded by the existing contract: at most 1,000 ranges and 32 pages per range,
or 32,000 page keys. Time and space are therefore `O(r log r + p)`, where `r` is range count and `p`
is the number of selected page occurrences. There are no repeated list scans or N+1 HTTP calls;
range pages are fetched in at most five 200-row requests.

## 5. Transaction and concurrency boundary

The report performs no transaction and takes no lease. Each Application API response is a valid
read projection, but a running batch may advance between the batch-list response and range pages.
The report therefore records the batch resource version and the latest persisted `updated_at` it
observed. It does not claim a database-wide snapshot.

Refreshing replaces the entire client-side report. There is no merge of old and new observations.
The active slot 5 worker remains independent and is never signalled, restarted, or reconfigured.

## 6. Failure, retry, and idempotency behavior

The BFF endpoint is a GET and has no side effect. Pagination is bounded, cursor cycles fail, and the
GUI may repeat GET requests safely. There is no automatic worker retry, review decision, acceptance,
or Graph publication. Upstream errors remain sanitized `GatewayError` codes.

Quality classification is intentionally observational:

- `PASS`: no topology or pointer finding;
- `WARN`: a gap is visible inside a document's selected envelope;
- `FAIL`: batch identity/count, ordinal, overlap, source-pointer, or duplicate result-pointer
  invariants are inconsistent.

Text extraction density is not an acceptance gate in this view. Empty or sparse Markdown content
requires Artifact-level evidence and belongs to the separate analysis review contract; range
metadata alone must not invent such a conclusion.

## 7. Dependency direction and ownership

The new JSON Schema defines the Web presentation contract first. Frozen Web models implement it.
The pure report builder depends only on those models. The HTTP gateway is the infrastructure
adapter. Routes call the Web application service. JavaScript renders only the resulting DTO.

The Web layer does not import SQLAlchemy models, Catalog internals, worker code, Graph persistence,
or filesystem adapters. It does not read NAS or query PostgreSQL directly.

## 8. Simpler alternative and why it is insufficient

Showing only `accepted / total` is cheap and remains on the control card, but it cannot detect a
same-page duplicate, a page gap, source revision drift, or a reused analysis result pointer. A raw
range table would expose data without explaining these invariants and would make the administrator
perform repeated scans manually. The bounded derived report is the smallest layer that answers the
actual review questions while preserving the existing architecture.

## 9. GraphRAG exploration boundary

The Studio visualization is named **analysis coverage map**. It displays only observed edges:

```text
curriculum unit key -> pinned document revision -> selected physical page interval
```

It must always state that it is not a published Graph Snapshot. It does not show semantic claims,
Evidence Bundle contents, graph nodes, or graph edges that the Application API has not projected.
A future canonical Graph explorer needs a separate schema-first read contract that resolves a
pinned Graph Snapshot revision through its owning application service.

## 10. Security and privacy

- The endpoint is ADMIN-only and read-only.
- No secret, bearer token, worker prompt/result, textbook text, file path, storage URI, or raw log is
  returned.
- Dynamic DOM content is created with `textContent`; no API value enters `innerHTML`.
- Response size is bounded by the upstream 1,000-range contract and bounded finding references.
- Cursor values are opaque, bounded, and never logged as evidence.
- The client cannot trigger accept, retry, publish, or worker control from this view.

## 11. Verification

Tests cover canonical JSON Schema validation, coherent and anomalous range topology, duplicate
pointers, deterministic ordering, bounded pagination, cursor cycles, ADMIN authorization, absence
of mutation controls, safe DOM construction, and the distinction between analysis coverage and a
published Graph Snapshot. Full Web GUI tests and release isolation checks remain required before a
Web-only deployment.
