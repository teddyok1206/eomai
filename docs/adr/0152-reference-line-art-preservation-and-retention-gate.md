# ADR 0152: Reference line-art preservation and morphology-retention gate

Status: Accepted for implementation

Date: 2026-09-29 UTC

## Context and responsibility

The local image provider owns deterministic preparation of a reviewed visual reference before GPU
inference and deterministic validation of the generated raster afterward. A real item workflow
selected a clean public-domain ammonite line drawing, but the `local-image-reference-simplification/1.1`
photo-oriented denoise path erased most continuous black contours. The GPU followed that damaged
conditioning input and produced a fragmented result. Density-only output checks accepted it, and the
review role did not identify the visual defect.

The immutable source is the pinned normalized visual-reference artifact revision. The conditioning
image and generated raster are workspace materializations; committed results remain immutable artifact
revisions with separate logical IDs, revision IDs, and SHA-256 hashes.

## Decision

Add successor contracts rather than changing the released V5 bytes:

- `local-image-reference-simplification/1.2` deterministically classifies a normalized reference as
  clean monochrome line art or photographic material using pinned color-spread, white-background, and
  dark-foreground thresholds.
- Clean line art uses a source-preserving six-level tone map. Photographic material continues to use
  the existing detail-reduction algorithm.
- The V6 receipt records the selected simplification mode and the deterministic classification
  metrics.
- `local-image-provider-binding/6.0` and reference-conditioned request/receipt `6.0` pin the successor
  policy.
- V6 fails closed when the postprocessed foreground retains too little of the conditioning foreground.
  This is a coarse deterministic morphology-loss gate, not a semantic classifier.

V1-V5 schema bytes, receipts, artifacts, and replay behavior remain unchanged.

## Data structures and access patterns

The hot operations are one bounded image scan, keyed contract dispatch, and immutable pointer
resolution. Fixed-size 800x504 rasters are scanned in O(width × height) time and O(width × height)
temporary image memory. Contract dispatch uses typed discriminated models and maps rather than list
searches. No database schema, index, queue, or binary persistence change is required.

## Transactions, concurrency, retry, and dependency direction

The existing request hash includes the exact V6 binding and policy. Idempotent replay therefore cannot
confuse V5 and V6 output. Workers still read staged inputs and write only local results; the
orchestrator remains the sole NAS commit owner. A failed preservation or retention gate produces no
canonical image artifact. Retrying an identical V6 request is deterministic at the contract and seed
boundary.

Contracts remain below provider and Catalog adapters. The image provider implements transformation;
Catalog only builds and validates typed requests and receipts. No worker-to-worker communication is
introduced.

## Simpler alternative rejected

Changing the V1.1 algorithm in place would make the same released request identity produce different
conditioning bytes after a deployment. Lowering the existing density threshold would accept the same
fragmented output. Always bypassing simplification would preserve line art but reintroduce photographic
background texture. The successor adaptive contract is the smallest change that preserves history and
handles both real source classes.

