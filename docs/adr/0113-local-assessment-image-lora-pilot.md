# ADR 0113: Local assessment-image LoRA pilot

- Status: Accepted for protocol-first implementation
- Date: 2026-09-25 UTC
- Scope: local SSD-1B training and evaluation only

## Decision

EOM will evaluate one bounded LoRA adapter trained to reproduce the visual style of Korean science
assessment figures.  The adapter will not replace or mutate the installed SSD-1B revision.  It will
be a separate immutable Artifact Revision bound to the exact base model, training dataset revision,
training plan, training receipt, and holdout evaluation result.

The pilot optimizes non-authoritative raster style only.  Exact graphs, maps, apparatus, particles,
cells, axes, values, arrows, labels, boundaries, answer-bearing geometry, tables, and panel labels
remain deterministic SVG or native HWPX content.  Korean semantic descriptions remain in the
canonical drawing, while the local model continues to receive a bounded English subject.

## Responsibility and boundary

The Catalog application owns selection of eligible source pointers and construction of the
immutable dataset manifest.  A new isolated trainer adapter reads an orchestrator-staged dataset and
base-model revision, writes only to its local workspace, and returns a typed result.  Only the
orchestrator may validate and commit the dataset, LoRA, receipts, and evaluation artifacts to NAS.
The image provider may load an approved adapter only through a successor provider binding.

The trainer does not query PostgreSQL, read NAS, contact external APIs, publish to a model hub, or
modify the generation provider environment.  The current `eom-image` runtime remains inference-only.

## Canonical sources and revision model

The canonical source chain is:

```text
approved past-exam Item Revision
  -> accepted extraction-result Artifact Revision
  -> pinned source page-image Artifact Revision + normalized bounding box
  -> immutable training-dataset revision + deterministic crop member + English caption
  -> immutable training plan
  -> immutable LoRA Artifact Revision + training receipt
  -> immutable holdout evaluation result
  -> optional successor provider binding
```

Logical IDs, revision IDs, Artifact IDs, Artifact Revision IDs, and SHA-256 hashes remain separate.
A path is only a materialization location.  Existing model, dataset, prompt-policy, and evaluation
revisions are never overwritten or resolved through an implicit latest pointer.

## Dataset eligibility and exclusions

The accepted Graph base contains 520 occurrence-backed past-exam targets and 537 visual
observations.  The first audit observed 162 `RASTER` and 50 `MIXED` visuals, but these counts are an
upper bound rather than an automatic training set.  Each candidate must pass all of the following:

- exact approved Item Revision and accepted extraction-result pointer;
- exact page-image Artifact Revision, media type, lifecycle, access, member, size, and SHA-256;
- a bounded nonempty crop resolving inside the source image;
- no overlap with the 12 immutable evaluation holdout source anchors;
- no embedded answer, explanatory text, item number, publisher mark, or required scientific label;
- no human subject, full page, table, graph, or authoritative diagram geometry;
- representation suitable for organic objects, nonhuman animals, fossils, natural textures, or
  non-authoritative natural scenes;
- duplicate byte hash and perceptual near-duplicate cluster removed deterministically;
- an independently reviewed English caption describing count, viewpoint, exterior, and physical
  state without style terms or answer-bearing labels.

The first pilot is bounded to 100-200 unique training crops.  If fewer than 100 pass, the pilot stops
rather than weakening eligibility.  The 12 fixed holdout samples and any near-duplicates of them are
excluded from training.

The first exact read-only projection against the 2026-09-25 accepted source snapshot found 72
strictly cropable candidates and 37 explicit omissions whose page or bounding-box provenance was
not sufficient to create a crop.  All projected candidates remain `PENDING`; projection is not a
content or rights approval.  Across all bounded `RASTER`/`MIXED` observations there are 131 possible
visuals, but the additional diagram/apparatus classes overwhelmingly carry axes, labels, scales,
legends, symbols, data points, or other authoritative geometry.  They must not be silently admitted
to satisfy the minimum sample count.

Consequently the first pilot is stopped before dataset materialization while the strict eligible
population is below 100.  A future successor eligibility policy may admit a larger population only
after a human-approved crop/mask or redaction contract preserves exact source provenance and keeps
all scientific geometry, labels, and values deterministic.  That successor is a separate protocol
decision; it does not weaken `local-image-lora-eligibility/1.0` or reinterpret this projection.

The DRAFT and FINAL review revisions share an exact `candidate_population_sha256` derived from the
source snapshot, holdout, selection/policy revisions, immutable candidate pointers/crops, and typed
omissions.  Human decisions and captions are deliberately excluded from that population hash but
remain covered by the final review self-hash.  This prevents a review successor from adding,
removing, or repointing a candidate while still allowing pending decisions to become eligible or
excluded.

Source permissions and intended-use metadata must authorize internal derivative model training.
Absence or ambiguity is an explicit `TRAINING_SOURCE_RIGHTS_UNCONFIRMED` exclusion; approval as a
RAG source alone is not silently treated as training authorization.

## Access patterns and data structures

