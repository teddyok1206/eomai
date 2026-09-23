# ADR 0107: Separate document-review domain manifests from the Artifact manifest

- Status: Accepted
- Date: 2026-09-23

## Context

The immutable file-set store reserves the root member name `manifest.json` for its own Artifact
manifest. Office-review projection and annotated-PDF producers nevertheless used that same name for
their domain manifests. Unit fakes accepted the collision, while the real `stage_file_set_artifact`
boundary correctly rejected it before NAS commit. An admitted Office source therefore remained
available, but its otherwise valid PDF/page projection failed with
`DOCUMENT_REVIEW_PROJECTION_FAILED`.

The released JSON Schemas already model member paths as bounded safe relative paths and do not pin
the conflicting root name. Existing Pydantic source-pointer models did add a stricter legacy check.
No successful Office V3 projection using the reserved name exists in production, but readers must
remain compatible with any previously serialized pointer.

## Decision

Document-review domain manifests use distinct, explicit member names:

```text
Office/PDF projection Artifact
    document-manifest.json       domain intake manifest
    source/original.pdf          derived review PDF
    pages/page-NNNN.png          ordered page projections
    manifest.json                platform-owned file-set manifest

Annotated-PDF Artifact
    annotation-manifest.json     domain annotation manifest
    result.json                  application result
    annotated/*.pdf              immutable annotated outputs
    manifest.json                platform-owned file-set manifest
```

The existing JSON Schema 2020-12 contracts remain byte-unchanged because both new names are already
valid under their authoritative safe-relative-path constraints. Pydantic pointer validation accepts
both the old `manifest.json` spelling and the new `document-manifest.json` spelling for backward
read compatibility. New producers emit only the non-reserved names. Artifact commit failures are
normalized to the existing retryable `CATALOG_ARTIFACT_COMMIT_FAILED` code instead of being hidden
by a generic projection error.

## Boundary, identity, and access pattern

Catalog application services own domain-manifest construction. The orchestrator Artifact adapter
continues to own the platform manifest and NAS commit. Workers receive only typed pointers and do
not write NAS. Canonical identity remains logical Artifact ID, immutable Artifact Revision ID,
member path, schema/media type, and SHA-256; a filesystem path is not identity.

Frequent operations are indexed Artifact/revision lookup followed by one keyed member lookup in the
stored manifest. Producers use dictionaries keyed by member path, giving `O(1)` construction lookup
and `O(n)` deterministic staging over the bounded member set. No DB schema, migration, queue, cache,
or new index is required. PostgreSQL continues to store only pointer metadata.

## Transactions, failure, retry, and compatibility

Source admission and projection commit remain separate bounded transactions. If projection staging
or commit fails, the already admitted source pointer is returned with a stable retryable error;
history is not rewritten. A byte-identical request reuses existing idempotency and immutable source
boundaries. Readers never substitute another revision or an implicit latest member.

Tests must exercise `stage_file_set_artifact`, not only permissive fake committers, so a future
producer cannot reintroduce any root `manifest.json` domain member. Existing response fixtures using
the legacy spelling remain parseable; new producer tests require the non-reserved spelling.

## Simpler alternative rejected

Allowing callers to overwrite the platform `manifest.json` would make one path represent two
different hashes and break Artifact verification. Renaming the platform manifest would affect every
Artifact reader. Creating a new wire version is unnecessary because the released JSON Schemas
already permit the correct member names and no field shape or meaning changes. The smallest safe fix
is to align producers with the existing storage invariant and keep backward-compatible readers.
