# ADR 0065: Bounded local-GPU semantic subject

## Decision

The validated content-team drawing remains the canonical source. Its immutable drawing hash binds
the complete team-lead `illustration_prompt`, the worker's exact `generation_prompt`, semantic
description, constraints, labels, overlay, and `alt_text`. The Catalog local-image adapter derives
the non-authoritative SSD-1B raster request from the worker-authored `alt_text`, prefixed by the
fixed `monochrome:` renderer instruction. It appends a compact fixed negative denylist and the
worker's bounded negative prompt. No source prompt is truncated or rewritten.

The GPU raster is one component of a typed manifest. Deterministic SVG remains authoritative for
labels, numbers, equations, and exact geometry; only the orchestrator/Catalog boundary commits the
validated composite artifact to NAS.

## Access patterns and structures

Drawing and provider identities are immutable keyed lookups. Prompt construction is ordered tuple
concatenation in O(c) time and space for at most 50 subject characters and 120 worker-negative
characters. Request identity includes the drawing hash, policy revision, and derived prompt hashes,
so idempotent lookup remains O(1) and a policy or source change cannot reuse an old request.

## Failure and retry

Unsafe content or an overlong worker field fails with `LOCAL_IMAGE_INPUT_INVALID`. Both provider
tokenizers independently enforce the 77-token limit and fail closed; the adapter never silently
truncates. A retry uses a new immutable drawing/result revision or the identical request identity.

## Alternatives

Passing the complete Korean team prompt exceeded both fixed CLIP contexts in the live canary.
Blind token truncation would silently remove subject or safety constraints. Loading model
tokenizers in Catalog would couple the application service to GPU infrastructure. The bounded
semantic subject keeps that dependency inside the provider while preserving the complete reviewed
instruction as provenance. Historical V5 background drawings retain their existing worker-authored
generation prompt as the subject; the bounded `alt_text` projection applies to V6 hybrid drawings.
