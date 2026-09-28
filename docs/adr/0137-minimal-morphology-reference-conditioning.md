# ADR 0137: Simplify morphology references before local line-art generation

## Status

Accepted for an additive evaluation-only successor on 2026-09-28 UTC. This decision does not
activate a style adapter, change released provider bindings, or authorize generative raster output
for labels, axes, arrows, measured geometry, tables, graphs, circuits, or exact apparatus.

## Responsibility and boundary

The local GPU path owns only non-authoritative subject morphology. Python/SVG/HWPX continues to own
all answer-bearing structure and editable text. When a reviewed visual reference is available, the
reference owns subject count, silhouette, pose, viewpoint, relative placement, overlap, scale, and
framing. The model may change only the assessment-page rendering style.

The predecessor passed the normalized reference PNG directly to SDXL img2img and always requested
light-gray hatching. Human review showed that this preserves or invents too much texture. The
successor therefore creates one deterministic, low-detail morphology-conditioning PNG before model
inference and uses a derived prompt policy that requests only essential large contours and sparse
flat tone. The two team-lead source documents and the KICE illustration guide remain byte-stable.

## Canonical source and revision model

```text
approved visual-reference bundle revision
  -> immutable normalized reference PNG
  -> deterministic morphology-conditioning PNG + metrics
  -> reference/style-conditioned raster candidate
  -> deterministic SVG overlay
  -> final generated-stimulus Artifact Revision
```

The normalized source and conditioning member have separate paths and SHA-256 hashes. The source is
never overwritten. The conditioning member is committed with the generated stimulus so the receipt
never points only to a temporary workspace copy. A workspace is materialization, not identity.

## Routing rule

The generative path is limited to morphology or non-authoritative natural texture. Exact laboratory
assemblies, scales, containers whose fill level is answer-bearing, arrows, labels, particle counts,
plots, maps, circuits, and measured relationships remain deterministic. A beaker silhouette may be
a morphology reference only when every scientifically authoritative mark and relationship is added
by the overlay; an apparatus assembly is never delegated to diffusion.

The existing released workflow route vocabulary is not broadened in this change. A future worker
contract may add a reviewed `OBJECT_MORPHOLOGY_REQUIRED` reason, but the provider successor must not
infer that meaning from free text or silently reinterpret an older route.

## Contract and pointer design

The additive provider-binding/request/receipt V3 family pins:

- the exact V2 style-adapter release and base model;
- the exact approved visual-reference pointer;
- `local-image-reference-simplification/1.0` parameters;
- the exact conditioning member path, media type, dimensions, size, and SHA-256;
- bounded foreground, border, and edge-density metrics;
- the exact composite request and receipt; and
- UTC completion time and receipt self-hash.

JSON Schema 2020-12 defines the wire shape before Pydantic and provider behavior. Old V1/V2 schema
bytes are immutable. Pointer resolution still validates existence, pinned revision, schema, media
type, lifecycle, size, and SHA-256 before materialization.

## Access patterns and data structures

The dominant operation is one sequential pass over an 800x504 image. Pixel storage is a fixed-size
array owned by Pillow; histogram and edge counts are fixed-size reductions. Runtime and memory are
`O(W*H)`. No database table, index, cache, queue, or large JSON payload is added. Artifact assembly
uses the existing keyed typed manifest; duplicate paths remain rejected by that boundary.

## Deterministic preprocessing

The v1 simplifier performs only reviewed local operations: grayscale conversion, 5x5 median noise
suppression, a 1.2 pixel Gaussian smoothing pass, bounded autocontrast, and four-level tone
quantization. It does not segment a foreground, synthesize missing pixels, crop, rotate, mirror,
rescale, or call a model. It therefore reduces small texture without changing canvas geometry.

The simplifier measures source/conditioning foreground ratios, dark border ratio, source/output edge
density, and their ratio. A nearly empty image, a nearly full image, or a dark/cluttered border fails
before GPU inference. It does not pretend that an uncertain background can be removed safely.

## Transaction, concurrency, retry, and idempotency

The Catalog application stages the exact source pointer and request. The isolated image provider
creates the conditioning member, validates it, performs the already pinned model invocation under
the existing GPU lease, and writes one self-hashed receipt. Catalog validates every output and alone
commits the file set to NAS. Workers still cannot access NAS or communicate with the provider.

Request identity includes provider binding, prompt-policy revision, source pointer/hash, style
adapter, and simplification policy. Byte-identical replay reuses exact outputs. Any pre-existing
partial output, conflicting hash, stale pointer, or changed policy fails closed instead of being
overwritten. Rollback is selection of the predecessor binding/release; historical artifacts remain.

## Failure behavior

Unsafe paths, symlinks, wrong modes, oversized bytes, invalid PNG structure, source/hash drift,
complex borders, empty/full foreground, output drift, or receipt mismatch fail before commit. There
is no automatic fallback to text-only generation, a higher diffusion strength, an alternate
reference, background removal, or implicit latest adapter.

## Dependency direction and dependencies

Wire contracts and frozen models live in `eom_image_contracts`. The pure simplifier lives in the
image-provider infrastructure package and uses the already pinned Pillow dependency. Catalog owns
staging and validated Artifact assembly; it does not implement pixel rules. Domain/workflow models
do not import provider or filesystem code. No dependency is added.

## Simpler alternatives rejected

Prompt-only changes cannot prove which source pixels reached img2img and cannot remove input
microtexture. Passing an aggressively thresholded edge map loses broad morphology and makes the
model invent volume. General background segmentation adds an unreviewed model and another failure
boundary. Mutating binding V2 would break replay. The additive V3 receipt plus a small deterministic
simplifier is the smallest auditable successor.
