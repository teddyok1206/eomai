# ADR 0138: Evaluate FLUX.2 klein 4B for reference-conditioned assessment line art

## Status

Accepted for an additive, evaluation-only probe on 2026-09-28 UTC. This decision does not activate
FLUX.2, replace SSD-1B, reinterpret an existing style adapter, or authorize generated pixels for
answer-bearing labels, axes, arrows, tables, plots, measured geometry, or exact apparatus.

## Responsibility and system boundary

The probe answers one question: does the Apache-2.0 FLUX.2 klein Base 4B checkpoint preserve a
reviewed subject's morphology while rendering it as sparse monochrome assessment line art better
than the current SSD-1B path? The image provider remains an infrastructure adapter. The
Orchestrator resolves immutable inputs and uses the existing reference-simplification adapter before
staging both the source and its exact conditioning PNG. The isolated runner reads only those inputs
and a read-only installed model, and only the Orchestrator may publish validated outputs to NAS.

Python/SVG/HWPX continues to own every authoritative mark and editable label. The candidate model
may supply only non-authoritative organism, fossil, landscape, astronomical, or natural-object
morphology.

## Canonical source and revision model

```text
upstream FLUX.2 repository + immutable commit
  -> installed evaluation model revision + file manifest
reviewed visual-reference bundle revision
  -> normalized PNG Artifact member
  -> existing deterministic morphology-simplification adapter
  -> hash-pinned morphology-conditioning PNG
  -> candidate raster output
  -> immutable technical probe result
  -> separate human morphology/style review
```

The upstream repository revision, installed model revision, input Artifact Revision, conditioning
bytes, output bytes, and result hash are separate immutable identities. A filesystem path is only a
read-only materialization location and is never used as the model identity.

## Protocol and pointer design

JSON Schema 2020-12 defines four new wire contracts before runner behavior:

- `local-image-model-candidate-manifest/1.0` pins the exact FLUX.2 repository revision, Apache-2.0
  license, installed files, lifecycle and self-hash;
- `local-image-flux2-reference-probe-plan/1.0` pins the model manifest Artifact member, normalized
  reference pointers, prompts, seeds, sampler and existing simplification policy;
- `local-image-flux2-reference-probe-command/1.0` pins the staged workspace members and source
  commit; and
- `local-image-flux2-reference-probe-result/1.0` records only validated conditioning/output members
  and bounded runtime measurements.

All contracts are evaluation-only and carry `activation_policy=FORBIDDEN`. Existing SSD-1B provider
and V1-V3 reference-conditioned schema bytes remain unchanged.

Before dereference, the Orchestrator validates Artifact/Revision existence, exact member path,
schema, media type, lifecycle, size and SHA-256. The runner validates every staged regular file,
rejects symlinks, checks canonical JSON, binds the conditioning PNG to the plan, verifies the
installed model file set against its manifest, and does not access PostgreSQL or NAS. Keeping
simplification outside the candidate runtime avoids duplicating the existing authoritative
algorithm merely because FLUX.2 requires newer Diffusers dependencies.

## Access patterns and data structures

The probe performs exact-key lookup of at most twelve cases, then stable ordered iteration. A dict
or set validates case/member uniqueness in `O(C)` time and space. Each image preprocessing and
validation pass is `O(W*H)` over fixed 800x504 reference, 800x512 generation, or 800x500 delivery
rasters. The generation canvas is divisible by the FLUX.2 VAE/packing multiple; its central delivery
crop is deterministic. Model files are an ordered frozen tuple and are verified once per run; there
is no database, queue, cache, or new index.

## Runtime and dependency ownership

The existing production image-provider environment stays pinned to its SSD-1B-compatible Diffusers
release. FLUX.2 requires a separate explicit Conda environment because its pipeline support is
newer and has materially different transformer, tokenizer and offload behavior. This is the reason
for the isolated runtime dependency set; production packages are not upgraded in place.

The runner uses BF16, fixed seeds, CPU model offload, local-files-only resolution and one case at a
time. The RTX 5080 has 16 GiB VRAM while the vendor reports approximately 13 GiB for 4B inference;
peak allocation is still measured and an OOM fails closed. System RAM is close to the vendor's
fine-tuning recommendation, so this probe authorizes inference only, not LoRA training.

## Transaction, concurrency, retry, and idempotency

The exact plan and command hashes determine one run identity. One GPU lease permits one runner.
Outputs use exclusive creation and are never overwritten. A byte-identical completed result may be
reused after full hash validation. Partial files, model drift, input drift, an expired lease, OOM or
unknown completion state stop the run; a new key is not invented to bypass an uncertain outcome.

Publication, if performed, is one existing Orchestrator Artifact commit containing the plan,
manifest, conditioning PNGs, candidate PNGs and result. A failed probe publishes no approved model
or provider binding.

## Failure and rollback

Stable failures distinguish invalid canonical input, model-manifest drift, unsafe reference bytes,
GPU unavailability, OOM, execution failure and invalid output. There is no automatic fallback to a
different model, seed, prompt, source image or implicit latest revision. Rollback is removal or
disablement of the optional evaluation runner/model mount; the active SSD-1B binding is untouched.

## Simpler alternatives rejected

Hot-swapping the current provider is simpler but breaks released model, sampler, LoRA and receipt
identity. Prompt-only comparison cannot prove which model and reference bytes were used. Running an
untyped notebook would produce useful pictures but not reproducible evidence. Training a new LoRA
before a base-model bake-off risks spending hours adapting a model whose morphology preservation is
already inadequate. The bounded typed probe is the smallest honest next step.

## Acceptance boundary

Technical success proves only that the exact model ran within bounds and emitted valid PNGs. Human
review must separately score subject identity, landmark preservation, framing, exam-line economy,
pseudotext, invented anatomy and excessive detail. Activation and LoRA training remain forbidden
until that review prefers the candidate on representative organisms, fossils and natural objects.
