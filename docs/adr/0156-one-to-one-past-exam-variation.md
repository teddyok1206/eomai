# ADR 0156: One-to-one past-exam variation

## Status

Accepted for implementation.

## Responsibility and boundary

Scientific Studio may start a new generated Item from one explicitly selected, immutable
past-exam Item Revision.  The feature is a successor of the existing graph-grounded item workflow;
it is not Item revision, free-text prompting, or a second retrieval system.  Studio captures the
selection, Application API starts the workflow, Catalog resolves the exact source into one Evidence
Bundle, Orchestrator validates and materializes it, workers return structured results, and Catalog
alone registers the approved new Item and its lineage.

Workers do not communicate with one another and do not write to NAS.  The existing orchestrated
authoring/review rework loop remains authoritative.

## Canonical source and revision model

The canonical source is an occurrence-backed Catalog Item and one pinned Item Revision.  A request
stores the immutable `item_revision_id`; it never resolves an implicit latest revision during
execution.  The resulting question is a new logical Item, not a revision of the source Item.

The derivation flow is:

```text
source Item -> pinned source Item Revision -> pinned ITEM_CONTENT Artifact Revision + SHA-256
            -> variation Workflow/Evidence Bundle
            -> new Item -> new approved Item Revision
```

The registration transaction writes one unique `PAST_EXAM_VARIANT_OF` relationship from the new
Item to the source Item and source-revision provenance for the new Item Revision.  Historical source
or generated revisions are never changed.

## Contracts and pointer checks

`past-exam-variation-request/1.0` identifies the source revision and a sorted, unique set of
transformation axes. `educational-retrieval-requirement/2.0` embeds that request and is accepted only
for `ITEM_PREPARATION` with exactly `PAST_EXAM` sources. `workflow-start/4.0` binds it to the
`generic-item-development@1.14.0` successor. `resolved-execution-plan/16.0` pins the requirement,
Evidence Bundle, Graph snapshot, preset, Content Pack, and their hashes.

Resolution must prove that the selected revision exists in the pinned Graph as an occurrence-backed
PAST_EXAM source and that the Evidence Bundle contains only that source revision for Item evidence.
For an exact variation, the indexed assessment-occurrence placement for the pinned Item Revision is
the retrieval seed.  Legacy accepted past-exam Items do not have the content-team
`item_element_refs` projection, so the output-oriented `required_item_elements` filter must not be
used as an eligibility test for the selected source.  Ordinary non-targeted retrieval continues to
use that filter.  The placement's source pointers must still resolve back to the exact accepted
analysis and PAST_EXAM Item Revision before it can become evidence.
The source content pointer is accepted only from the plan-pinned, hash-verified Evidence manifest;
its Artifact/Revision, schema, media type, lifecycle, manifest entry, byte count, and SHA-256 are
validated before temporary materialization.  Missing, stale, ambiguous, or mismatched pointers fail
closed.  No latest-revision substitution is allowed.

## Access patterns and data structures

Primary operations are indexed lookup by `item_revision_id`, membership/deduplication of evidence
and axes, ordered immutable iteration of axes, and unique lineage insertion.  The exact source seed
uses `ix_assessment_item_ref_item_revision`; generic element-filtered retrieval retains
`ix_item_element_revision_kind`.  In-memory maps/sets provide O(1) expected membership and the
existing B-tree/foreign-key lookups resolve Items, Revisions, components, and Graph references. The
existing unique relationship key
`(source_item_id, target_item_id, relationship_type)` prevents duplicate lineage.  Expected scale is
one source and at most six axes per workflow, so plan and validation work is O(E + A), where E is the
bounded Evidence entry count and A is the axis count.

## Transactions, concurrency, retry, and idempotency

Workflow creation keeps the existing API and Catalog idempotency boundaries.  Evidence retrieval is
keyed by the canonical requirement, including the source revision and axes.  Registration creates
the Item Revision, provenance, and relationship in the existing registration transaction.  An
idempotent replay returns the previously registered revision and does not insert another lineage
row.  Concurrent duplicate registration remains protected by the existing registration key and
unique relationship constraint.

## Dependency direction

Studio depends on its typed Web contract; Web maps to the public API contract; Application API calls
the Catalog application boundary; Orchestrator consumes the workflow/control contracts; Catalog
implements retrieval and Registry persistence.  Domain and contract packages do not import service
or filesystem adapters.

## Failure behavior

The request fails before workflow creation if the selected revision is not an eligible past-exam
Graph source.  Materialization fails before worker start for pointer or hash errors.  Authoring must
cite the selected source as `STRUCTURE_PATTERN`; review independently checks the requested axes and
originality.  Registration fails before Item writes if the plan, source provenance, receipt pair, or
source Revision differs.  Existing workflows and released V1 contracts retain their behavior.

The bounded primary/escalated review selector accepts both the original
`resolved-execution-plan/12.0` family and this feature's explicit
`resolved-execution-plan/16.0` successor. Selection is by the schema discriminator before Pydantic
validation; it never coerces an unknown plan into V12. This keeps the primary review, optional
stronger review, and at-most-three authoring rework cycles available without changing either
released plan's bytes.

## Simpler alternative rejected

Putting an Item ID into free-text authoring guidance is insufficient: it cannot pin a revision,
constrain retrieval to one source, authorize source content materialization, mechanically validate
the citation, or preserve lineage.  Reusing `REVISE_ITEM` is also incorrect because a past-exam
variation is a new logical Item, not a mutation of the source Item.
