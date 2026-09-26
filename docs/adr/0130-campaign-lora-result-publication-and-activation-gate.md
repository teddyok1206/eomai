# ADR 0130: Publish campaign LoRA evidence before any activation decision

- Status: Accepted for protocol-first implementation
- Date: 2026-09-26 UTC
- Scope: terminal results from the campaign LoRA probe and paired holdout evaluation

## Responsibility and system boundary

The isolated image trainer may write a typed result, adapter files, and evaluation PNGs only to its
staged local workspace. Those bytes are not durable product evidence until the Orchestrator has
validated and committed them as immutable Artifact revisions. Publication is not activation: the
adapter remains `EVALUATION_ONLY` and `activation_policy=FORBIDDEN` until a separate, explicit
successor provider-binding decision exists.

The publication application scripts validate the released JSON Schema and Pydantic result,
recompute every declared byte hash and size with safe regular-file reads, and call the existing
Orchestrator-only control-file-set publisher. The worker receives no PostgreSQL or NAS access.

## Canonical source and revision model

The canonical chain is:

```text
crop-set Artifact revision
  -> probe-plan Artifact revision
  -> local worker result + adapter workspace materialization
  -> immutable training-result file-set Artifact revision
  -> paired holdout evaluation workspace materialization
  -> immutable evaluation file-set Artifact revision
  -> human/automated activation decision (separate successor contract)
```

Training publication includes the canonical worker `result.json`, the adapter manifest, the exact
Diffusers configuration, and the safetensors weights. Evaluation publication includes its canonical
result and every BASE/ADAPTER PNG pair. PostgreSQL stores only job, relationship, pointer, state,
hash, and bounded manifest metadata; large adapter and PNG bytes remain in Artifact storage.

## Pointers and resolution checks

Each returned pointer pins Artifact ID, Artifact Revision ID, member path, schema, media type, and
member SHA-256. Publication validates workspace path identity, regular single-link files, bounded
size, canonical JSON, released contract versions, result-to-command identity, adapter manifest,
declared file hash/size, exact expected member set, success lifecycle, and fixed 200-step count.
Missing, stale, extra, duplicate, symlinked, mutable, or hash-mismatched members fail explicitly.

## Access patterns and data structures

The hot operations are exact member lookup, exact-set comparison, deterministic ordered manifest
assembly, and idempotent lookup by run ID. They use dictionaries and sets plus sorted immutable
tuples, so validation is `O(n)` time and memory for four training members and at most nine evaluation
members. Existing indexed job idempotency and Artifact/Revision keys own concurrency; no new table or
index is required.

## Transaction, concurrency, retry, and idempotency

All workspace bytes are validated before a NAS write. `ControlFileSetPublisher` owns one atomic
Artifact commit and uses a run-ID-derived idempotency key. Byte-identical replay returns the existing
revision; semantic drift under the same run identity conflicts. A failed publication never rewrites
the worker result and never creates an activation record. The transient trainer unit may be stopped
without deleting its immutable inputs or completed workspace evidence.

## Dependency direction and adapter ownership

Released schemas and Pydantic models remain in `image_contracts`. Application scripts coordinate
validation and invoke interfaces. Filesystem, PostgreSQL, and NAS behavior stays in Orchestrator
adapters. Contract/domain packages import no infrastructure. The provider-binding activation path
consumes only a future validated Artifact pointer and never a worker workspace path.

## Failure and rollback

Schema, pointer, file, or result mismatch fails closed with a stable publication error. Until a
separate activation gate succeeds, rollback is simply to retain the existing base-only provider
binding. A future activated adapter is rolled back by selecting the previous immutable provider
binding; training and evaluation history is preserved.

## Simpler alternative rejected

Keeping only the local trainer workspace leaves durable evidence outside the canonical Artifact
boundary and makes cleanup unsafe. Copying weights directly into the provider directory would bypass
validation, provenance, and rollback. Creating a new registry or queue is unnecessary because the
existing typed result contracts and control-file-set publisher already own bounded immutable
publication.