- Exact pointer lookup uses indexed IDs and maps keyed by revision ID.
- Membership and holdout exclusion use sets and database uniqueness constraints.
- Stable output uses tuples sorted by `training_sample_id`.
- Exact duplicate detection uses SHA-256 maps in expected `O(n)` time and `O(n)` memory.
- Perceptual duplicate detection uses a fixed-size perceptual hash and bounded Hamming buckets,
  avoiding all-pairs pixel comparison.  The expected pilot scale is at most 537 observations.
- Revision history and receipts are append-only.  Training claims use the existing atomic
  claim/lease/idempotency model rather than directory scans.
- PostgreSQL stores pointers, status, indexes, and bounded receipts only.  Crop PNGs, accepted
  adapter weights, and long logs are Artifacts and are never stored in DB rows.  Optimizer
  checkpoints are temporary worker-local materializations and are not canonical or published.

Candidate indexes are not added speculatively.  Existing item-revision, artifact-revision, source
anchor, workflow/job, and idempotency indexes are reused; a new DB index requires an observed query
plan showing a missing indexed lookup.

The candidate projection is an `O(a + v + p)` pass over accepted analyses, visual observations, and
source pages.  Maps keyed by item/source page and source anchor avoid repeated corpus scans; sets
provide holdout membership and identity deduplication.  Missing crop provenance is retained as a
typed omission rather than being silently dropped.

## Training configuration

The pilot trains UNet LoRA weights while keeping both text encoders and the VAE frozen.  It starts
with rank 8, alpha 8, batch size 1, gradient accumulation 4, gradient checkpointing, fp16, a fixed
seed, and a bounded number of steps selected after a preflight memory probe.  Resolution is a
documented multiple of 64 no larger than the provider's native training capability.  Random
horizontal flips are disabled because scientific orientation may carry meaning.

The RTX 5080 exposes 16 GB VRAM.  `peft` and `bitsandbytes` are not installed in the
current inference environment.  They may be added only to a separate pinned trainer environment;
each dependency is required respectively for LoRA injection/serialization and bounded-memory
optimization.  The bounded immutable sample tuple is loaded directly, so the pilot does not add a
dataset framework.  No dependency is added to API, Web, Catalog, HWPX, or the inference provider
merely for training.

## Transaction, concurrency, retry, and idempotency

Dataset publication is one transaction over manifest metadata after all members have been validated
and committed by the orchestrator.  A training run is identified by the canonical hash of its base
model pointer, dataset revision, hyperparameters, dependency versions, and seed.  The same identity
replays the same terminal receipt; different input with the same key fails closed.

At most one training job may hold the GPU training lease.  Image inference and LoRA training are
mutually exclusive at the GPU capacity boundary.  Checkpoints are local temporary materializations
bound by `local-image-lora-checkpoint-manifest/1.0` to the exact run, plan hash, attempt, completed
optimizer step, micro-step, file set, and hashes.  A process restart may resume only the highest
complete checkpoint for the same attempt; mismatches fail closed before deserialization.  A failed
run remains failed; retry creates a new attempt bound to the same plan, not a rewritten result.
Cancellation stops the trainer and releases its lease but does not publish partial weights.

## Evaluation and activation gate

The immutable 12-sample holdout is rendered with base policy 1.6 and the adapter using identical
subjects, seeds, sampler, dimensions, and negative prompt.  The evaluation checks:

- subject, count, viewpoint, and physical-state fidelity;
- unrelated person, portrait, fashion, room, stage, photo, anime, manga, comic, and text leakage;
- white background, grayscale distribution, margins, crop completeness, and line readability;
- OCR findings and deterministic overlay compatibility;
- nearest training-image byte/perceptual similarity to detect memorization;
- blinded human preference and scientific suitability.

Automatic completion is not activation.  The adapter must have no holdout contamination, no exact
or near-exact training-image reproduction, no increase in subject failures, and no person/text
leakage.  Human review must prefer the adapter on exam suitability without finding a new critical
scientific mismatch.  Otherwise provider policy 1.6 remains active and the failed candidate is
preserved only as historical evidence.

Activation requires a successor provider binding that pins both base model and adapter revisions,
then one bounded single-item canary.  Rollback changes the active binding back to the base-only
revision; it does not delete the adapter or rewrite historical requests.

## Failure modes

Dangling, stale, unauthorized, wrong-schema, wrong-media, non-approved, or hash-mismatched pointers
fail before crop materialization.  Dataset duplicates, holdout leakage, caption-policy failure,
unbounded files, CUDA OOM, nonfinite loss, dependency drift, checkpoint mismatch, and adapter/base
incompatibility have stable error codes.  No error substitutes the latest revision, broadens source
rights, reduces validation, or falls back to an external model.

## Simpler alternative

Prompt policy 1.6 remains the simpler production default and may prove sufficient.  LoRA is justified
only as a bounded experiment because the local checkpoint repeatedly exhibited unrelated-person and
photographic priors.  Full-model fine-tuning is rejected for the pilot: it requires more memory and
storage, increases catastrophic-forgetting risk, and makes rollback and provenance harder without
first proving that a small style adapter is insufficient.
