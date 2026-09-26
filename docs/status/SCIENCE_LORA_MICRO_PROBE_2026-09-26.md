# Science image LoRA micro-probe status — 2026-09-26 UTC

> Historical first probe. The expanded successor campaign is recorded in
> [Expanded science-image LoRA campaign](SCIENCE_LORA_EXPANDED_CAMPAIGN_2026-09-26.md). This file's
> original evidence and activation decision remain unchanged.

## Outcome

`TECHNICAL_PASS / DO_NOT_ACTIVATE / DO_NOT_SCALE_CURRENT_DATASET`

The approved 15-group crop set supported one bounded evaluation-only probe: 12 TRAIN, one
VALIDATION, and two HOLDOUT groups. Training and the fixed base-versus-adapter comparison completed,
but the holdout evidence does not justify production activation or immediately expanding the same
captioning route to 100 samples.

The adapter remains `EVALUATION_ONLY` with `activation_policy=FORBIDDEN`. No provider binding,
production activation, external API, or model replacement occurred.

## Immutable training evidence

- crop-set Artifact Revision: `rev_bb321224e1aa4bf88641ea191d6185cd`;
- crop-set semantic SHA-256:
  `sha256:468c9b968f2ad927cc7d68f3a0a329d26087dab380d0af5fb93c0a4a28b756d4`;
- plan Artifact Revision: `rev_70d762553e0f4f938ac62bcc77ffb674`;
- plan semantic SHA-256:
  `sha256:3d3d3184dafc5919d95c0b8263fc59df487fe431688eade433587813e4a14d5e`;
- training run: `imgscimicrotrainrun_06f6c97bc2e5a8f619e00c44623c4bf8`;
- training result semantic SHA-256:
  `sha256:f94a4a79f2fd7b23fac3f4ce97d5655d6c1fe3bca38d17bfcb9ccf82e6b76bb7`;
- realized samples / optimizer steps: 12 / 200;
- final loss: `0.015135172754526138`;
- adapter manifest SHA-256:
  `sha256:548fc0b7bef04106cafb3b34372c4a9b83129cd6377025c565512f58b3d9e3d5`.

Loss is recorded as a training diagnostic, not as an image-quality acceptance metric.

## Fixed holdout comparison evidence

- evaluation run: `imgscimicroevalrun_1bcd94559cfc6ae7cdd4c734a61d74e1`;
- evaluation result semantic SHA-256:
  `sha256:1506841a9e3c084877ee191664eb33173a2f46943e52c7a4460f453965856536`;
- result Artifact: `artifact_449b032a2635404f912a8b1bfeca78e5`;
- result Artifact Revision: `rev_a5f26c7d8d94440b81943847383f24b3`;
- file-set manifest SHA-256:
  `sha256:facd81df377646d73c38baeafa0e41480a7719b35e820e14da1cbb05af9e55bc`;
- output coverage: exactly two HOLDOUT cases × BASE/ADAPTER = four 800×500 PNGs.

Both variants use the same case prompt, negative prompt, seed, local base-model revision, scheduler,
dimensions, 20 inference steps, and guidance. The comparison therefore demonstrates real adapter
movement, but not production suitability.

## Preliminary visual finding

The first holdout is a compact leaf diagram with deterministic brackets and marks. Its caption only
describes a grayscale botanical leaf illustration. The adapter moves the base output toward isolated
grayscale leaf specimens, but neither variant recovers the required bracket, mark, or authored
layout. Diffusion alone is not an acceptable renderer for those authoritative elements.

The second holdout is a sequence of numbered gray geometric panels. Its stored caption describes a
smooth planetary surface. The base produces terrain and the adapter produces an isolated planet;
both follow the caption but not the source crop. This is a caption-to-crop semantic binding failure,
not evidence that another 85 similarly prepared samples would solve the product problem.

## Decision and next boundary

Do not activate this adapter and do not scale the same dataset construction route. Before another
training run:

1. validate every crop/caption pair and reject semantic mismatch;
2. classify naturalistic raster material separately from deterministic assessment diagrams;
3. route labels, brackets, axes, arrows, geometry, panel order, and `(가)/(나)` layout to the
   existing Python/SVG/HWPX deterministic path;
4. use a local raster model only for non-authoritative textures or naturalistic subjects where
   diffusion is appropriate;
5. derive a typed visual brief from the two content-team sources and preserve it through raster,
   vector overlay, and HWPX assembly;
6. repeat a small fixed holdout comparison before authorizing any larger dataset or production
   activation.

This preserves the useful result: a small LoRA can materially alter SSD-1B style. It also records
the limiting result: current captions and renderer routing are not yet sufficiently faithful for
science-assessment diagrams.
