# ADR 0123: Publish science-visual campaign outputs as one immutable file set

- Status: Accepted for protocol-first implementation
- Date: 2026-09-26 UTC
- Scope: committing validated science-visual pilot manifests, rendered pages, and candidate crops

## Context and boundary

The science-visual pilot worker intentionally writes its bounded output to an isolated
local workspace. A result manifest alone is not a usable training or review input: its
page and candidate records point to PNG members that must be preserved with the same
validated result. Publishing only the manifest would leave the images in a disposable
workspace and violate the canonical-artifact boundary.

This decision does not let the worker write to NAS and does not store image bytes in
PostgreSQL. The worker still stages local results; only the orchestrator validates and
commits them.

## Decision

The science-visual publisher validates the complete closed output set and invokes the
existing `ControlFileSetPublisher` once. Its primary member is
`manifests/visual-pilot-result.json`; each validated `pages/...png` and `crops/...png`
member is committed in the same immutable Artifact Revision with its exact member
schema, media type, byte count, and SHA-256.

The generic bounded file-set limit is raised from 64 to 1,024 members. A visual pilot
can contain one manifest, at most 384 rendered pages, and at most 512 candidate crops
(897 members total). The limit remains explicit and below the one-GiB aggregate byte
bound; callers outside this contract remain bounded by the same generic validation.

```text
pinned campaign plan
  -> isolated worker workspace
  -> closed manifest/page/crop validation
  -> one orchestrator file-set commit
  -> immutable artifact/revision + file-set manifest
  -> suitability review and later LoRA inputs by typed pointer
```

## Access patterns, concurrency, and failure

Member paths are collected in a set for closure and uniqueness, then emitted as one
lexicographically sorted tuple. Validation is `O(n)` space and `O(n log n)` time for
`n <= 1,024` output members; file content is read only at validation and commit
boundaries. The result SHA-256 remains the idempotency key, so a retry resolves the
same committed file set or fails on any differing member identity.

Missing, symlinked, mutable, duplicate, stale, hash-mismatched, schema-mismatched, or
out-of-bound members fail before the commit. A database interruption after the NAS
commit is recovered by the existing file-set publisher; a failed publication never
promotes the workspace as canonical output.

## Simpler alternative rejected

Publishing just the JSON manifest is smaller but produces dangling local paths once a
workspace is removed. Copying page/crop bytes into database JSON would break the
artifact boundary and make resolution and retention worse. A new visual-specific NAS
writer would duplicate the orchestrator's tested idempotency and commit semantics.
