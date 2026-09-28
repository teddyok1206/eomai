# ADR 0137: Add a separate object-line-art campaign successor

## Status

Accepted for protocol-first, evaluation-only implementation on 2026-09-28 UTC. This decision does
not activate an adapter or reinterpret the immutable raster-texture campaign review.

## Responsibility and system boundary

The 768-candidate science visual campaign contains both deterministic diagrams and useful object
illustrations. Its existing review answers a different question: whether a candidate is suitable
for raster texture learning. It therefore classifies many people, vehicles, specimens, and
equipment with diagrams, even though a bounded crop of those objects is useful for assessment
line-art style learning.

The new boundary records a second, independent suitability axis. A reviewer selects only isolated
object morphology; the Orchestrator resolves the pinned campaign candidates, performs literal
rectangular crops, validates every byte, and publishes an immutable crop set. The isolated trainer
reads staged files and can only produce an `EVALUATION_ONLY` adapter with activation `FORBIDDEN`.

## Canonical source and revision model

```text
published campaign pattern inventory + approved training authorization
  -> immutable object-line-art suitability review
  -> immutable object-line-art crop-set revision
  -> immutable 16 TRAIN / 4 VALIDATION / 4 HOLDOUT probe plan
  -> isolated adapter result
  -> paired semantic and reference-composition evaluation
  -> human style review
  -> separate future activation decision
```

The suitability review and crop set pin exact Artifact revisions and SHA-256 values. Candidate ID,
crop-set sample ID, Artifact ID, Artifact Revision ID, and content hash remain separate. Existing
raster review, crop sets, adapters, and failed or successful probes are never rewritten.

## Suitability decisions

Each of the 768 candidates receives one decision on the line-art axis:

- `OBJECT_LINE_ART_ELIGIBLE`: a literal crop can preserve one useful object or pose without answer
  content;
- `DETERMINISTIC_RENDERER_ONLY`: authoritative geometry, plots, tables, circuits, labelled
  apparatus, or other content that belongs in Python/SVG/HWPX;
- `RASTER_STYLE_ONLY`: astronomy, microscopy, geology, or other texture-first imagery handled by
  the separate raster adapter;
- `EXCLUDED`: redaction damage, insufficient content, duplication, or unsafe composition.

Only an eligible entry carries an object family, exact crop box, and bounded English morphology
caption. Text, labels, values, arrows, answer-bearing geometry, redaction holes, and background
clutter are explicit disqualification reasons. The crop box is a selection instruction, not a new
identity; the resulting member has its own immutable sample ID and hash.

## Access patterns and data structures

Dominant operations are candidate lookup, review coverage, partition membership, crop membership,
deduplication, and ordered manifest assembly. Validators use dictionaries keyed by candidate and
sample ID, counters keyed by source document and exam group, and sets for exact/perceptual hashes.
For at most 768 candidates and 96 crop members, validation is `O(C + M)` time and memory. Canonical
wire order is a sorted tuple. Existing Artifact/Revision indexes and publisher idempotency keys are
sufficient; no database table, queue, cache, or migration is added.

The first expanded probe remains exactly 24 independent members: 16 TRAIN, 4 VALIDATION, and 4
HOLDOUT. A document may contribute at most three members and an exam group at most four, while one
exam group may appear in only one partition. Parent candidate, exact crop bytes, and perceptual hash
are unique.

## Transaction, concurrency, retry, and idempotency

All 768 decisions and source pointers are validated before publication. Crop bytes are materialized
into a fresh workspace, checked for source bounds, decoded dimensions, exact hash, and perceptual
duplication, then committed as one Artifact file set by the Orchestrator. Same semantic input is
idempotent; drift under a derived identity conflicts. Trainers have neither NAS nor PostgreSQL
access. Failed attempts remain immutable evidence and are not retried under a new identity without
a new plan.

## Dependency direction and adapter ownership

JSON Schema 2020-12 and frozen Pydantic value models live in `image_contracts`. Application scripts
validate commands and call Orchestrator resolution/publication adapters. PostgreSQL, NAS, workspace,
systemd, and model execution remain infrastructure details. Domain contracts do not import those
adapters, and workers do not orchestrate or publish.

## Failure behavior

Missing or stale candidates, incomplete review coverage, source hash drift, a crop outside its
candidate bounds, label/redaction contamination, cross-partition group reuse, duplicate parent or
image content, or an unsupported lifecycle fails closed. There is no implicit latest resolution,
automatic caption repair, inpainting, erasure, or padding with duplicate crops. Activation remains
forbidden until semantic holdouts, composition preservation, style review, and human review all
pass.

## Simpler alternatives rejected

Reclassifying the raster suitability review would change the meaning of released evidence. Mixing
object drawings into the raster-texture adapter would blur two distinct targets. Repeating the
14-sample probe or lowering the 100-sample production gate would overstate dataset diversity. A new
generic training framework is unnecessary: the additive review/crop-set contracts and a narrow
successor of the existing campaign probe are the smallest change that preserves provenance and
enables a broader object-line-art experiment.
