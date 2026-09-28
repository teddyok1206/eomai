# ADR 0143: V1 reference-conditioned production Pack

## Status

Accepted for implementation on 2026-09-28.

## Context

The live local-image binding is `local-image-provider-binding/1.0`.  The image provider and image
contracts already support `local-image-reference-conditioned-composite-request/1.0` and its typed
receipt, but the Catalog production use case invokes that path only for V2/V3 bindings.  With a V1
binding it acquires a visual reference and then calls the unconditioned compositor.  A production
canary therefore retained the reviewed monochrome style but mirrored a right-facing car to the
left.  The committed receipt correctly proved that no reference was consumed.

This decision does not alter the two team-lead guidance files, released Pack bytes, provider
binding, model weights, or existing Item revisions.

## Decision

Add immutable Content Pack `generated-knowledge-item/1.20.3`.  Only workflows pinned to that Pack
may route a V1 local-image binding through the already released V1 reference-conditioned request
and receipt.  Earlier Packs retain their exact behavior.

The Catalog application remains the owner of the use case.  It resolves one typed visual-reference
pointer through the existing orchestrator publication receipt, validates its immutable bytes, and
temporarily materializes those bytes into the provider workspace.  The worker does not receive a
filesystem path and does not write to NAS.  The provider returns a typed receipt; Catalog validates
the receipt and commits the final immutable artifact and receipt through the existing artifact
service.

The new Pack also selects prompt policy `ASSESSMENT_REFERENCE_COMPOSITION_V3`.  It preserves the
minimal line-art policy and derives an explicit orientation lock only when the bounded English
subject contains `facing right` or `facing left`.  Exact labels and scientific geometry continue to
belong to the deterministic SVG overlay.

## Canonical source and pointer model

The canonical reference remains:

```text
visual-reference bundle revision
  -> immutable artifact member pointer
  -> schema/media/size/SHA-256
  -> exact bytes staged for one provider request
```

The output remains:

```text
generated stimulus logical artifact
  -> immutable artifact revision
  -> PNG/SVG/raster/reference-conditioned receipt members
  -> member hashes
```

Filesystem paths are temporary materialization locations, not identity.  The idempotency key binds
the workflow, image result revision, visual ordinal, drawing hash, provider binding hash, and exact
reference-conditioned request hash.

## Access patterns and data structures

The hot path performs one keyed receipt lookup per IMAGE ordinal, one bounded pointer resolution,
and one typed manifest commit.  Existing indexed identifiers and maps are reused.  Runtime work is
O(v) time and O(v) bounded workspace space for `v` IMAGE slots; current contracts bound `v` to the
small authored visual list.  No new table, index, queue, cache, or repeated list scan is introduced.

## Transactions, concurrency, retry, and failure

Provider request identity is content-addressed and its fixed unit is idempotent.  A retry with the
same pinned inputs resolves to the same request hash.  Missing, stale, unauthorized, wrong-schema,
wrong-media, wrong-size, or wrong-hash references fail before provider execution.  A missing or
invalid conditioned receipt fails before artifact commit.  Catalog's existing artifact transaction
and uniqueness boundary remain authoritative.

Rollback is activation of Pack 1.20.2 for new workflows.  Existing 1.20.3 workflows retain their
pinned Pack and request identity; their history is not rewritten.

## Alternatives

Prompt-only direction wording is insufficient because the previous canary proved that an
unconditioned model can mirror composition even when the subject says `facing right`.  Moving the
live binding to V2/V3 would widen deployment scope to style-adapter releases and is unnecessary for
the immediate invariant.  A new protocol is also unnecessary: the required V1 request and receipt
schemas, validation, provider implementation, and fixed unit already exist.
