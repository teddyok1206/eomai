# ADR 0191: One bounded spatial-conditioning alternative after failed native and cleanup probes

Date: 2026-10-04 UTC

Status: proposed; NOT_IMPLEMENTED, no ControlNet weight acquired or GPU run submitted.

## Evidence and hypothesis

The three same-source T2I strengths, single negative-clause ablation and fixed CPU
cleanup are closed. Native 72/72 and derived 6/6 remain own-REJECTED. Whitening
is not sufficient: scientific contours, roots and wheel-light marks must survive.
The approved plan's step 6 already allows a bounded ControlNet/IP-Adapter fallback.
Evaluate one spatial controller first, not a combined multi-model/parameter sweep.

Candidate: `diffusers/controlnet-canny-sdxl-1.0` with the existing full SDXL base,
fp16 VAE and the same reviewed LoRA. The [official model card](https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0)
declares SDXL Canny conditioning and OpenRAIL++ weights. The
[upstream file list](https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0/tree/main)
offers an fp16 safetensors file; do not fetch the whole repository or either pickle
variant. Exact revision, file size/SHA, configuration and applicable license-text
pins are still PENDING, not inferred from the label. Diffusers code licensing is
separate from weight licensing.

The [pinned Diffusers 0.35.2 implementation](https://github.com/huggingface/diffusers/blob/v0.35.2/src/diffusers/pipelines/controlnet/pipeline_controlnet_sd_xl.py)
provides the SDXL ControlNet pipeline, LoRA loader and explicit spatial-control
parameters. This establishes an implementation path, not better exam quality.
Choosing it before IP-Adapter is our hypothesis: test direct edge preservation
without adding another encoder/conditioning factor. No claim of improvement or
16GB fit is made before actual measurement.

## Required design boundary

1. Responsibility: extend the existing isolated provider's evaluation backend;
   Orchestrator remains the sole source resolver, scheduler/lease owner and
   validated Artifact publisher. No new framework, queue or operating endpoint.
2. Canonical source: the same three admitted TRAIN targets/captions, frozen
   source history, SDXL base/VAE and LoRA revisions. ControlNet is a separate
   immutable model pointer; a Canny image is a recorded derivative, not a new
   source photograph. No VALIDATION/HOLDOUT pixels in this diagnostic.
3. Identity: new model/command/result revisions, per-case conditioning hashes and
   raw/native/optional publication-output hashes. Existing T2I/cleanup history
   stays immutable and is the comparison baseline, not renamed ControlNet output.
4. Resolution: validate source authorization/split/review/schema/media/lifecycle/
   SHA before pixels or weights. Pin the controller configuration, code/version,
   license/provenance and safetensors members. Offline runtime; no implicit
   `main`, pickle/code loading, network download or latest fallback.
5. Access patterns: bounded indexed metadata batches, keyed target/model lookup,
   ordered case/seed/arm iteration and terminal replay. Reuse current admission
   and numerical pair execution where their types/semantics genuinely match.
6. Structures: frozen typed model/command/result manifests, maps/sets for coverage
   and exact members; existing GPU inode lock and exclusive private workspace.
   No DB schema/index/cache change. Do not hide ControlNet under a T2I field name.
7. Complexity/scale: first diagnostic at most three cases and BASE/LORA arms,
   six new GPU images. Source/conditioning preparation is O(total pixels); one
   batch-one numerical session per arm with explicit cleanup. Preserve the
   fallback's existing overall ceiling of 12; the unsubmitted remainder is not
   an automatic license to tune after seeing results.
8. Transaction/concurrency: one frozen six-output command and one exclusive GPU
   lease; existing Orchestrator Artifact commit/idempotency. Check quiescence and
   rollback wheels before any lab install. No production install/restart/activation.
9. Dependency direction: pure contracts first; provider owns OpenCV/Diffusers/file
   adapters and Orchestrator owns application admission/publication. Existing
   Diffusers 0.35.2, Torch 2.7.1+cu128, PEFT 0.17.1 and Pillow 11.3.0 are retained.
   OpenCV is currently absent. If Canny requires it, pin a lab-only optional
   headless package and record license/hash/reason before install. Do not add it
   to API/core or upgrade numerical dependencies implicitly. Do not substitute
   an unverified Pillow edge filter and still call it Canny.
10. Failure/retry: schema/hash/media/runtime/resource/conditioning errors fail
    closed; preserve a bounded failed prefix and exact error. Query/replay a
    possibly dispatched identity; no new seed/key, automatic retry, looser
    threshold, CPU-offload fallback or reinterpretation as a success. Old
    successful numerical execution does not make rejected quality acceptable.
11. Simpler alternative: another T2I strength/prompt/cleanup sweep is already
    closed by recorded failures. A directly recorded spatial controller tests a
    different hypothesis while reusing base/VAE/LoRA, inputs and orchestration.
    Adding IP-Adapter, a new base or retraining at the same time would confound it.

## Ordered pre-execution gates

1. Define successor model/acquisition/comparison JSON Schema 2020-12 and frozen
   Pydantic models before backend behavior. Preserve every released schema byte.
2. Freeze Canny implementation/version/parameters and source placement. Inspect
   all three conditioning images before model acquisition: leaf veins/roots,
   fan hub/grille and wheel-light marks must be present. Failure stops here;
   do not consume GPU to compensate for missing input edges.
3. Complete exact model revision/configuration/safetensors/license/resource pins
   and optional dependency decision. Use supported bounded acquisition/install
   with no base/VAE/LoRA/dataset duplication. No remote inference/credits.
4. Validate the real backend arguments/shape/polarity, stale/hash/permission
   negatives, ordered partial failure, secure staging/claim/lease and transform-
   or model-free replay. Verify wheel RECORD and actual installed worker imports.
5. Before the one GPU dispatch, freeze source/prompt/seed/scheduler/steps/guidance/
   LoRA/controller strength/guidance range and resource ceilings. Same-case
   previous T2I outputs are reused; no fresh baseline generation. Measure actual
   peak VRAM/latency; no claim of fitting the 16GB device from parameter count.
6. Commit validated results, inspect all native candidates against source and
   previous output, and judge white canvas, clean strokes, exact parts and pose
   together. Publication cleanup cannot silently repair or excuse scientific
   details. Independent blind/heldout and Item Preview/HWPX activation remain
   distinct later gates and are not opened for an own-rejected candidate.

Runtime/library research and this proposal consume no model execution budget.
The acquisition/model contract, exact controller pins and new numerical quota
remain pending. The completed CPU checkpoint is documented in
[ADR 0190](0190-pinned-sdxl-publication-derivatives.md) and the
[improvement plan](../operations/IMAGE_STYLE_IMPROVEMENT_PLAN_2026-10-03.md).
