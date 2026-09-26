# ADR 0129: Expand the science-campaign LoRA probe without partition leakage

- Status: Accepted for protocol-first implementation
- Date: 2026-09-26 UTC
- Scope: successor to the immutable campaign crop set and micro-probe in ADR 0127/0128

## Responsibility and boundary

The first campaign probe trained successfully from 12 TRAIN crops, but paired holdout inspection
showed one modest improvement and one semantic-shape regression. A read-only audit of all 768
campaign candidates confirmed that the additional broad `DETERMINISTIC_RENDERER_ONLY`
astronomical, fossil, and organism candidates are diagrams rather than missed photographs. The
remaining data bottleneck is the V1 crop-set rule that admits at most one crop per document and
exam group, even when distinct raster candidates in the same TRAIN group are not duplicates.

The Orchestrator remains the only component that resolves campaign pointers, materializes literal
crops, validates bytes, and publishes canonical Artifacts. The isolated trainer reads only staged
inputs and writes only its local workspace. It does not read PostgreSQL or NAS and cannot activate
an adapter.

## Canonical source, revisions, and pointers

The canonical chain remains:

```text
published campaign inventory + strict raster review + training authorization
  -> immutable refinement-plan successor
  -> immutable campaign crop-set V2 Artifact
  -> evaluation-only expanded probe plan/command/result
  -> paired BASE/ADAPTER holdout evaluation
```

Every pointer pins logical ID, immutable revision, schema, media type, member path, and SHA-256.
V1 bytes and the first adapter remain immutable evidence. V2 never resolves an implicit latest
revision and never rewrites V1 outcomes.

## Access patterns and data structures

Dominant operations are candidate lookup, refinement lookup, bounded multiplicity accounting,
byte/perceptual-hash deduplication, ordered manifest assembly, and partition coverage. Validators
use dictionaries keyed by candidate/refinement/group, counters keyed by document and exam group,
sets for exact hashes and parent candidates, and sorted tuples for canonical output. Validation is
`O(c + r + m)` time and memory for 768 candidates, at most 1,024 refinements, and at most 256 crop
members. No new database table or index is required; existing Artifact/Revision indexes and unique
idempotency keys own publication.

## V2 selection and leakage policy

V2 permits multiple **distinct parent candidates** from one document or exam group only when all
members retain the partition pinned by the original campaign source. It enforces:

- at most 3 members per document;
- at most 4 members per exam group;
- one crop per parent candidate;
- unique crop bytes and no perceptual duplicate within Hamming distance 2;
- no exam group appearing in more than one partition;
- literal rectangular crops only, with no erasure, inpainting, reconstruction, or pre-publication
  resizing;
- no `PYTHON_SVG_REQUIRED`, authoritative geometry, plot, or table parent.

This preserves holdout isolation while allowing several unrelated photographs from one TRAIN exam
group. The successor target is bounded to 16 TRAIN, 4 VALIDATION, and 4 HOLDOUT crops. The expanded
probe remains `activation_policy=FORBIDDEN`; paired evaluation and a separate activation decision
are mandatory.

## Transaction, retry, and failure behavior

All source pointers and bytes are validated before publication. Crop-set publication is one atomic
file-set commit through the existing control Artifact publisher. Training/evaluation commands are
content-addressed and stage into fresh workspaces. Same semantic input is idempotent; drift under a
derived identity conflicts. Missing/stale pointers, hash mismatch, cross-partition group reuse,
multiplicity overflow, duplicate parent/hash/perceptual content, or output mismatch fails closed.
Failed attempts remain historical and are never reinterpreted as success.

## Dependency direction and adapter ownership

Schema and Pydantic contracts live in `image_contracts`. Application scripts validate and stage
typed commands. Orchestrator adapters own PostgreSQL/NAS resolution and publication. The trainer
implements the command in an isolated filesystem/systemd boundary. No domain or contract module
imports infrastructure.

## Simpler alternative rejected

Increasing steps on the same 12 crops would amplify overfitting without adding visual coverage.
Training on full page fragments would teach answer masks, labels, and layout artifacts. Reusing V1
while silently relaxing its uniqueness rule would mutate a released contract. The additive V2 crop
set and expanded probe are the smallest change that increases independent raster coverage while
keeping provenance, split isolation, rollback, and historical reproducibility.
