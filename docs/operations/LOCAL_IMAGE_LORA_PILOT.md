# Local assessment-image LoRA pilot runbook

This runbook executes ADR 0113 without changing the active local-image provider until the candidate
adapter passes an immutable holdout comparison and human review. All timestamps are UTC. The pilot
uses no external LLM or image API.

## Objective and non-goals

The pilot tests whether a small UNet LoRA can reduce unrelated-person and photographic priors while
preserving the existing SSD-1B model as the rollback authority. It trains only non-authoritative
raster style. Scientific labels, values, arrows, axes, tables, panel labels, and answer-bearing
geometry remain deterministic SVG or native HWPX content.

The pilot does not fine-tune the full model, alter the 520 accepted analyses, mutate the installed
model revision, use the 12 holdout sources for training, or publish checkpoints as canonical
Artifacts.

## Stage and exit-gate map

| Stage | Work | Exit gate |
|---|---|---|
| P0 | Contracts and rights boundary | Schema 2020-12/Pydantic parity; explicit derivative-training authorization required |
| P1 | Candidate review | Every eligible crop has an exact source pointer, bounded box, rights pointer, human-reviewed English caption, and no exclusion condition |
| P2 | Dataset materialization | 100–200 unique crops; holdout and near-duplicates absent; deterministic manifest and hashes |
| P3 | Isolated training | Exact runtime pins; one GPU lease; terminal typed result; adapter weights only |
| P4 | Holdout evaluation | Same 12 subjects/seeds/sampler/canvas for base and candidate; memorization and leakage checks |
| P5 | Human decision | Blinded exam-suitability review records an explicit accept/reject decision |
| P6 | Optional activation | Successor provider binding and one bounded Item canary; base-only binding remains rollback |

P0 contract and P2/P3 implementation tests may finish before source authorization. P1–P6 must not
silently bypass a missing gate.

## P0: authorization

The accepted legacy rights review authorizes internal corpus analysis and controlled model exposure.
It does not by itself assert permission to create derivative model weights. Before source pixels are
placed in a training dataset, the Orchestrator must publish one exact
`local-image-training-authorization/1.0` Artifact with:

- the pinned Graph/source snapshot;
- every exact rights-policy revision used by the candidate set;
- `permitted_use=INTERNAL_LORA_TRAINING`;
- `derivative_output=LORA_ADAPTER_ONLY`;
- `state=APPROVED` and the accountable operator identity.

The authorization is not inferred from repository ownership, RAG approval, filesystem access, or a
generic request to continue development. If it is absent or does not bind every candidate,
`TRAINING_SOURCE_RIGHTS_UNCONFIRMED` is terminal for the pilot input.

## P1: candidate access pattern and review

The dominant operations are exact revision lookup, source-anchor membership, and deterministic
ordered iteration. Implementations use maps keyed by Artifact Revision and source anchor, sets for
holdout and duplicate membership, and sorted immutable tuples for output. They do not scan the same
521 Artifact records once per visual.

Candidates are derived from the pinned 520 occurrence-backed accepted analyses and their exact
extraction/page-image revisions. Only `PHOTOGRAPH` and `COMPOSITE` observations rendered as `RASTER`
or `MIXED` may proceed to manual eligibility review. A reviewer rejects full pages, answer/explanation
content, humans, publisher marks, item numbers, embedded labels, tables, graphs, authoritative
geometry, ambiguous crops, and any source whose intended use is not authorized.

An eligible candidate receives a bounded English caption describing only subject count, viewpoint,
exterior, and physical state. Style words and answer-bearing semantics are forbidden. Caption work,
if delegated, is a structured worker task routed through the Orchestrator; workers never communicate
directly or read NAS.

The complete population is first published as an immutable `DRAFT`
`local-image-training-eligibility-review/1.0` member whose undecided entries are `PENDING`. Automated
projection never upgrades an entry to `ELIGIBLE`. A human-reviewed successor is `FINAL`, contains no
pending entries, retains every excluded candidate and its reasons, and recomputes the eligible
subset hash from the exact typed candidate values. The candidate inventory is valid only when it is
byte-for-value equal to that final eligible subset. The dataset manifest pins both Artifact members,
so a later reviewer decision or caption cannot be silently substituted.

### Current read-only projection status

The exact 2026-09-25 projection over the pinned 520 occurrence-backed accepted analyses produced:

- 72 cropable `PHOTOGRAPH`/`COMPOSITE` candidates, all `DRAFT` + `PENDING`;
- 37 typed `AMBIGUOUS_CROP` omissions with insufficient page/bounding-box provenance;
- 131 bounded `RASTER`/`MIXED` visuals across all representation kinds, most additional examples
  carrying authoritative labels, axes, scales, legends, symbols, or geometry.

