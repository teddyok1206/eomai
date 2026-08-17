# Content Pack V0

Content Packs keep domain policy out of platform code. A pack source is validated authoring input;
the canonical runtime object is a released immutable bundle artifact revision pinned by workflows.

```mermaid
flowchart LR
    Intake[Accepted Intake] --> Source[Pack source]
    Source --> Compiler[Deterministic compiler]
    Compiler --> Bundle[Immutable .eompack artifact revision]
    Bundle --> Release[Content Pack Release]
    Release --> Activation[Environment activation]
    Activation --> Snapshot[Workflow pinned snapshot]
    Snapshot --> Profile[Profile and prompt template]
    Profile --> Prompt[Rendered prompt artifact]
```

## Design Record

1. **Boundary:** `eom_content_pack` owns lifecycle and restricted substitution. Filesystem and ZIP
   handling are adapters; `ContentPackService` owns provenance, transaction, release, and activation.
2. **Canonical source:** a released bundle artifact revision plus release row and canonical manifest.
3. **Entity/revision:** `content_packs` is logical identity; each semantic version is an immutable
   `content_pack_release`.
4. **Pointers:** release ID, artifact ID/revision, bundle/source/manifest hashes, profile and template
   hashes, schema references, and accepted Intake IDs.
5. **Access:** key/version import, release lookup, active environment lookup, profile key lookup, and
   ordered manifest iteration.
6. **Structures:** path and profile maps give expected O(1) lookup; sets enforce normalization and
   uniqueness; sorted tuples and ZIP entries provide stable output; DB partial unique index protects
   one active release.
7. **Complexity:** discovery and output ordering are O(n log n), hashing and bundle I/O are O(total
   source bytes), and metadata is O(n) space.
8. **Transactions:** filesystem compilation and artifact commit occur outside DB transactions.
   Release/event/file/profile finalization and activation replacement use locked aggregate rows.
9. **Dependencies:** CLI → application service → lifecycle/contracts; PostgreSQL, NAS, YAML, and ZIP
   are adapters. Workers receive staged rendered prompts and never read pack source.
10. **Retry/idempotency:** `(pack key, version, source hash)` and artifact idempotency keys return the
    same release. Same key/version with a different hash is a conflict. Activation replacement is
    atomic.
11. **Alternative:** a general Jinja/plugin engine is rejected. V0 supports only declared scalar
    dot-path substitution, which is sufficient for the four real worker profiles without code
    execution.

## Bundle

`.eompack` is a deterministic ZIP with normalized paths, fixed entry timestamps, stable ordering,
and `content-pack-manifest.json`. The manifest lists every source file's media type, size, role, and
SHA-256. Bundle hash and semantic source-tree hash remain separate.

## Release Rules

Only packs backed by accepted Intake batches can import. `RELEASED` payload columns are protected by
PostgreSQL trigger. Only released, non-deprecated packs can become active. A workflow resolves once
and pins the exact release rather than following later activation changes.
