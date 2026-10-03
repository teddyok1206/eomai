# Isolated SDXL lineart candidate stack

Status: Accepted for implementation, 2026-10-03 UTC.

## Boundary and canonical source

Extend the existing isolated image provider/trainer for evaluation; do not add a service or change
the SSD-1B operating binding. A frozen stack manifest pins the three required upstream components:
SDXL base, TencentARC lineart T2I-Adapter and the fp16-fixed VAE. Canonical downloaded dependencies
are immutable protected model directories, not DB blobs or generated image Artifacts.
The manifest itself remains small metadata. Model acquisition is an explicit operator boundary;
the worker is offline and must not fetch code or weights at inference time.

## Identity and pointers

Stack logical ID, immutable revision ID and manifest hash remain distinct. Each component has its
own logical/revision IDs, upstream 40-character revision and sorted file size/SHA-256 records.
Component IDs bind role/repository; revision IDs bind upstream metadata and files. The stack hash
also binds UTC creation metadata. Do not identify a model by its directory path or substitute the
SSD-1B model for the SDXL base. Resolve exact file membership, safe paths, file identity, sizes,
hashes and manifest/schema before loading. Numerical architecture checks remain the backend's
responsibility; a metadata hash alone cannot prove tensor compatibility.

Generated PNGs and long receipts are committed only by the Orchestrator. A later experiment
command pins reference/conditioning, prompt provenance, stack and optional SDXL LoRA separately.
LoRA must bind the SDXL base revision; the old SSD-1B adapter cannot be renamed as compatible.

## Access patterns and concurrency

Lookup by component role uses a three-entry map. File uniqueness and membership use a set/map;
stable iteration uses a tuple sorted by relative path. Each component has at most 64 files, at
most 8 GiB per file. Validation is O(f) apart from checking sorted order, with O(f) space. No DB
table, cache or queue is needed. The operator publishes once, workers read staged/protected
inputs, and the existing GPU lease bounds concurrent execution. New manifests never rewrite an
old revision. A retry pins the same manifest and request rather than resolving latest upstream.

## Preprocessing and license boundary

The first diagnostic may use approved black-on-white lineart PNGs with an explicit deterministic
polarity conversion. This measures conditioning/style, not general photograph conversion quality.
Later photo conversion must pin the detector/receipt independently. The TencentARC card describes
white linework on black conditioning; the pinned `controlnet_aux` v0.0.7 implementation inverts
the detector output. Actual polarity and tensor range must be checked with fixtures before GPU
execution, not inferred from the final white-background publication PNG.

The public Annotators hub labels its aggregate license `other` and has an empty card. The
ControlNet lineart source attributes its implementation to MIT-licensed Informative Drawings,
while `controlnet_aux` code is Apache-2.0. Code license is not automatically a weight license.
Do not install unverified detector weights or pickle-load a `.pth` on that assumption. First
complete the weight provenance/license review; any authorized load must use `weights_only=True`
and a pinned hash. This does not block a preprocessed-lineart diagnostic using approved PNGs.

## Failure, ownership and simpler alternative

All stack manifests are `EVALUATION_ONLY`, with activation `FORBIDDEN`. Missing components,
duplicate/unsafe paths, unsupported upstreams, conflicting hashes and non-UTC timestamps fail
closed before inference. Publication and staging use existing Orchestrator adapters; contracts
import no filesystem/process/DB adapter. Extending the old SSD-1B manifest is simpler but would
reinterpret a released architecture contract and allow incompatible adapters. A generic model
plugin system is unnecessary for this one fixed three-component candidate.

Primary references:

- [SDXL base](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0)
- [TencentARC adapter](https://huggingface.co/TencentARC/t2i-adapter-lineart-sdxl-1.0)
- [fp16-fixed VAE](https://huggingface.co/madebyollin/sdxl-vae-fp16-fix)
- [Pinned lineart implementation](https://github.com/huggingface/controlnet_aux/blob/v0.0.7/src/controlnet_aux/lineart/__init__.py)
- [Original lineart attribution](https://github.com/lllyasviel/ControlNet-v1-1-nightly/blob/main/annotator/lineart/__init__.py)
