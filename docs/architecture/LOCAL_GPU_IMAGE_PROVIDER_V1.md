# Local GPU image provider V1

Status: design draft for protocol-first implementation

Last reviewed: 2026-09-01 UTC

## Decision

EOM should add local image generation as a separate GPU provider behind the existing vector-first
stimulus pipeline. The first reviewed model target is `segmind/SSD-1B`; `black-forest-labs/FLUX.1-schnell`
is the higher-quality second target after the light baseline is stable. No hosted image API is part
of this provider class.

The provider must not replace deterministic scientific drawing. It may generate a non-authoritative
background layer or visual texture for an item stimulus. Exact labels, arrows, graphs, apparatus
geometry, scales, equations, and scientifically assessed relationships remain in the validated SVG
overlay and are composed deterministically by Catalog.

## Current hardware and runtime boundary

The current EOM server has one NVIDIA GeForce RTX 5080 with 16 GiB VRAM and compute capability
12.0. The existing `eom-image` Conda environment does not yet contain PyTorch, Diffusers,
Transformers, Accelerate, Safetensors, or Pillow.

Blackwell support should be treated as a runtime dependency boundary. PyTorch 2.7 introduced
Blackwell support and CUDA 12.8 wheels, so the first installation plan should use a CUDA 12.8
compatible PyTorch build rather than relying on the ambient driver alone.

## Model shortlist

| Rank | Model | Role | Reason | Risk |
| --- | --- | --- | --- | --- |
| 1 | `segmind/SSD-1B` | first local baseline | Apache-2.0 model card, Diffusers/Safetensors support, SDXL-derived 1B-class model, lighter for 16 GiB VRAM | lower ceiling than FLUX; final license/provenance review still required |
| 2 | `black-forest-labs/FLUX.1-schnell` | quality target | Apache-2.0 model card, strong prompt following, 1-4 step generation | 12B BF16 model, gated Hugging Face access, may need CPU offload or quantized/runtime-specific workflow |
| 3 | `stabilityai/stable-diffusion-xl-base-1.0` | mature fallback | broad ecosystem, Diffusers support, 3B params, known SDXL behavior | OpenRAIL++ license; text/compositional limitations matter for assessment images |
| 4 | `stabilityai/stable-diffusion-3.5-medium` | license-reviewed option | modern architecture and resource-efficiency claims | Stability Community License and gated access; not the default open-source baseline |

Operational recommendation:

1. Prove the provider boundary with `SSD-1B` first.
2. Add FLUX only after the model-store, hash verification, GPU lease, artifact provenance, and
   non-authoritative-background policy are already enforced.
3. Do not install several model families at once. One model revision should be accepted, hashed, and
   smoked before the next candidate is introduced.

## Responsibility and system boundary

- Workflow contracts describe that a local generative background is requested.
- Workers may request the route through typed data, but they do not call a model, access GPU state,
  read provider secrets, write NAS, or communicate with another worker.
- Catalog owns provider invocation through an infrastructure adapter after the worker output has
  passed schema and domain validation.
- The provider reads a reviewed local model revision from a protected model store and writes only to
  a private staging workspace.
- The orchestrator/Catalog commits validated output artifacts to NAS and records immutable pointers.
- HWPX consumes the approved PNG pointer exactly as it does for deterministic SVG output.

## Canonical source and revision model

```text
LocalImageModel
    -> LocalImageModelRevision
        - provider family
        - upstream model ID
        - local model-store path
        - file manifest
        - SHA-256 for every required file
        - license/provenance record
        - runtime contract version

Image role result
    -> typed request for LOCAL_GENERATIVE_BACKGROUND
    -> Catalog provider adapter
    -> background Artifact Revision
    -> deterministic SVG overlay composition
    -> final stimulus Artifact Revision
    -> approved Item Revision image pointer
```

The model path is not identity. Identity is the logical model ID, immutable model revision ID, exact
file hashes, provider contract version, and runtime manifest.

## Required pointers and resolution checks

Before loading a model revision, the provider adapter must verify:

- model logical ID and immutable revision ID exist;
- model revision state is `APPROVED`;
- expected provider family matches the adapter;
- local path is under the reviewed model-store root;
- no path component is a symlink;
- every required file is regular, within size limits, and has the pinned SHA-256;
- model license/provenance record is present;
- runtime contract version is compatible with the current provider code;
- the GPU lease belongs to the current provider job.

Before committing output, Catalog must verify:

- output file is regular, non-symlink, non-empty, and within bounded size;
- dimensions match the requested contract;
- content hash matches the provider receipt;
- provider receipt pins model revision, prompt hash, negative prompt hash, seed, sampler settings,
  output hash, runtime package versions, GPU name, and CUDA/PyTorch versions;
