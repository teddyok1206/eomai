# ADR 0128: Train an evaluation-only LoRA probe from the reviewed campaign crop set

- Status: Accepted for protocol-first implementation
- Date: 2026-09-26 UTC
- Scope: the immutable campaign crop set published under ADR 0127

## Responsibility and boundary

The Orchestrator resolves the published campaign crop-set revision, publishes a probe plan,
materializes only the pinned inputs into an isolated trainer workspace, starts the bounded worker,
validates its typed result, and publishes successful output through the existing control-Artifact
boundary. The trainer has no PostgreSQL, NAS, repository, network, or root-Codex access. It reads
staged files and writes local result, checkpoint, and adapter files only. No worker communicates
with another worker.

The canonical chain is:

```text
training authorization revision
  + campaign inventory/review/refinement revisions
  -> campaign crop-set revision (12 TRAIN, 1 VALIDATION, 2 HOLDOUT)
  -> campaign micro-probe plan revision
  -> isolated 200-step worker result
  -> evaluation-only adapter Artifact revision
  -> paired BASE/ADAPTER holdout evaluation revision
```

The prior single-pilot science micro-probe contracts and artifacts remain immutable. The campaign
path uses additive schemas because its sample identity is a reviewed campaign crop, not an original
candidate, and because its crop-set pointer has a different schema and member path.

## Identity, pointers, and resolution

The campaign plan pins the crop-set Artifact ID, Artifact Revision ID, member path, schema, media
type, member-byte SHA-256, and crop-set semantic SHA-256. It also pins the base-model revision,
runtime dependency versions, hyperparameters, partition member IDs, authorization reference,
source commit, creator, and UTC timestamps. The command pins the exact plan revision and embeds the
same plan for the isolated worker. Realized samples preserve campaign sample ID, parent candidate
ID, source crop hash, realized training hash, caption hash, document ID, and exam-group hash as
separate immutable values.

Every dereference checks target/revision existence, approved lifecycle, schema, media type, path,
manifest metadata, regular single-link stable bytes, bounded size, and SHA-256. Workspaces are
temporary materializations and never become canonical identity. PostgreSQL stores only Artifact
metadata and pointers; PNG, checkpoint, adapter, and evaluation bytes stay in Artifact storage.

## Access patterns and data structures

Dominant operations are exact lookup by sample ID, partition membership, uniqueness, stable ordered
iteration, and append-only publication. Crop members use a dictionary keyed by sample ID; partition
coverage and duplicate checks use sets; realized output uses sorted immutable tuples. Training is
`O(n)` time and memory for `n = 15` published crop members before GPU compute. No database schema or
index is added because existing indexed Artifact and revision identities plus publisher idempotency
keys own all persistence. The GPU remains guarded by the existing exclusive file lock.

## Training and evaluation policy

The first campaign run is fixed at 200 optimizer steps, rank/alpha 8, 768x512, batch 1, gradient
accumulation 4, fp16, AdamW8bit, frozen text encoders and VAE, no random flip, and a fixed seed. Only
the 12 TRAIN crop members enter the runtime dataset. VALIDATION and HOLDOUT members are never staged
as training samples. A successful result must contain exactly 12 unique realized samples and exact
adapter files. Its adapter remains `EVALUATION_ONLY` with `activation_policy=FORBIDDEN`.

The subsequent evaluation renders BASE and ADAPTER variants for the two exact HOLDOUT captions with
identical prompts, seeds, model revision, scheduler, dimensions, inference steps, and guidance. A
probe may advance only after integrity checks, leakage checks, fixed metrics, and a recorded visual
review. Training loss alone is not an activation criterion.

## Transaction, retry, and failure

Plan publication is idempotent on its semantic identity. A workspace and run identity are derived
from the pinned plan pointer and attempt. The first attempt is immutable; an inconclusive or failed
run is preserved and any retry requires an additive attempt contract or successor plan rather than
overwriting files. Missing/stale/hash-mismatched inputs, partition leakage, duplicate realized
samples, runtime drift, non-finite loss, wrong step count, GPU contention, or uncertain worker
outcome fails closed. Publication occurs only after worker output validation. Activation is a
separate later boundary and cannot be caused by this protocol.

Rollback before activation means stopping the transient unit and retaining the base-only provider
binding. After a later canary activation, rollback selects the previous immutable provider binding;
it never deletes the adapter, plan, result, or evaluation history.

## Simpler alternative rejected

Re-labeling campaign sample IDs as legacy candidate IDs or rewriting the prior crop-set contract
would destroy provenance and immutable compatibility. Training directly from local PNG paths would
make the dataset unreproducible. Creating a new queue or training framework is unnecessary: the
existing isolated trainer, control-Artifact publisher, systemd sandbox, GPU lock, and evaluation
backend already own the required adapter boundaries. An additive campaign protocol is the smallest
implementation that preserves these invariants.
