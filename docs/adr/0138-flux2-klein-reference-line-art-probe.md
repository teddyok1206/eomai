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

## 2026-09-28 probe outcome

The exact three-case probe completed and was published as Artifact
`artifact_a57beb9984694f739b4b9d8d7590e080`, revision
`rev_bb5e28f15ee74ed3bf730c9367cb0d3d`. The canonical result hash is
`sha256:d57e0512436c5206e430ebe02e998b5ba498266a3029a3c192b0704405271366`; the
file-set manifest hash is
`sha256:bb65257afb6c53470dd8bc263234af583c5034f53499d3bfa94c6f87d425acd1`.
The three 50-step cases took 55.391, 40.429 and 39.917 seconds. Peak allocated GPU memory was
8,913,644,032 bytes on the RTX 5080; the isolated systemd unit completed in 2 minutes 50 seconds
with a 24.5 GiB system-memory peak.

The technical execution boundary passed, but the current reference-conditioning strategy did not
pass the activation boundary. All outputs were clean PNGs without pseudotext, yet the model
reconstructed the named subject rather than preserving the exact crop composition. In particular,
the partial automobile crop became a complete detailed automobile with a shadow, and the plant
reference changed from a leafy specimen to a flowering specimen. The fossil retained a broadly
similar centered specimen layout but invented internal morphology. This also shows that prompt
prohibitions alone do not enforce sparse detail or composition preservation.

Consequently FLUX.2 remains `EVALUATION_ONLY` with `activation_policy=FORBIDDEN`. These outputs are
useful negative evidence: the model is technically feasible on the local GPU and can make clean
black-and-white illustrations, but it must not replace the deterministic Python/SVG path or the
current provider for reference-faithful rendering. Any successor experiment must use a distinct
plan/revision and demonstrate composition fidelity explicitly; it must not reinterpret this result
or silently tune the prompt/seed under the same run identity.

The user subsequently accepted the visual style, especially the automobile result. That product
assessment refines the interpretation above: FLUX.2 is not rejected as a renderer; its line-art
style is a viable candidate, while reference composition remains the blocking invariant.

A second immutable run removed contradictory subject wording and explicitly prohibited completing
cropped objects. It was published as Artifact `artifact_3a7be3bbc7434ebaaac1023636de8e9a`,
revision `rev_01792d3dd923457399378e710f31d5ed`, with result hash
`sha256:c1465a1f34fd2f0742378266987d32bfd471e1c596bec6a3ce850da2d747a960` and
file-set manifest hash
`sha256:a63de61f0812b778644db339d19ac7afa6c875716c6484938dfff45c0ece884a`.
Against a foreground-threshold bounding box, candidate-to-conditioning area ratios improved from
8.09 to 2.29 for the automobile and from 10.12 to 0.78 for the fossil; normalized center drift fell
to 0.031 and 0.009 respectively. The plant retained the correct no-flower semantics but still
extended its stem, with area ratio 2.55 and center drift 0.114. Prompt correction therefore helps
but does not provide a structural guarantee.

The next successor must keep the accepted style prompt while moving placement and scale out of the
generative model. A deterministic layout adapter should compute the reference foreground bounding
box, stage the bounded subject crop, and composite the validated generated subject back into that
exact rectangle on the target canvas. Its typed result must report source/output normalized bounds,
area ratio and center drift. A structural-control model may be evaluated separately if internal
edge topology must also be preserved. Prompt wording alone is no longer considered sufficient for
the composition gate.
