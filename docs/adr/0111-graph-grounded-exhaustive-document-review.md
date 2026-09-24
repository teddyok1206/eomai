# ADR 0111: Graph-grounded exhaustive paired-document review

## Status

Accepted for implementation on 2026-09-24.

## Context

The released `pdf-document-review@1.1.0` / `pdf-document-review-result@2.0`
path preserves two immutable source revisions and page-anchored findings, but it
does not make four important claims machine-checkable:

1. every review axis is independently covered;
2. an `INSUFFICIENT` originality decision cannot be reported as `COMPLETE`;
3. every question has an explicit solve, answer/choice, unit, and official
   explanation comparison record; and
4. Graph evidence used by the reviewer is pinned and independently validated.

The predecessor bytes and historical results are immutable.  Tightening their
Pydantic semantics in place would reinterpret accepted history, so the change
requires a successor protocol.

## Decision

Add the following immutable successor family:

- Workflow `pdf-document-review@1.2.0`;
- worker protocol `workflow-role/1.27.0`;
- result `pdf-document-review-result@3.0`;
- resolved plan `resolved-execution-plan/15.0`;
- control bootstrap `pdf-document-review-control-bootstrap/5.0`; and
- trusted receipt `document-review-evidence-validation-receipt/1.0`.

The existing `@1.1.0`, `@2.0`, protocol `1.26.0`, plan V14, and control V4
remain byte-stable and replayable.

### Exhaustive review contract

The V3 result requires exactly one verification target for each of the ten
closed review axes.  It also requires one ordered `item_review` per detected
question.  Each item record contains:

- question and solution anchors;
- a concise solution summary, ordered externally auditable solve steps, and final answer;
- answer-status and condition-sufficiency decisions;
- unit/dimension checks, including an explicit `NOT_APPLICABLE` rationale;
- ordered choice diagnostics for choice-bearing questions;
- ordered official-explanation step checks; and
- Graph evidence citations or an explicit insufficient-evidence state.

The contract does not request or persist hidden chain-of-thought.  It records
only concise verification conclusions, calculations needed to audit the
answer, and source anchors.

All ten axes must be present exactly once.  Every question and solution page
must be included in the corresponding page-coverage set.  Item keys,
question labels, choice keys, and explanation step ordinals are unique and
stable within the result.  Maps/sets are used for validation so these checks
are linear in the bounded result size.

`review_status=COMPLETE` is permitted only when all targets are `VERIFIED`, all
cross-document checks are `MATCHED`, all item-level mandatory decisions are
positive, every evidence status is `SUPPORTED`, and no candidate is
`UNCERTAIN`.  `FAILED`, `INSUFFICIENT`, `MISMATCH`, or `MISSING` therefore
forces `NEEDS_HUMAN_DECISION`.  Findings may still be complete and useful when
the aggregate requires a human decision.

### Document-to-Graph scope planning

The Catalog owns a new private `CREATE_DOCUMENT_REVIEW_EVIDENCE` application
operation.  It accepts the two exact `PdfReviewDocumentPointer` values and the
preset-selected immutable retrieval-policy pins.  It never accepts a caller
supplied Graph revision.

For each exact source PDF the Catalog:

1. validates logical Artifact ID, immutable Artifact Revision, member path,
   media type, schema, lifecycle, size, and SHA-256;
2. materializes the member only inside an operation-local directory;
3. runs the root-owned Poppler `pdftotext` executable without network access;
4. normalizes and bounds lexical terms; and
5. resolves matching nodes through the snapshot-local indexed
   `knowledge_node_terms(graph_snapshot_revision_id, term, node_id)` relation.

The dominant access pattern is exact Artifact lookup followed by indexed term
membership.  At most 512 distinct document terms and 131,072 term/node rows
are considered.  Node scores use deterministic inverse-frequency evidence,
then stable node identity; at most 20 sorted stable Graph keys are retained.
Retrieval resolves those keys first by the indexed exact stable-key lookup and
also retains its historical lexical fallback, so a label-derived match is not
lost by re-tokenizing an opaque key.
Expected complexity is `O(B + R log R)`, where `B` is bounded extracted text
bytes and `R <= 131072`; persistent space is unchanged because terms and
Evidence Bundle records already exist.

