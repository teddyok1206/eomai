# Full Textbook Knowledge Analysis

## Responsibility and boundary

This runbook defines a bounded operator batch for analyzing every physical page of the approved
Integrated Science Educational Documents while excluding Science Inquiry Experiment documents. It
does not let a worker enumerate Catalog data, read NAS, publish an Education Graph, or communicate
with another worker. Every page range is a normal Knowledge Analysis request routed through the
Application API, Catalog application boundary, orchestrator, and fixed support slot 05.

The canonical source remains the approved Educational Document Revision. The extracted Markdown
page is a validated workspace materialization; it is not a new canonical source. Every request pins
the document logical ID, document revision ID, source Artifact and Artifact Revision, SHA-256,
analysis-bundle and rights pointers, released Execution Preset Revision, risk-policy revision, and
workflow/protocol identities resolved by the existing application service.

## Access patterns and batch structure

The dominant operations are ordered page traversal, range overlap with curriculum mappings,
idempotent request creation, FIFO processing under one support-slot capacity, and append-only status
accounting. A protected batch manifest therefore stores an ordered immutable tuple of page ranges
and a map keyed by the stable range key for O(1) status lookup. PostgreSQL remains authoritative for
each Knowledge Analysis run and its lifecycle; the batch manifest is operator evidence, not a new
domain registry or a copy of worker output.

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

The initial production batch uses a conservative four-page maximum, matching the successful pilot
scale under the fixed 600-second worker sandbox. The Execution Preset may declare a larger policy
timeout, but that value does not override the systemd hard stop. Increasing the fixed worker timeout
is a separate infrastructure/security review and is not hidden inside this batch.

For `n` pages, planning is O(n + m log m), where `m` is the number of curriculum boundaries, and the
manifest is O(n / 4). Each request materializes at most four Markdown pages plus the pinned index,
well below the 32-page and 2 MiB source contracts. One support lease is active at a time; excess work
must queue rather than add slots or concurrent Codex processes.

## Transaction, failure, and review behavior

Each API create is its own idempotent transaction. A range is considered submitted only after the
API returns its canonical `analysis_run_id`; a lost response may be recovered only with the same
idempotency key and identical body. No failed worker run is automatically retried. Independent later
ranges may continue, while the failed range and evidence remain visible for explicit remediation.

Workflow completion is reconciled through the existing Knowledge Analysis application operation.
Low-risk proposals may become `ACCEPTED` according to the pinned released risk policy. Any
`NEEDS_REVIEW` run remains pending for a human decision; the batch must never synthesize approval.
Graph publication and Evidence Bundle generation are separate, explicitly authorized boundaries.

The batch coordinator must stop before creating work if the preset pointer, support capability,
auth binding, source revision, rights contract, page coverage, or curriculum mapping differs from
the reviewed manifest. It must also stop submitting new ranges when its authenticated operator
session is no longer fresh. It may resume only from its protected journal and immutable idempotency
keys; it may not guess missing state or resolve an implicit latest revision.

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
and no worker access to DB or NAS. Accepted results may later be published only through a separately
authorized deterministic graph-snapshot operation.
