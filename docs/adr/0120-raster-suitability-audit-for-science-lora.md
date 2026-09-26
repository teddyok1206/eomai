# ADR 0120: Raster-suitability audit before science LoRA selection

- Status: Accepted
- Date: 2026-09-26 UTC
- Scope: internal SSD-1B science-assessment LoRA data only

## Context

The first science visual micro-probe used a reviewed crop set whose `LORA_ELIGIBLE`
classification was intentionally broad. Its fixed holdout exposed two failure modes:

1. a caption may describe a different semantic object than the pinned crop; and
2. an apparently raster-like crop can still contain panel composition, answer-relevant
   geometry, labels, masks, or a deterministic assessment illustration.

Training on those members teaches the model to emit panels, text-like marks, or an
incorrect object rather than a reusable non-authoritative science texture. It also
blurs the boundary in which Python/SVG owns scientific geometry.

## Decision

Before any successor science LoRA crop-set is selected, EOM records one immutable
`local-image-science-raster-suitability-review/1.0` against the exact pattern-inventory
revision. The review covers **every** member previously marked `LORA_ELIGIBLE`; it is
not a sample or a mutable annotation.

Each entry makes one of three mutually exclusive decisions:

- `GPU_RASTER_ELIGIBLE`: a single, non-authoritative naturalistic raster subject with a
  visually verified caption;
- `PYTHON_SVG_REQUIRED`: the visual is a deterministic diagram or scientific structure
  whose geometry, labels, count, or relation must be authored in code; or
- `EXCLUDED`: the crop is unsuitable for either current LoRA learning or direct reuse,
  such as a panel montage, redacted crop, text/number contamination, inadequate content,
  or caption mismatch.

Only a `GPU_RASTER_ELIGIBLE` entry may carry an exact training caption and its SHA-256.
The successor crop-set publisher must require this review and must select only entries
whose decision is GPU-eligible and whose semantic alignment is `VERIFIED`.

The prior inventory and crop-set contracts remain immutable history. The existing
evaluation-only adapter remains forbidden from activation. This ADR does not lower the
minimum of 12 TRAIN, 1 VALIDATION, and 2 HOLDOUT members, and does not pad, duplicate,
or augment samples to meet it.

## Ownership and data flow

```text
pinned visual-pattern inventory
  -> complete raster-suitability review
  -> successor raster-reviewed crop-set selection (V1.1)
  -> offline local trainer / fixed holdout evaluation
```

The review stores only typed candidate IDs, decisions, short reason codes, captions and
hashes. It stores no PNG/PDF bytes. The existing inventory pins the candidate result
member and its source chain; a consumer must validate the inventory pointer schema,
file hash, semantic hash, candidate coverage, and review self-hash before selection.

The dominant operation is candidate-ID membership and exact lookup. Validators build a
map/set once and run in `O(n)` time and space for at most 512 reviewed candidates.
There is no database table, index, queue, or worker-to-worker channel. A future
Orchestrator-owned publisher may commit the review; workers continue to see only staged
local input and return local results.

`local-image-science-visual-crop-set/1.1` is the selector contract. It pins both the
pattern-inventory and raster-suitability-review artifact/file and semantic hashes. Its
validator resolves selected members through indexed candidate/review maps and requires
`GPU_RASTER_ELIGIBLE`, `VERIFIED`, and the exact reviewed caption. The existing V1 crop
set remains historical micro-probe evidence; it is not silently upgraded or reused as a
V1.1 input.

## Failure and rollout

Missing candidate coverage, duplicate IDs, an unpinned inventory, a mismatched inventory
semantic hash, an incorrect self-hash, a GPU decision without a verified caption, or a
non-GPU entry carrying a caption fails closed. A review does not activate an adapter or
cause training. If fewer than 15 group-deduplicated GPU-eligible members survive, the
proper result is `INSUFFICIENT_RASTER_DATA`, not a smaller or padded training run.

The simpler alternative—continuing to treat `LORA_ELIGIBLE` as sufficient—cannot record
caption-to-crop verification or distinguish a panel/diagram from a reusable raster
subject, which is exactly the observed micro-probe failure.