The chosen topic keys, a hash of the bounded normalized term set, the exact
extractor binary hash, both document identities, the educational retrieval
requirement, and the resulting Graph/Evidence pointers form a self-hashed
`DocumentReviewEvidencePlan`.  Broad integrated-science fallback evidence is
not invented: missing text or no matching controlled topic fails explicitly.

The simpler alternative—retrieving from the integrated-science root without
document-derived topics—was rejected because a bounded bundle would contain
arbitrary unrelated evidence and could not support per-item originality or
solution checks.  A model planning Workflow was also rejected for this
successor because it would require mutable execution-plan amendments or a
second asynchronously chained Workflow.  Deterministic indexed scope planning
is sufficient for the current PDF/HWP/HWPX text-bearing documents and keeps
one Workflow identity.

### Orchestrator validation and receipt

The V15 plan pins the exact request, preset/capacity revision, retrieval
requirement, retrieval request, Graph snapshot, access policy, Evidence Bundle
revision, manifest/context members, and one support step with
`EVIDENCE_CONTEXT` access.  The materializer stages only the two validated
Evidence Bundle members plus the already authorized document members.

The V3 result cites manifest evidence IDs and anchor IDs and points to scalar
leaves in its own item-review JSON.  Before NAS commit the orchestrator reloads
the V15 plan and exact Evidence Bundle manifest, validates every citation and
JSON Pointer, requires every item to have positive evidence or an explicit
insufficient status, and creates a self-hashed receipt bound to the pending
result Artifact.  The receipt is stored in the same transaction's single
`ARTIFACT_COMMITTED` event.  Missing, stale, mismatched, duplicate, or
unresolvable evidence fails before canonical Artifact commit.

Workers remain isolated: they read staged files and submit local structured
results.  They do not call Catalog, communicate with another worker, or write
NAS.  Catalog scope planning is an Application use case; orchestration and the
final commit remain owned by the existing Application/Orchestrator boundaries.

## Failure, retry, and idempotency

The public Review Set aggregate owns idempotency and rejects document, source
hash, preset, guidance, actor, or permission drift before evidence planning.
The private Catalog command derives its Evidence Bundle idempotency key from
that stable outer key plus the canonical submission hash; it is not a second
public idempotency registry. Catalog Evidence Bundle publication keeps its
existing unique request and immutable revision semantics.

Workflow creation occurs only after evidence planning succeeds.  Existing
Workflow and job idempotency remain unchanged.  A timeout is reconciled by the
same request key; a new key must not be used to guess the outcome.  No DB row
is rewritten and historical failures remain terminal evidence.

## Consequences

- Text-bearing PDFs and office documents receive reproducible, Graph-grounded
  exhaustive review evidence.
- Image-only/scanned documents without extractable text fail this strict path
  instead of claiming unrelated grounding.  OCR is a separate future
  successor, not an implicit fallback.
- The UI can continue rendering predecessor results.  V3 adds detail and
  grounding projections without exposing internal IDs by default.
- No database migration is required: immutable plans use the existing plan
  record, Evidence Bundles use existing Catalog tables, and receipts use the
  existing append-only job-event payload.

## Required tests

- JSON Schema 2020-12 and Pydantic parity for V3/V15/receipt contracts;
- predecessor schema and config byte preservation;
- exact ten-axis coverage and status fail-closed negatives;
- missing/duplicate item, choice, explanation, page, and anchor negatives;
- indexed lexical scope planning determinism, bounds, missing text, stale
  source, hash mismatch, and same-key replay;
- V15 materialization of exact documents and evidence only;
- unknown evidence/anchor/path, container/non-leaf path, plan drift, and
  missing/duplicate receipt rejection before NAS commit;
- API/query/UI predecessor/V3 union behavior; and
- package, formatter, linter, strict type-checker, focused unit/integration,
  and disposable-database persistence gates.
