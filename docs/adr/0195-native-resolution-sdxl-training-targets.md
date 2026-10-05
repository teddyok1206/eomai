# ADR 0195: Explicit native-resolution SDXL target preparation

## Status and purpose

Accepted for protocol-first, CPU-only implementation on 2026-10-05 UTC. This
implements the next source-to-training boundary of the illustration-quality goal;
it does not authorize an unbounded model experiment or claim generation quality.

Native576 preparation is complete for seven TRAIN regions, but its source state
is PENDING_TARGET_REVIEW. Some regions still have annotation/caption/margin or
original raster-resolution limitations. Released target1.0/1.1 always emit768x512
with optional masks; released micro training1.0/1.1 accepts only that geometry.
Do not substitute higher-resolution files under those identities or train a
person-heavy seven-image cohort again merely because this CPU step passes.

## Responsibility, canonical source and identities

Add target-command/result1.2 over a pinned native-PDF crop-set1.0. The source set
points to its immutable crop command, which pins the original source review and
PDF/grid recipe. Reuse the corpus authorization, complete metadata lineage and
existing reviewed-target worker/application/file-set commit owners. Source PNGs,
captions, old targets, partitions and historical adapters remain immutable.

The new command has an independent content-derived run ID/semantic hash. Every
source-set selection receives exactly one explicit PREPARE or DEFER decision.
PREPARE pins a reviewed caption, expression, literal normalized frame and one of
three closed canvases:1024x1024,768x1024,1024x768. Masks are structurally forbidden.
Output target logical ID/revision/raw SHA and caption SHA remain distinct; source
set/command/review/authorization form a small pinned source snapshot. A corrected
derived caption never edits the legacy source caption or implies scientific truth.
Variable-canvas binary members use target-PNG descriptor1.1, not the released
768x512 target-PNG1.0 identity. Their exact dimensions/recipe are owned by result1.2.

## Pointer resolution and media admission

Before PNG reads, validate all four source metadata members: native set, its
command, original review and authorization. Check raw hash, canonical bytes,
schema/version/media/member, exact identities, chronology, selected TRAIN IDs,
frame4x dimensions, permission/lifecycle and full original/supplemental provenance.
Unknown/dangling/stale/hash mismatch is an explicit error; no latest fallback.
Resolve only PREPARE PNGs once in a bounded indexed batch. Deferred PNGs, original
PDF/page pixels and VALIDATION/HOLDOUT bytes are not workspace inputs.

## Target recipe and data structures

Reuse rational reviewed-frame fitting. Extract that pure arithmetic into one
shared geometry owner with typed immutable values; old768x512 calls keep their
exact results. Native target policy is grayscale RGB, aspect-preserving LANCZOS
fit, centered white canvas, margin32, no foreground inference/mask/OCR/enhancement.
Maximum upscale is explicitly pinned1000..2000 milli. Upsampling is conventional
target normalization, never additional optical detail or another independent
drawing. Source-native pixels and their resolution limitations stay separately
available. Canvas choice is caller-reviewed, not silently guessed from a filename.

Use map/set for selection membership and exact coverage, sorted frozen tuples
for decisions/samples/outputs, and an immutable three-entry canvas lookup. Each
native source command has at most32 regions, so this preparation is a bounded
batch, not the complete100–200-image training population. Future training must
compose distinct prepared revisions and validate source-document/group diversity;
this change does not enlarge released96-sample/200-step micro budgets. Admission
is O(S), raster work O(output pixels), metadata O(S), with8MiB per PNG and existing
128MiB aggregate read bounds. No DB/index/queue migration is needed.

## Ownership, concurrency, failure and retry

Contracts own frozen decisions/geometry/provenance/result validation, not I/O.
Orchestrator owns metadata/media resolution, local workspace staging, supported
isolated dispatch and validated canonical commit. The existing image worker reads
only staged local metadata/PNG files, emits local target/result files and performs
no model/GPU/NAS/DB/auth work. Extend its existing target entry point with this
third closed protocol; do not create a parallel executor or generic plugin layer.

Reuse exclusive workspace creation, canonical result receipts and read-only
terminal replay. A failed result remains FAILED; unreceipted output/unknown live
completion blocks redispatch rather than obtaining another identity. Canonical
publication remains the existing unique idempotent transaction/commit owner.
Prepared targets stay UNREVIEWED_TRAIN_TARGET_CANDIDATES with activation FORBIDDEN.
An explicit post-preparation review and a successor full-training contract remain
separate gates. No production model/service/prompt or worker privilege changes.

## Simpler alternatives and tests

Reusing768x512 loses native detail on tall drawings and silently changes old
geometry; padding every drawing into a forced square unnecessarily changes
composition. Three explicit SDXL-sized canvases plus one shared fit rule cover
current shapes without a bucketing framework or dependency. Repainting annotations
would contaminate source evidence and is outside this native preparation recipe.

Test schema/Pydantic/canonical/hash equivalence, frozen predecessor bytes, all
three geometries, scale/margin/frame bounds, exact source/decision closure,
reviewed caption hashes, masks/unknown canvases/reserved sources, missing/stale
pointers, duplicate PNGs, metadata-before-media and PREPARE-only reads, worker
output/failed receipts/no-write replay, CLI/wheel compatibility and dependency
direction. Installed-role CPU execution/actual target inspection are distinct
from synthetic tests, GPU training, held-out comparisons and independent review.

## Implementation gates — 2026-10-05 UTC

Focused synthetic/regression suite322 PASS, including46 native-target cases and
two explicitly opt-in synthetic Poppler cases; strict typing7 source files,
Ruff/format, shell syntax and diff checks PASS. The full dependency audit remains
5 PASS/1 unchanged failure: predecessor`source_page_crop_expansion_inputs.py`
imports pure planning rules/errors from Catalog infrastructure. This predates
this successor; no added import crosses that boundary and the audit is not
weakened. Move the existing rules to their correct shared domain owner in a
separate focused maintenance change. Installed-role execution, actual PNG review
and canonical publication are still separate evidence, not implied by these tests.
