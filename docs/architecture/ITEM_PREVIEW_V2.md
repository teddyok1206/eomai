# Completed Item Preview V2

Status: reviewed implementation design
Date: 2026-09-01 (UTC)

## Responsibility and boundary

Scientific Studio must render an immutable completed Item Revision in the same order as its
canonical `AssessmentItemContent`. Catalog remains the only component allowed to resolve artifact
storage. Application API authorizes delivery, and the Web BFF exposes only same-origin Studio URLs.
The browser, Web BFF, and Application API never receive a NAS path or storage URI.

```text
browser
  -> Studio BFF preview JSON / same-origin media URL
  -> Application API ITEM_READ boundary
  -> private Catalog Unix socket
  -> Catalog pointer validation and bounded media stream
  -> canonical Artifact Revision member
```

## Canonical source and revision model

The canonical source is one approved, explicitly requested Item Revision and its required
`ITEM_CONTENT` component. The JSON content is a small immutable value artifact. Image blocks keep
their existing logical Artifact ID, immutable Artifact Revision ID, member name, media type, and
SHA-256 pointer. Preview V2 is a derived read model and never becomes a second canonical copy.

Every media request uses `(item_revision_id, block_id)`. Catalog reloads the pinned content,
selects exactly one image block, and validates its complete artifact pointer. The client cannot
supply or override an artifact ID, revision ID, member path, hash, or media type.

## Access patterns and structures

- Body rendering is ordered iteration over at most 100 immutable blocks: an ordered tuple is the
  appropriate structure, with O(n) construction and rendering.
- Choice and statement explanation resolution use maps keyed by immutable IDs, avoiding repeated
  scans and making missing or duplicate references explicit.
- Media lookup is one bounded O(n) block lookup inside a single pinned content artifact. At the
  contract maximum of 100 blocks an additional persistent index would add complexity without a
  measured benefit.
- Media bytes are streamed in bounded chunks; they are not placed in JSON or PostgreSQL.

## Protocol and dependency direction

The private Catalog socket gains a separate, additive
`catalog-item-media-request/response@1.0` framing contract. It reuses the existing socket identity,
peer-credential check, and runtime directory; it does not create a parallel storage service.
Catalog owns file resolution and streaming. Application API owns authorization and HTTP response
headers. Web owns presentation only.

Preview JSON uses additive `item-preview@2.0`. Historical V1 schema bytes remain unchanged.
Preview blocks are a discriminated union matching the presentation-neutral canonical block types.
Image blocks contain only a same-origin delivery URL derived from immutable IDs.

## Transaction, concurrency, retry, and failure

Preview is read-only and opens no write transaction. Catalog validates the Item Revision,
component pointer, media Artifact and Artifact Revision lifecycle, safe member path, regular-file
type, size, media signature, and SHA-256 before sending the success header. It opens the final file
with no-follow semantics and rechecks metadata so replacement races fail closed. The API client
hashes the received stream end to end.

GET requests are naturally repeatable but are not a recovery mechanism for stale pointers.
Missing blocks, wrong media type, stale revisions, symlinks, path escapes, size changes, and hash
mismatches return stable errors. No request silently resolves a newer Item or Artifact Revision.

## Security and scale bounds

- Only authenticated users with `ITEM_READ` can fetch preview JSON or media.
- Only the fixed `eom-api` UID may use the private Catalog socket.
- Images are limited to PNG/JPEG and 16 MiB; browser responses use `nosniff`, authenticated
  `no-store` delivery, a declared length, and no content disposition or storage metadata.
- Rendering uses DOM construction and `textContent`; canonical text is never assigned to
  `innerHTML`.
- Equations remain canonical notation/source data. A deterministic, dependency-free presentation
  layer renders the safe supported equation token subset and always preserves an accessible source
  fallback; no external script or LLM endpoint is introduced.

## Simpler alternative rejected

Embedding image bytes as base64 in structured-content or preview JSON would be simpler to wire,
but it duplicates large payloads, defeats streaming and cache boundaries, inflates the private JSON
protocol, and weakens pointer-oriented resolution. Giving the browser an artifact path or NAS URI
would violate the storage boundary. The additive stream operation on the existing Catalog socket is
the smallest design that preserves current ownership and security invariants.