- deterministic SVG overlay is applied after the generated background and remains the source of
  scientific truth.

Dangling model pointers, stale revisions, hash mismatch, unavailable GPU, unsupported route, OOM,
or timeout must fail closed. There is no silent fallback from local generation to a different model
or hosted provider.

## Primary access patterns and data structures

- Model lookup: indexed by immutable model revision ID.
- Model file verification: keyed manifest map from relative path to SHA-256 and size.
- GPU scheduling: one FIFO lease per physical GPU. The provider must not share Slot 5 textbook
  analysis capacity.
- Idempotent generation: key by `(model_revision_id, prompt_hash, negative_prompt_hash, seed,
  sampler_contract, canvas_size, route_contract)`.
- Artifact output: keyed manifest of generated background, canonical SVG, and delivery PNG members.
- Prompt policy lookup: immutable route policy map by visual kind and provider family.

Expected scale is small: one local GPU, one active image-generation job, and a bounded number of
background candidates per item. The main risk is not database scale; it is reproducibility,
unbounded GPU usage, and confusing generated pixels with scientific content.

## Transaction and concurrency boundary

Provider invocation occurs outside the final artifact commit transaction. The transaction stores a
provider job record before execution, then records a terminal receipt or failure. Artifact commit
occurs only after output validation succeeds.

The GPU lease is acquired before model load and released after output validation or failure. A
process crash must leave a reclaimable lease with an expiry and a durable provider job state. The
lease limit is one until measured evidence proves that concurrent GPU jobs do not harm worker
stability or textbook-analysis throughput.

## Failure, retry, and idempotency

Each provider attempt has one explicit idempotency key. A lost HTTP or workflow response may replay
the same key and body to recover the same provider job. A new seed, changed prompt, changed model
revision, or changed sampler setting is a new attempt and needs explicit authorization by the
calling use case.

Failures should use stable codes:

- `LOCAL_IMAGE_MODEL_UNAVAILABLE`
- `LOCAL_IMAGE_MODEL_HASH_MISMATCH`
- `LOCAL_IMAGE_LICENSE_NOT_ACCEPTED`
- `LOCAL_IMAGE_GPU_UNAVAILABLE`
- `LOCAL_IMAGE_PROVIDER_TIMEOUT`
- `LOCAL_IMAGE_PROVIDER_OOM`
- `LOCAL_IMAGE_OUTPUT_INVALID`
- `LOCAL_IMAGE_ROUTE_UNDEPLOYED`

Automatic regeneration is forbidden for assessment output unless a higher-level workflow explicitly
creates a new attempt and records why.

## Dependency direction and adapter ownership

Contracts and workflow models define the route and provider receipt shape. Catalog application
services own pointer resolution, policy checks, idempotency, transactions, and artifact commit.
GPU, PyTorch, Diffusers, model loading, filesystem model cache, and CUDA checks belong to an
infrastructure adapter beneath Catalog.

Contract packages must not import PyTorch, Diffusers, filesystem adapters, SQLAlchemy sessions, or
HTTP clients. The provider adapter must not be imported by the web GUI or item registry.

## Safety policy for assessment visuals

Local diffusion output is not trusted to render facts, Korean text, scales, labels, equations, or
diagram topology. Those remain in SVG/HWPX deterministic layers.

Allowed first use:

- neutral laboratory background;
- environment texture;
- non-labeled scene backdrop;
- organism or object silhouette used only as visual context;
- stylistic paper/background layer behind exact SVG marks.

Forbidden first use:

- answer-bearing labels or symbols;
- graph axes, tick labels, measurements, equations, or molecular structures;
- generated Korean text;
- fine apparatus geometry that affects the answer;
- faces/identity-like images unless a separate safety and consent policy exists.

## Simpler alternative and why it is insufficient

Keeping only deterministic SVG is safest and remains the default, but it cannot produce organic
visual texture, scene context, or naturalistic stimuli that content teams may want. Directly calling
a model from a worker is simpler to code, but it violates the orchestrator boundary, loses provider
provenance, and makes retries/resource contention hard to control. A Catalog-owned local provider
with a single GPU lease is the smallest extension that preserves EOM's pointer and artifact model.

## Sources reviewed

- NVIDIA GeForce RTX 5080 product page:
  `https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5080/`
- PyTorch 2.7 release notes:
  `https://pytorch.org/blog/pytorch-2-7/`
- Hugging Face model cards:
  `https://huggingface.co/segmind/SSD-1B`,
  `https://huggingface.co/black-forest-labs/FLUX.1-schnell`,
  `https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0`,
  `https://huggingface.co/stabilityai/stable-diffusion-3.5-medium`
