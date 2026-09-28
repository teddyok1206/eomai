# ADR 0144: HYBRID SVG overlays remain transparent

- Status: Accepted
- Date: 2026-09-28

## Context

Content Pack 1.20.3 made the existing V1 local image provider consume the exact approved visual
reference.  A live item canary then exposed a separate handoff error: an image worker returned a
valid safe-SVG document whose first element was an opaque white rectangle covering the complete
800×500 canvas.  Required labels were present and the image-result Artifact was valid, but the
fixed rasterizer encoded the overlay as RGB instead of the required RGBA overlay.  Catalog correctly
refused to compose it because the rectangle would hide the reference-conditioned raster.

The canonical input remains the immutable image-result Artifact.  The SVG is an authoritative
overlay, not a background image.  Local GPU/reference bytes remain an independently pinned raster
input.  No existing Pack, result schema, workflow, Artifact, or database row is rewritten.

## Decision

Publish immutable Content Pack `generated-knowledge-item@1.20.4` as a prompt-only successor to
1.20.3.  For `LOCAL_GENERATIVE_BACKGROUND` and `HYBRID_LOCAL_GENERATIVE`, the image worker must:

- keep the SVG canvas transparent;
- omit every full-canvas background rectangle or other opaque background fill;
- put only authoritative labels, arrows, axes, walls, guides, and bounded geometry in the overlay;
- leave photographic/organic appearance and the white exam-page background to the local raster
  provider and final renderer respectively.

The existing fixed PNG validator remains fail-closed.  It continues to require an 800×500 RGBA
overlay, so a worker that ignores the prompt cannot silently obscure the generated raster.
Pack 1.20.4 selects the same reference-composition prompt policy and V1 reference-conditioned
provider protocol as 1.20.3.

## Access pattern and complexity

Pack selection is one keyed version lookup.  Overlay validation reads one bounded PNG header and
the compositor processes one bounded SVG (`<=96 KiB`), all `O(n)` in the single overlay size with
constant auxiliary metadata.  No new table, index, queue, cache, or cross-service message is added.

## Transaction, retry, and rollback

Worker output is still committed only after schema and Pydantic validation; Catalog alone writes
the final generated stimulus Artifact.  Existing workflow retry/idempotency behavior is unchanged.
Rollback activates immutable Pack 1.20.3 for future workflows.  Workflows already started with
1.20.4 retain their pinned release.

## Rejected alternative

Silently stripping arbitrary white shapes during rendering was rejected because a white rectangle
can be scientifically meaningful.  Accepting RGB overlays was also rejected because an opaque
canvas would hide the reference-conditioned raster.  A new result schema is unnecessary: the
existing contract already defines this member as the transparent overlay, and the defect was an
instruction gap rather than a new data shape.
