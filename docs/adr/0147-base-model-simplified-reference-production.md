# ADR 0147: Base-model simplified-reference production route

## Status

Accepted for implementation on 2026-09-28 UTC.

## Responsibility and system boundary

The Catalog image use case may combine one pinned public-domain or CC0 morphology reference with
the approved local SSD-1B base model. The current production V1 route preserves the reference but
does not pin deterministic simplification or monochrome output. An actual Item canary therefore
produced one correctly composed trilobite whose photographic color and surface texture were not
suitable for a Korean assessment page. The evaluated LoRA adapters remain activation-forbidden, so
this decision must not manufacture a style-adapter release or silently reinterpret V1–V3.

Add provider binding `local-image-provider-binding/4.0` and reference request/receipt `4.0`. V4
uses the existing reviewed `local-image-reference-simplification/1.1`, the approved base-model
revision, and deterministic `ASSESSMENT_GRAYSCALE` output. It has no LoRA pointer. The two
team-lead instruction files and existing Content Pack bytes remain unchanged.

## Canonical source, revisions, and pointers

The canonical input chain is:

```text
visual-reference bundle revision
  -> exact normalized PNG member pointer and SHA-256
  -> V4 provider binding revision value and binding SHA-256
  -> V4 request SHA-256
  -> deterministic conditioning PNG and metrics
  -> generation/composite/V4 receipts
  -> immutable final stimulus Artifact Revision and SHA-256
```

Logical IDs, revisions, member paths, media types, schemas, and hashes remain distinct. Workspace
files are temporary materializations. Existing V1–V3 requests, receipts, workspaces, Items, and
Artifacts are never rewritten.

The source foreground ratio is retained as audit evidence and must exceed the non-empty minimum,
but its upper bound does not reject a dark photographed background. The configured foreground
maximum applies to the deterministic conditioning output that is actually passed to the model.
The conditioning foreground and border ratios must both remain within their pinned limits. This
keeps empty or still-cluttered conditioning fail-closed while allowing simplification to perform
its intended conversion of a valid dark source into a bounded light line-art reference.

## Access patterns and data structures

The route performs keyed immutable pointer lookup, one bounded 800×504 pixel simplification, one
GPU inference, and one bounded 800×500 grayscale pass. It is `O(W*H)` time and transient memory for
fixed canvases, with `O(1)` database pointer lookups through existing indexes. Typed frozen models
and manifests remain the authoritative structures; no table, index, queue, cache, or binary DB
column is added.

V4 runs through its own fixed `eom-image-reference-base-provider@` unit. Unlike the V2/V3 style
unit it has no style-adapter store argument or mount, while preserving the same private-network,
GPU-device, workspace, repository, NAS, and secret isolation boundaries.

## Transaction, concurrency, retry, and idempotency

Catalog owns request construction and temporary staging. The isolated provider has no database or
NAS access. The request hash includes the V4 binding hash and the exact simplification policy; the
fixed provider unit remains single-request idempotent. Catalog validates the V4 receipt, exact
conditioning output, final PNG, and all hashes before the existing artifact transaction commits.
The isolated provider canonicalizes generated pixels to RGB grayscale before hashing them into the
generation receipt; the compositor then adds only the deterministic black/transparent SVG overlay.
Missing, stale, unauthorized, or mismatched outputs fail closed.

Activating V4 affects only workflows started after the root-controlled binding replacement.
Already-started workflows retain their pinned provider snapshot. Rollback restores the previous
immutable V1 binding and restarts the workflow runner; it does not delete V4 artifacts or rewrite
history.

## Dependency direction and adapter ownership

JSON Schema 2020-12 and Pydantic contracts are defined before runtime behavior. Catalog implements
the application use case and stages validated inputs. The image-provider adapter owns Pillow and
Diffusers behavior. Workflow workers neither communicate with the provider nor write NAS.

## Simpler alternative

Changing the V1 provider implementation to grayscale new outputs is smaller, but a lost workspace
could then replay the same V1 request hash to different bytes. Merely adding stronger prompt text
already failed in the live canary. Activating an evaluation-only LoRA would violate its lifecycle
and global review decision. V4 is the smallest reproducible successor that closes the observed gap.
