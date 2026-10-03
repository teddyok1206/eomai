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

Compiled prompt provenance is a small immutable control Artifact: it pins both original team-lead
documents, illustration guidance, the existing Catalog policy revision and the exact case prompts.
The worker schema-checks it and compares all cases with the command before model loading. It does
not compile prompts from repository files at runtime. Original corpus permission currently names
SSD-1B and remains unchanged. An explicit operator approval value for internal SDXL comparison
(and optionally SDXL LoRA training) is required in the new provenance; it does not authorize source
export or automatic activation. A sudo authentication acknowledgement is not that data-use approval.

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

## Bounded reference diagnostic

The first command/result family is a base-only, evaluation-only lineart diagnostic, not a substitute
for the later SDXL LoRA and photograph arms. Commands pin the stack and compiled-prompt provenance,
one to six exact PNG members and one or two unique seeds per depiction (at most twelve model
calls). Case/command hashes bind all inputs and settings; stage member names are derived from case
IDs, never arbitrary filesystem paths. Permission, lifecycle and provenance resolution happens
in the Orchestrator before staging. Workers verify staged hashes and image dimensions.

Generation uses a fixed 832x512 canvas (compatible with adapter/UNet downsampling), a centered
800x500 publication crop and explicit fit/grayscale/inversion of reviewed lineart. The conditioning
PNG is retained independently so polarity and source geometry can be inspected. Each model call
retains raw RGB and grayscale publication PNGs; conversion removes color only and does not claim
to remove pseudotext, correct science or improve stroke quality. No source pixels are pasted back
into a generated image. Human/semantic review and the later morphology gates remain required.

The application owns bounded metadata input/output and replay; the backend owns Diffusers/CUDA.
Role-keyed lookup verifies each model file once per command, using streaming hashes rather than
materializing gigabyte weights. Runtime/case duration and peak VRAM are measured and checked against
the frozen budget. The existing GPU lease is acquired by the CLI; the isolated process has an outer
timeout because a post-call duration check alone cannot interrupt a hung CUDA call.
The evaluation template has a 1,830-second hard timeout, including a 30-second cleanup margin.
The command schema and frozen model cap the diagnostic budget at 1,800 seconds; a larger budget
cannot bypass the installed runtime ceiling. A killed process has no successful terminal receipt.
Result/member paths are unique and ordered by (case ID, seed). A terminal result replays only after
its command hash and all recorded file hashes resolve. Failed or partial runs remain failed; an
existing unreceipted output is not silently treated as success or overwritten. New experiment
identities represent intentional successor experiments, never timeout-driven duplicate submission.

## Orchestrator input admission

The existing control-Artifact resolver is the only NAS/DB input adapter. A bounded application
use case resolves compiled provenance, the approved crop set, its original authorization,
inventory/review and pinned campaign plan/results. It reuses the existing pure crop/source
validators rather than copying their rules. A missing, unapproved, stale, wrong-schema or
hash-drifted pointer fails before any worker input is materialized. The new experiment approval
must precede the command; the old SSD-1B permission is never rewritten.

The dominant operations are keyed pointer/member lookup, uniqueness and stable ordered assembly.
A per-call map resolves each immutable metadata pointer once; a member map and sets select at
most six distinct TRAIN crops. Full metadata scale is bounded by the existing 96-crop / four-shard
contracts. Validation is linear in reviewed source metadata, with bounded maps; PNG bytes are
materialized only at this explicit staging boundary, not in DB or cross-service arbitrary blobs.
The result is a frozen tuple of at most eight local input members (command, provenance, PNGs).
Worker-side decode/dimension validation still runs before CUDA and is not a claim of style quality.

Admission is read-only and has no queue, claim, retry or activation side effects. Control metadata
publication reuses the current Orchestrator publisher and its idempotency/commit owner. A failed
admission cannot create a replacement execution or silently resolve a latest revision. The simpler
alternative of trusting only the staged image SHA is insufficient: it would lose partition,
approved-source and policy lineage even though the PNG bytes happen to match.

Primary references:

- [SDXL base](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0)
- [TencentARC adapter](https://huggingface.co/TencentARC/t2i-adapter-lineart-sdxl-1.0)
- [fp16-fixed VAE](https://huggingface.co/madebyollin/sdxl-vae-fp16-fix)
- [Pinned lineart implementation](https://github.com/huggingface/controlnet_aux/blob/v0.0.7/src/controlnet_aux/lineart/__init__.py)
- [Original lineart attribution](https://github.com/lllyasviel/ControlNet-v1-1-nightly/blob/main/annotator/lineart/__init__.py)
