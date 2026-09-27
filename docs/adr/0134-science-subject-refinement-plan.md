# ADR 0134: Pin per-subject science visual refinement without activating the adapter

## Status

Accepted for protocol-first implementation on 2026-09-27 UTC. This decision does not activate a
LoRA adapter, change the production provider binding, or publish benchmark images as Item content.

## Responsibility and boundary

The three-seed review shows that one global image-model decision is invalid: two subjects stably
prefer the adapter, two stably prefer the base model, twelve are seed-dependent, and two are not
acceptable under either variant. The refinement plan records one explicit production disposition
and a bounded set of research actions for every reviewed raster subject. It is a control Artifact,
not a worker command or an activation record.

The existing subject-inventory V1 identity does not bind the complete subject definitions. Reusing
that identity after changing a prompt or route could therefore produce different bytes under the
same logical/revision identity. This plan never republishes or mutates V1. It pins the exact V1
inventory Artifact Revision and the exact multi-seed review Artifact Revision, and gives any future
prompt or route its own content-bound successor identity.

## Canonical source and revision model

```text
subject inventory Artifact Revision
  + multi-seed review Artifact Revision
  -> immutable per-subject refinement plan Artifact Revision
  -> later bounded prompt/route benchmark or adapter canary
```

Every pointer carries logical Artifact ID, immutable Artifact Revision ID, member path, schema,
media type, and SHA-256. The plan stores small typed decisions and candidate prompts only. It stores
no source PDF, PNG, model weights, or generated image.

## Access patterns and data structures

Dominant operations are lookup by subject ID/key, membership and duplicate detection, and stable
ordered iteration. Validators use dictionaries and sets and preserve a tuple sorted by subject key.
For at most 256 subjects and three evidence cases per subject, validation is `O(S + E)` time and
space. An immutable JSON Artifact is sufficient; no database table or index is justified.

## Decision semantics

- `BASE_ONLY` is the only production disposition for stable-base, stable-adapter, and mixed
  results. `ADAPTER_PRODUCTION_CANARY` is a research action and never changes that disposition.
- `BLOCK_UNTIL_REFINED` is required when neither BASE nor ADAPTER was acceptable at all three
  seeds.
- a subject requiring prompt refinement must carry the exact printable-ASCII candidate prompt and
  its SHA-256; a subject without that action must not carry a candidate prompt;
- route reclassification records `PYTHON_SVG` as a candidate for a later production-path benchmark.
  It does not change the released inventory route;
- global adapter activation is always `FORBIDDEN`.

## Transaction, concurrency, retry, and idempotency

The plan identity is derived from both pinned predecessor pointers and every per-subject strategy.
The plan hash covers the full payload including UTC authoring metadata. Byte-identical publication
is idempotent; a conflicting payload fails closed. A later publisher must resolve and validate both
predecessors before the Orchestrator commits one Artifact. No worker writes NAS.

## Failure and rollback

Missing, stale, unauthorized, wrong-schema, wrong-media, or hash-mismatched pointers fail closed.
Incomplete review coverage, duplicate subjects/cases/actions, inconsistent stability decisions,
prompt/hash drift, or any global activation request also fail closed. Since this plan changes no
runtime binding, rollback is simply to not consume it; predecessor evidence remains immutable.

## Simpler alternative rejected

A prose table would not bind the exact review and could be mistaken for production activation.
Editing the V1 inventory would collide with its incomplete identity body. A global boolean such as
`use_adapter` cannot represent the observed subject-dependent outcomes. One small immutable plan is
the simplest honest successor boundary.
