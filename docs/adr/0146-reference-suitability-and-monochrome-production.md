# ADR 0146: Reference suitability and monochrome production guard

## Status

Accepted for implementation on 2026-09-28 UTC.

## Responsibility and boundary

The Wikimedia adapter supplies non-authoritative object morphology to the local assessment-image
provider. It does not own labels, answer-bearing geometry, panel layout, or final HWPX placement.
The image provider may preserve the selected reference composition, but the final morphology raster
must still satisfy the existing white-page monochrome presentation rule.

An actual item canary exposed two gaps: Commons relevance order selected a multi-object fossil/cast
file ahead of cleaner alternates, and the diffusion result retained substantial source color even
though the prompt prohibited color. The content-team prompts remain authoritative and unchanged.

## Canonical source and identity

The canonical morphology source remains the immutable visual-reference bundle revision and its
normalized PNG member. Candidate identity, page revision, license, source hash, generated request,
provider receipt, final PNG revision, and final hash remain separate. Historical bundles and output
artifacts are not modified.

## Selection and raster rules

Within the already bounded, metadata-verified Commons candidate set, a stable suitability key first
deprioritizes file titles that explicitly advertise a montage, collection, group, display, plate,
multiple specimens, or a cast comparison. A requested viewpoint word in the title is preferred;
official relevance order and page ID remain deterministic tie-breakers. This is a heuristic, not a
semantic guarantee, so all candidates remain pinned in the intent and the selected source remains
auditable.

If the exact viewpoint query yields no image under the existing public-domain/CC0 policy, discovery
performs at most one deterministic subject-only fallback by removing a closed set of viewpoint and
white-background modifiers. It does not relax licensing, media, host, byte, dimension, or metadata
validation. This keeps the common one-request path unchanged and bounds the fallback path to two
official API requests; an unbounded synonym search or attribution-policy expansion would add
non-reproducible selection and licensing obligations.

Only the current simplified-reference V3 generation path canonicalizes the generated background to
8-bit grayscale RGB before computing the generation receipt and before deterministic SVG overlay.
The operation cannot add, remove, or move morphology. Predecessor V1/V2 provider paths remain byte
stable. Labels and exact science geometry remain deterministic overlay responsibilities.

## Access patterns and complexity

Candidate ranking sorts at most five validated metadata records: `O(C log C)` time and `O(C)` space,
with `C <= 5`. Grayscale canonicalization is one bounded 800 by 500 pixel pass: `O(W*H)` time and
`O(W*H)` transient memory. No database, index, cache, queue, network endpoint, or dependency is
added; Pillow is already a pinned image-provider dependency.

## Transaction, retry, and failure behavior

Discovery/acquisition retains its existing immutable command and bounded retry identities. Ranking
is deterministic for the exact response. The provider writes the canonicalized bytes only at the
existing local generation-output boundary, hashes those exact bytes in the existing receipt, and
lets the Orchestrator/Catalog publish the validated artifact as before. Invalid PNG input fails with
the existing stable provider error and is never committed. A replay with a completed, validated
workspace remains idempotent.

## Dependency direction and alternatives

Selection stays in the Wikimedia infrastructure adapter. Pixel normalization stays in the isolated
image-provider adapter. Contracts and domain models do not import HTTP, filesystem, or Pillow code.

Prompt-only color suppression was insufficient in the live canary. Rejecting every colored model
result would consume repeated GPU attempts for a presentation defect that deterministic grayscale
conversion can safely correct. Downloading arbitrary internet images outside the typed Commons
boundary, or adding a new vision service, would expand trust and operational surface without solving
the bounded issue. Actual final-PNG inspection by the review workflow remains a separate protocol
successor; this guard does not claim to replace it.
