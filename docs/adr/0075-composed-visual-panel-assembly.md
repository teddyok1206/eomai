# ADR 0075: Composed visual panel assembly

## Status

Accepted.

## Responsibility and canonical source

The image worker owns the ordered semantic drawing intent for each `IMAGE` member in the approved
Item draft.  For a hybrid drawing, the local GPU provider may create only the non-authoritative
background.  The validated SVG overlay remains authoritative for labels, arrows, axes, values, and
answer-relevant geometry.  Catalog composes those two layers and commits one immutable final PNG
Artifact Revision per visual ordinal.  The HWPX builder consumes only those exact pinned final PNG
pointers; it does not regenerate, relabel, merge, or infer images.

The existing contracts already express the complete bounded shape, so this decision does not add a
wire schema or database migration:

| Ordered image count | Canonical layout | Labels |
| --- | --- | --- |
| 0 | `NONE` | none |
| 1 | `IMAGE_ONLY` | `""` |
| 2 | `IMAGE_IMAGE` | `"(가)"`, `"(나)"` |

A single image must never acquire `(가)` or `(나)`.  A two-image item must preserve visual ordinal
0 on the left as `(가)` and ordinal 1 on the right as `(나)`.  Scientific labels inside an image,
such as `A`/`B`, `P`/`Q`, or a measured value, are independent worker-authored overlay labels and
must not be confused with the HWPX panel labels.

## Access pattern, structure, and complexity

The canonical collection is an immutable ordered tuple bounded to two members.  Catalog and HWPX
perform one ordered pass and direct ordinal comparison, O(n) time and O(n) transient pointer space
for `n <= 2`.  Order is part of identity, so a set or unordered map would be the wrong structure.
Artifact lookup remains by immutable artifact/revision identity and SHA-256; image bytes are
materialized only at provider composition, validation, and HWPX assembly boundaries and are never
stored in PostgreSQL.

## Validation, failure, and retry

The acceptance suite must exercise the real safe-SVG sanitizer and rasterizer, the real Pillow
alpha compositor, and the real reviewed HWPX slot renderer.  These infrastructure adapters remain
in their separate runtime environments; the suite joins them through the same immutable PNG
pointer and hash contract used in production instead of importing one adapter into another.  It
proves that:

1. arbitrary required scientific labels and geometry survive deterministic overlay rasterization;
2. the overlay is applied over the generated-background-sized canvas;
3. each composed PNG is embedded byte-for-byte at its original visual ordinal;
4. one image removes the panel-label row, while two images render `(가)` then `(나)`; and
5. label, count, ordinal, pointer, or hash drift fails before HWPX publication.

Workers still write only local results.  Catalog and the orchestrator retain provider invocation,
validation, artifact commit, and NAS ownership.  A failed attempt is preserved and a retry uses the
existing immutable workflow/build identities; there is no silent fallback or image substitution.

## Alternative

Flattening two panels into one generated bitmap would make panel order and labels part of
unvalidated pixels, weaken accessibility and reuse, and prevent exact per-image provenance.  Adding
a successor schema would add version surface without a missing field.  The existing ordered pointer
model plus one cross-boundary acceptance gate is the simplest complete expression of the current
requirement.  A future layout with more than two panels must use a protocol-first successor rather
than extending these literals in place.
