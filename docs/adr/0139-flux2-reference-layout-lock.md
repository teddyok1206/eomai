# ADR 0139: FLUX.2 reference layout lock

- Status: accepted for evaluation-only implementation
- Date: 2026-09-28

## Context

The bounded FLUX.2 Klein probe established that the candidate model can produce an
acceptable monochrome assessment-line-art style.  Prompt-only composition control did
not reliably preserve the reference foreground's scale and placement.  Production
activation remains forbidden.

The dominant operations are one keyed lookup per probe case, one foreground bounding-box
scan per raster, and ordered immutable output assembly.  Probe scale is 3--12 images of at
most 800 x 512 pixels, so a linear O(cases x pixels) raster scan is the appropriate and
simplest data structure.  No database, queue, cache, or new worker-to-worker protocol is
needed.

## Decision

Add immutable successor contracts:

- `local-image-flux2-reference-probe-plan/1.1`
- `local-image-flux2-reference-probe-command/1.1`
- `local-image-flux2-reference-probe-result/1.1`

The plan pins `local-image-reference-layout-lock/1.0`.  The adapter:

1. derives a half-open foreground bounding box from the staged conditioning image with
   the already-pinned luma threshold 245;
2. maps its vertical coordinates from the 800 x 504 conditioning canvas to the 800 x 500
   delivery canvas with outward rounding;
3. preserves the unmodified 800 x 500 model output as `RAW_CANDIDATE`;
4. crops the raw candidate to its tight foreground bounding box;
5. resizes that crop to the exact mapped reference box with deterministic LANCZOS
   resampling and composites it on a white 800 x 500 canvas as `LOCKED_CANDIDATE`;
6. emits the unchanged conditioning image and typed measurements for all three boxes.

Successful results require exactly one raw, one locked, and one conditioning output per
case.  The locked box must equal the mapped reference box, its area ratio must be 1000
millipercent-of-ratio (1.0), and its normalized center displacement must be zero.  Empty
foregrounds fail closed.  Raw output retention makes the transform auditable and prevents
the adapter from being confused with model quality.

## Identity and boundaries

The existing model manifest, normalized visual-reference revision, conditioning bytes,
probe plan, command, and result remain separately pinned by logical IDs, immutable
revision IDs, schema references, and SHA-256 hashes.  Workspace files are temporary
materializations.  Only the existing publication application commits validated members
to NAS.  V1.0 schema bytes and published artifacts remain unchanged.

The runner owns raster transformation as an infrastructure adapter.  Contracts own only
the policy and measurements.  The orchestrator remains the sole work router and
publication authority; the worker does not write NAS.

## Failure, retry, and concurrency

All output is first written exclusively to a pending directory and renamed only after
schema, Pydantic, hash, image, and cross-field validation.  Any empty foreground,
out-of-bounds box, hash mismatch, or output mismatch produces the existing stable
fail-closed result.  A retry uses the same immutable command in a fresh workspace; it does
not mutate or reinterpret an earlier result.

## Alternatives

Prompt-only instructions were insufficient in two bounded runs.  Feeding a second
control network or training another adapter would add model and dependency risk before
proving that deterministic placement solves the isolated problem.  Masking to the source
silhouette would over-constrain legitimate detail and hide topology errors.  Exact-bbox
placement is therefore the smallest auditable successor; subject topology remains a
separate human/model-quality gate.

