# ADR 0127: Preserve campaign partitions through reviewed raster refinement

- Status: Accepted for protocol-first implementation
- Date: 2026-09-26 UTC
- Scope: the immutable 768-candidate science-visual campaign in ADR 0126

## Context and responsibility

The campaign strict review admits only five original crops directly. Useful natural-image panels
remain inside otherwise rejected page fragments, while deterministic plots, labels, masks, and
answer-bearing geometry must stay out of a raster LoRA dataset. The earlier single-pilot
refinement shape is train-only and binds one result; it cannot express the three-shard campaign or
preserve the campaign's existing validation and holdout partitions.

The Orchestrator owns source resolution, deterministic cropping, pixel/hash validation, group
deduplication, and publication. It may invoke a local deterministic image adapter, but no agent
worker reads PostgreSQL or NAS and no worker publishes files. Canonical source remains the
published campaign inventory revision and its pinned pilot-result revisions. A workspace crop is
only temporary materialization.

## Immutable chain and pointer checks

```text
campaign inventory revision
  + campaign strict-review revision
  + common training-authorization revision
  -> campaign raster-refinement plan revision
  -> campaign crop-set revision containing canonical PNG members
  -> evaluation-only campaign micro-probe successor
```

The plan pins the inventory, strict review, authorization, every parent candidate ID and SHA-256,
its normalized crop box, corrected caption and original source partition. Resolution verifies
target/revision existence, approved lifecycle, schema, media type, member path and content hash.
It never resolves an implicit latest revision or substitutes a different shard.

The crop set pins the plan and preserves logical sample ID, parent candidate ID, optional
refinement ID, output PNG hash and dimensions as distinct concepts. PostgreSQL stores only
Artifact metadata and pointers; PNG bytes remain in the one crop-set Artifact file set.

## Access patterns and data structures

Dominant operations are exact candidate lookup, membership, group deduplication, ordered
iteration, and immutable manifest assembly. Validators use dictionaries keyed by candidate and
refinement ID, sets for coverage/uniqueness, and sorted tuples for canonical output. Work is
`O(c + r)` time and memory for at most 2,048 campaign candidates and 1,024 refinements. The crop
set selects at most one member per document and exam-group hash, then uses the existing bounded
perceptual-hash band lookup rather than an all-pairs scan.

No new database table or index is needed: existing Artifact/Revision indexed identities and
unique idempotency keys own publication.

## Partition and quality policy

Refinement never moves a sample between partitions. A proposal's TRAIN, VALIDATION, or HOLDOUT
value must equal the pinned source's partition. This campaign successor intentionally differs from
the earlier train-only single-pilot plan: the campaign already assigned disjoint exam groups before
visual review, and a fixed clean crop is required to retain two independent holdout groups. No
group may appear in more than one crop-set member.

Only a strict-review `GPU_RASTER_ELIGIBLE` parent may pass through unchanged. An excluded parent
may be refined only when it is non-authoritative raster material and its reasons show removable
layout contamination or a caption mismatch. `PYTHON_SVG_REQUIRED`, plot/table representations,
authoritative geometry, synthetic erasure, inpainting, padding, and content reconstruction are
forbidden. A refined output must be a literal rectangular pixel crop, at least 32 pixels on each
side, with no resize before publication.

The campaign crop set requires at least 12 distinct TRAIN groups, one VALIDATION group and two
HOLDOUT groups. Training normalization happens later in the pinned trainer workspace and never
changes canonical crop bytes.

## Transaction, retry, and failure

All pointers and source bytes are validated before a NAS commit. The Orchestrator writes one
manifest and its PNG members atomically through the existing Control Artifact publisher. Same
semantic input is idempotent; a different payload under the same derived identity conflicts.
Missing/stale/hash-mismatched sources, duplicate boxes, partition drift, a non-literal crop,
caption mismatch, unsafe member path, near-duplicate group, or undersized partition stops before
publication. Failed attempts remain historical and retries use the same immutable plan.

## Simpler alternative rejected

Training on whole panels would increase count while teaching labels, blank answer masks, and page
layout. Discarding all panels leaves too few independent groups. Reusing the single-pilot plan
would either lose two shards or silently reassign holdouts. The additive campaign plan and crop
set are the smallest contracts that recover useful pixels while preserving provenance,
partitioning, rollback, and the prior released contracts.
