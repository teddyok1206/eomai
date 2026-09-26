# ADR 0126: Carry a reviewed visual campaign into a bounded LoRA probe

- Status: Accepted for protocol-first implementation
- Date: 2026-09-26 UTC
- Scope: the completed three-shard science-visual campaign and its 32 published review batches

## Context

The current campaign contains 768 candidates in three disjoint immutable pilot shards. ADR 0125
made semantic review recoverable by publishing 32 bounded command/result pairs. The next boundary
must not rebuild the review from local TSV files or treat a workspace path as identity. It must
select the exact published batch-result revisions, merge their disjoint candidate sets once, and
carry only reviewed raster-style crops into an evaluation-only SSD-1B LoRA probe.

The released campaign inventory 1.0 remains the canonical broad-classification shape. A publication
receipt additionally records the exact ordered review-result pointers and semantic hashes used by
the merge. Later raster-review, crop-set, and micro-probe successors must pin that inventory revision
rather than resolving an implicit latest value.

## Responsibility and canonical sources

The Orchestrator owns merge, validation, Artifact publication, temporary materialization, and the
GPU training command. Review workers receive staged local crops and return typed results; they do
not read PostgreSQL or NAS and never publish artifacts. The canonical inputs are:

```text
three published pilot plan/result revisions
  + 32 published review-batch command/result revisions
  -> complete campaign pattern inventory revision
  -> complete raster-suitability review revision
  -> group-deduplicated campaign crop-set revision
  -> evaluation-only campaign micro-probe plan/result revision
```

The original PDFs, page images, crop candidates, broad reviews, strict reviews, normalized training
samples, adapter files, and evaluation renders remain separate immutable revisions.

## Access patterns and data structures

The dominant operations are exact key lookup, membership, deduplication, stable iteration, and
group-aware selection. Candidate, review, and source lookup use dictionaries keyed by immutable ID.
Coverage and duplicate checks use sets. Batch and output order use sorted tuples. Perceptual-near-
duplicate lookup keeps the existing bounded four-band hash index. Merge validation is `O(c + b)`
time and `O(c)` memory for `c = 768` candidates and `b = 32` batches; it does not repeatedly scan
the full campaign for each batch.

PostgreSQL stores only Artifact identities, revisions, relationships, state, and hashes. PNG and
adapter bytes remain in one canonical Artifact file set. Workspace files are temporary
materializations only.

## Strict raster gate and dataset

Broad `LORA_ELIGIBLE` means only that a candidate is worth a second look. The strict review covers
that population exactly once and permits `GPU_RASTER_ELIGIBLE` only for one non-authoritative,
nonhuman raster subject with an exact English caption. Text, labels, masks, panel composition,
answer-bearing structure, caption mismatch, and insufficient image content fail closed. A panel
candidate may proceed only through an explicit reviewed refinement whose output is a new crop
revision; the parent bytes are never silently reinterpreted.

The crop set resolves all three pilot shards through maps, preserves source/exam-group partitions,
and selects at most one perceptually distinct member per group. At least 12 distinct TRAIN groups,
one VALIDATION group, and two HOLDOUT groups are required for the micro probe. No sample is padded,
duplicated, moved across partitions, or inferred from a missing pointer.

## Training, evaluation, and activation

The first combined-campaign run is a 200-step evaluation-only UNet LoRA probe using the existing
offline SSD-1B trainer, pinned runtime dependencies, frozen text encoders and VAE, one exclusive GPU
lease, and `activation_policy=FORBIDDEN`. Base and adapter variants use the same holdout prompts,
seeds, scheduler, dimensions, steps, guidance, and deterministic scientific overlays.

Automatic success never activates the adapter. Advancement requires integrity checks, leakage and
nearest-training checks, fixed quantitative comparison, and a recorded human visual decision. A
later activation uses a successor provider binding and one bounded Item/HWPX canary. Rollback selects
the prior base-only binding and preserves all campaign and training history.

## Transactions, retry, and failure

Each publication validates all source pointers before the NAS commit and persists only its own
Artifact revision and receipt. Same semantic input is idempotent; different input under the same
identity conflicts. A failed worker attempt stays failed. Missing/stale/hash/schema/media/lifecycle
pointers, batch overlap or gaps, duplicate source groups, rights drift, fewer than the required
partitions, GPU/runtime drift, non-finite loss, or unconfirmed outcomes stop further side effects.
Historical Control Artifact members retain the publisher's `0660` mode. Resolution therefore uses
an approved pinned revision, `O_NOFOLLOW`, regular/single-link and stable-descriptor checks, bounded
reads, manifest metadata equality, and the exact content hash instead of rewriting historical modes.

## Simpler alternatives rejected

Concatenating local JSON/TSV files would lose published Artifact identity and retry provenance.
Training three unrelated shard adapters would not answer whether the combined corpus improves one
model and would complicate activation. Feeding all 768 candidates to the trainer would mix exact
scientific diagrams and text into generative pixels. The staged successor chain is the smallest
design that reuses the existing trainer while preserving campaign provenance and rollback.
