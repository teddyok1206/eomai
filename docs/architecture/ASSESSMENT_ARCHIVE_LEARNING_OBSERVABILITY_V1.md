# Assessment Archive Learning Observability V1

## Responsibility and boundary

The Application API exposes read-only progress for reviewed assessment-archive extraction,
automatic Item promotion, knowledge analysis, and Graph publication. The Studio renders that
projection as the **자료 학습** administrator view. This feature never submits work, accepts an
Item, publishes a Graph, or reads source bytes.

## Canonical source and pointers

Existing durable records remain authoritative: extraction batch and work-unit rows, immutable
assessment occurrence and bundle revisions, layout observations, acceptance decisions, Item
revisions, Knowledge Analysis runs, and the current `integrated-science-textbooks` Graph snapshot.
The projection pins and returns their IDs; it does not persist a second progress state. Logical
batch, immutable occurrence revision, Item revision, analysis run, and Graph snapshot identities
remain distinct.

## Access patterns and structures

The dominant operations are recent-batch listing and one-batch ordered exam listing. Both use
indexed batch IDs and grouped SQL queries. Work-unit state counts are grouped by
`(extraction_batch_id, state)`. Exam identity is deduplicated by
`(extraction_batch_id, assessment_source_bundle_revision_id)` before joining the occurrence and
layout. Accepted decisions, promoted Items, latest analysis state, and current-snapshot membership
are aggregated in bulk. No source Artifact or large manifest is loaded and no per-row query is
issued.

The expected scale is at most 10,000 work units per extraction batch and hundreds of exams. Query
space is linear in the indexed rows selected for the requested batch set; response size is bounded
to 50 batches or 500 exams.

## Image and text evidence policy

Every extraction work unit is protocol-valid only with at least one pinned PNG page input, and the
released worker instruction requires inspecting every supplied image. The progress contract reports
this as `image_observation_mode=REQUIRED`. OCR or PDF text may assist page/item segmentation when
available but cannot replace visual inspection; the contract reports
`text_evidence_mode=AUXILIARY_WHEN_AVAILABLE`.

## Concurrency, failure, and idempotency

The endpoint uses one read-only database transaction per request. Counts are observations and may
advance between requests; one response is internally derived from a single transaction. Terminal
failures remain visible and are never rewritten as success. Refreshing the view has no side effect.

## Dependency direction and simpler alternative

JSON Schema and API Pydantic models define the projection. The Application API query adapter owns
SQL aggregation, the BFF validates the upstream response, and the browser only presents it. Reading
the extraction manifest from NAS was rejected because it would mix source-byte infrastructure into
a status query and repeatedly parse a large immutable file. Persisting a duplicate campaign state
was rejected because the existing state machines already own every displayed fact.

