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
successor therefore creates one deterministic, light-tone morphology-conditioning PNG before model
inference, reduces the same reviewed style adapter's inference scale, and uses a derived prompt
policy that requests only essential large contours and sparse flat tone. The two team-lead source
documents and the KICE illustration guide remain byte-stable.

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

The additive provider-binding/request/receipt V3 family was not activated before bounded
evaluation. Its final pre-activation contract pins:

- an additive style-adapter release V2 that references the same immutable adapter files and base
  model while fixing inference scale to `0.45`;
- the exact approved visual-reference pointer;
- `local-image-reference-simplification/1.1` parameters;
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

The v1.1 simplifier performs only reviewed local operations. A light fill branch uses grayscale,
5x5 median noise suppression, 1.2-pixel Gaussian smoothing, bounded autocontrast, and four light
tones. A contour branch uses a 5x5 maximum filter, 7x7 median filter, 2.0-pixel Gaussian smoothing,
edge detection, bounded autocontrast, and four contour tones. Their pixel-wise minimum preserves
large boundaries while keeping broad interiors light; a fixed five-pixel outer margin is forced to
white. Across the combined output there are at most six grayscale values. It does not segment a
foreground, synthesize missing pixels, crop, rotate, mirror, rescale, or call a model. It therefore
reduces texture without changing canvas dimensions or delegating answer-bearing structure.

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

## Bounded preprocessing evidence

On 2026-09-28 UTC, the first draft simplifier processed three previously reviewed 800x504 reference
candidates without GPU inference. The isolated beetle passed, while the automobile photograph was
rejected as `REFERENCE_SIMPLIFICATION_FOREGROUND_INVALID` and the rock photograph containing an
answer-bearing scale and dark border was rejected as
`REFERENCE_SIMPLIFICATION_BACKGROUND_COMPLEX`. This confirmed the fail-closed source boundary, but
the first GPU output was too dark and flat. An edge-only conditioning probe at style scale `0.8`
also remained too detailed and hatched, showing that prompt wording alone could not correct the
conditioning and adapter strength.

The reviewed light-tone contour probe used the exact v1.1 algorithm and style scale `0.45`. For the
same beetle input, it produced a 34,273-byte conditioning PNG with SHA-256
`7174f62b148471fea7e2303879b032f04445e4512a2e1e97ee2b914cfda1a530`, foreground ratio
`0.24122768`, border foreground ratio `0.00180799`, and edge-density ratio `0.91233403`. The GPU
candidate preserved the accepted bounding geometry (IoU `0.8188`, center shift `0.0129`, width
ratio `0.8425`, height ratio `0.9719`) while materially reducing dark fill and hatching. The legacy
composition evaluator rejected only edge recall, which is texture-sensitive and conflicts with the
explicit goal of deleting reference microtexture; its geometry thresholds passed. The legacy
threshold is not weakened or reinterpreted by this decision.

The final V3 family remains evaluation-only. Activation requires a morphology-aware evaluation
contract and representative subject review; this bounded canary is evidence for the contract
choice, not production approval.

The first bounded GPU canary stopped before CUDA transfer because the draft V2 negative prompt used
116 CLIP tokens and exceeded the pinned SSD-1B encoders' 77-token limit. No image was produced. The
successor prompt policy `local-gpu-image-prompt-policy/1.8.1` compresses equivalent prohibitions into
18 phrases and keeps the assembled negative prompt at no more than 340 characters. The provider's
existing exact-tokenizer guard remains authoritative and fail-closed; the character bound is only a
source-level regression guard, not a replacement tokenizer.