This does not satisfy the 100-sample minimum.  Training and dataset publication therefore remain
stopped.  Do not lower the minimum, mark pending rows eligible, broaden the representation allowlist,
or infer derivative-training rights to make the count pass.  The safe next work is human review of
the 72 candidates and a separate protocol-first crop/mask successor proposal for additional source
classes.  Neither action starts a GPU training job.

## P2: deterministic dataset

The Orchestrator stages exact validated page members into a local workspace. The trainer dataset
builder uses normalized bounding boxes, grayscale conversion, and a 768×512 white letterbox. It
checks source bytes through `O_NOFOLLOW`, immutable file identity, declared size, and SHA-256.

Exact duplicate detection is a hash set. Near-duplicate lookup uses four 16-bit average-hash buckets
and a Hamming-distance threshold of two. The 12 holdout anchor IDs are a set checked before crop
materialization. The dataset must contain 100–200 samples after all exclusions; a smaller result
fails instead of weakening eligibility.

Only the Orchestrator may commit the resulting dataset file set to NAS. PostgreSQL receives bounded
metadata and immutable pointers, never crop PNG bytes.

## P3: isolated runtime and recovery

The `eom-image-trainer` environment is separate from inference and pins the plan-declared Python,
PyTorch/CUDA, Diffusers, Transformers, Accelerate, PEFT, and bitsandbytes versions. The
`eom-image-trainer@.service` unit:

- runs as `eom-image`, which is not in `eom`, sudo, Docker, LXD, or adm;
- has no network, NAS, repository, EOMIS, secret, or inference-workspace access;
- can read only the pinned model and its own environment;
- can write only its exact training workspace and persistent GPU lock;
- shares `/var/lib/eom-image/gpu0.lock` with inference, preventing concurrent GPU use.

The initial plan is UNet LoRA rank/alpha 8, 768×512, batch 1, accumulation 4, fp16, AdamW8bit,
learning rate `1e-4`, no flips, fixed seed, and 800 optimizer steps. Trainable LoRA parameters use
float32 master values under mixed precision. Both text encoders and the VAE are frozen; their prompt
embeddings and latents are precomputed and then released from GPU memory.

Every 200 optimizer steps, the worker atomically materializes a local checkpoint containing LoRA
weights, optimizer state, and CPU/CUDA RNG state. The checkpoint manifest binds run ID, plan hash,
attempt, optimizer steps, micro-steps, exact files, and hashes. Recovery accepts only the highest
complete checkpoint for the same attempt and verifies hashes before safe deserialization. A terminal
failed attempt is not rewritten; a deliberate retry uses a new attempt.

The worker emits only a typed local result. The Orchestrator validates the adapter file set and
manifest before committing a candidate Artifact and terminal receipt. Partial outputs and optimizer
checkpoints are never activated or committed as adapter revisions.

## P4–P5: immutable evaluation and human review

The base and candidate render the same immutable 12-sample holdout with identical subject, seed,
sampler, canvas, negative prompt, and overlay. The comparison records subject/count/view fidelity,
person/portrait/room/photo/anime/text leakage, background and margin metrics, OCR findings, and
nearest training-image byte/perceptual similarity.

Automatic completion does not approve the adapter. Human review is blinded to variant identity and
must explicitly assess exam suitability and scientific mismatch. Activation is rejected if the
candidate contaminates the holdout, reproduces a training crop, increases subject failures, adds
person/text leakage, or introduces a critical scientific mismatch.

## P6: activation and rollback

Acceptance creates a successor provider binding that pins both the unchanged base revision and the
candidate adapter revision. Existing bindings and historical requests remain immutable. One bounded
single-item canary verifies the new binding through the normal image, Item, HWPX, and download
boundaries.

Rollback selects the prior base-only binding. It does not delete the adapter, rewrite its failed or
accepted evaluation, or change historical Item/HWPX provenance.

## STOP conditions

Stop before further side effects on any missing/stale/hash/schema/media/lifecycle/permission pointer,
rights ambiguity, holdout overlap, duplicate crop, fewer than 100 eligible samples, dependency or
GPU drift, nonfinite loss, checkpoint mismatch, CUDA OOM, unexpected person/text leakage, suspected
memorization, or unconfirmed worker outcome. Never substitute an implicit latest revision or fall
back to an external model.

## Evidence checklist

Record the source commit/tree, wheel hashes, installed runtime versions, authorization/inventory/
dataset/plan pointers, training command/result/receipt, checkpoint recovery test, adapter files and
hashes, holdout result, human review decision, activation binding, canary, and rollback pointer.
Keep model/GPU executions distinct from read-only checks and deterministic dataset builds.
