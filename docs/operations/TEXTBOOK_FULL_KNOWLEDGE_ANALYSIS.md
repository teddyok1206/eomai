# Full Textbook Knowledge Analysis

## Responsibility and boundary

This runbook defines a bounded operator batch for analyzing every physical page of the approved
Integrated Science Educational Documents while excluding Science Inquiry Experiment documents. It
does not let a worker enumerate Catalog data, read NAS, publish an Education Graph, or communicate
with another worker. Every page range is a normal Knowledge Analysis request routed through the
Application API, Catalog application boundary, orchestrator, and fixed support slot 05.

The canonical source remains the approved Educational Document Revision. V8 requires the exact
lossless PNG for every selected physical page; extracted Markdown is only auxiliary OCR/text-layer
evidence and is not a substitute for the page image. Both are validated workspace materializations,
not new canonical sources. Every request pins
the document logical ID, document revision ID, source Artifact and Artifact Revision, SHA-256,
analysis-bundle and rights pointers, released Execution Preset Revision, risk-policy revision, and
workflow/protocol identities resolved by the existing application service.

## Access patterns and batch structure

The dominant operations are ordered page traversal, range overlap with curriculum mappings,
idempotent request creation, FIFO processing under one support-slot capacity, and append-only status
accounting. The durable Catalog batch aggregate stores normalized ordered range rows and immutable
pointers in PostgreSQL; it does not store page text or worker output. A protected operator manifest
is submission evidence, while PostgreSQL remains authoritative for batch, range, analysis-run, and
workflow lifecycles.

For each included current approved document revision:

1. enumerate physical pages `1..source_page_count` from its canonical analysis manifest;
2. place boundaries at every curriculum-mapping start and end plus the document ends;
3. subdivide each resulting interval into bounded ranges that fit the existing 32-page API limit
   and the fixed worker runtime budget;
4. attach the sorted unique curriculum unit keys whose mappings overlap that exact range;
5. require ranges to be ordered, non-overlapping, gap-free, and collectively equal the complete
   physical-page set exactly once;
6. derive one distinct idempotency key per pinned document revision and range; and
7. never substitute a newer revision after the manifest is frozen.

The historical pilot used a conservative four-page maximum. Current range size is frozen in the
reviewed batch request and must satisfy the existing 32-page API bound and the released preset's
7,200-second execution window. The fixed runtime contract keeps slots 01--04 at 600 seconds and
pins only support slot 05 to 7,200 seconds; the resolved plan value must reach the launcher exactly.
Operators must not change range boundaries or timeouts after creation. V8 pins
`workflow-role/1.8.0`, request `/6.0`, and multimodal worker proposal `/4.0`. V4--V7 batches remain
immutable historical evidence and are not published as the current multimodal textbook corpus.

For `n` pages, planning is O(n + m log m), where `m` is the number of curriculum boundaries, and the
manifest is O(n / r) for frozen range size `r`. Each request materializes its bounded ordered PNG
set, the matching Markdown aids, and the pinned index. The measured 32-page upper-bound fixture used
21,232,796 image bytes (15.82% of the 128 MiB aggregate limit), with a largest image of 1,868,693
bytes (11.14% of the 16 MiB per-image limit). One support lease is active at a time; excess work must
queue rather than add slots or concurrent Codex processes.

## Transaction, failure, and review behavior

One fresh-auth API operation authorizes and creates the complete durable batch. The Catalog-owned
runner subsequently claims one range at a time with its persisted lease and advances it through the
ordinary Knowledge Analysis service; it neither retains nor manufactures a browser session. A lost
internal response is recovered only by the existing immutable idempotency key and identical body.
No failed worker run is automatically retried. A failed range is preserved and blocks that batch;
recovery requires a separately reviewed new batch or explicit domain operation, never mutation of
the failed row.

Workflow completion is reconciled through the existing Knowledge Analysis application operation.
Low-risk proposals may become `ACCEPTED` according to the pinned released risk policy. Any
`NEEDS_REVIEW` run remains pending for a human decision; the batch must never synthesize approval.
Graph publication and Evidence Bundle generation are separate, explicitly authorized boundaries.
V8 content acceptance has no minimum extraction quota: `NO_RELEVANT_CONTENT` and `UNCLEAR` are
valid page observations. Exact image delivery, one observation per page, hashes, safe pointers, and
internally valid references remain hard requirements.

Batch creation must stop if the preset pointer, support capability, source revision, rights
contract, page coverage, or curriculum mapping differs from the reviewed manifest. After that
single authorization transaction commits, ordinary progress is intentionally independent of the
browser session lifetime. The runner resumes only from indexed PostgreSQL state, leases, and
immutable idempotency keys; it may not guess missing state or resolve an implicit latest revision.

## Alternatives and trade-offs

A single whole-book prompt is simpler, but violates the 32-page selection contract, risks context
and result limits, weakens page-level provenance, and cannot isolate failures. Submitting every
range concurrently would shorten operator interaction but creates avoidable capacity-retry churn
against a one-slot pool. A persistent batch aggregate and scheduler may be justified after this
bounded corpus rollout provides scale and failure measurements; pre-building that framework now
would add schema, migration, and lifecycle complexity before a second real use case exists.

## Completion evidence

Completion requires every included document revision to have gap-free terminal range accounting,
no Science Inquiry Experiment document, immutable source/preset/risk pointers, no automatic retry,
exactly one PNG observation per physical page, and no worker access to DB or NAS. The background
batch may occupy only slot 05; slots 01--04 remain available for one-item workflows and GUI-backed
product work. Accepted results may later be published only through a separately authorized,
overlap-rejecting deterministic graph-snapshot operation.
