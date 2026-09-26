# Science LoRA raster re-review — 2026-09-26 UTC

## Scope

This is a second visual pass over the 24 candidates marked `LORA_ELIGIBLE` by the
immutable `imgscivisinventory_45a1dbe6df227c904965b94a3aad4a26` inventory. It was
performed from its pinned internal contact sheets before any successor training run.
It does not modify that inventory, its crop set, the evaluation-only adapter, or an
active image-provider binding.

## Result

| Decision | Count | Meaning |
|---|---:|---|
| `GPU_RASTER_ELIGIBLE` | 7 | single, non-authoritative fossil, astronomy, weather, or geologic raster subject with a visually plausible caption |
| `PYTHON_SVG_REQUIRED` | 4 | authored structure or scientific illustration; geometry must remain deterministic |
| `EXCLUDED` | 13 | panel montage, mask/redaction, caption mismatch, text contamination, or too little reusable raster content |

The seven retained subjects are a trilobite fossil, a leaf fossil, two separate spiral
galaxy crops, one volcanic crater landscape, a tornado, and a cave-stalactite photograph.
They are deliberately not enough for the current minimum: 12 TRAIN + 1 VALIDATION +
2 HOLDOUT group-deduplicated members. Therefore:

```text
CURRENT_SUCCESSOR_LORA_TRAINING=BLOCKED_INSUFFICIENT_RASTER_DATA
CURRENT_ADAPTER_ACTIVATION=FORBIDDEN
```

This is a data-quality gate, not a model/runtime failure. The right next source is the
approved expanded internal assessment corpus, after the same review has found at least
15 distinct eligible source/exam groups. No duplicate, panel crop, augmentation, or
diagram is used to satisfy the minimum.

## Observed exclusions

- paired or triple photo panels must be split at a future canonical crop boundary before
  they could ever be reviewed as individual naturalistic source images;
- images containing a blanked/redacted rectangle, printed number, bracket, axis, label,
  answer-frame, or explanatory text are not LoRA style training data;
- leaf, cloud, sand-mound, cell/mitochondrion, and mountain illustrations are retained
  as evidence for Python/SVG or excluded, not treated as pixel authorities; and
- the prior “smooth planetary surface” caption did not match its pinned crop, confirming
  that caption-to-crop verification must be a typed gate rather than a review convention.

## Implemented successor guard

ADR 0120 and `local-image-science-raster-suitability-review/1.0` introduce a complete,
immutable second-pass review. It pins the exact V1.1 pattern-inventory artifact/file and
semantic hashes, covers every broad LoRA candidate exactly once, records the route and
reason, and permits a caption only for `GPU_RASTER_ELIGIBLE` plus `VERIFIED` semantic
alignment. The future crop-set publisher must consume this review; the legacy V1 crop
set remains historical evidence and is not reinterpreted.
