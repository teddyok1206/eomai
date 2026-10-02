# ADR 0169: Database and Artifact-store recovery pair verification

## Status

Accepted for implementation on 2026-10-02.

## Decision

A PostgreSQL restore is not sufficient recovery evidence for EOM.  Reproducible state also depends
on immutable Artifact revision pointers and bytes.  A recovery drill therefore produces a typed,
self-hashed receipt that binds one validated database backup manifest to one immutable Artifact
snapshot identity.  Every drill compares the complete ordered database inventory
`(artifact_id, revision_id, manifest_sha256)` with the snapshot inventory in O(n) time.  It then
validates either a bounded deterministic sample of Artifact bytes or every Artifact byte in
explicit `FULL` mode; the receipt distinguishes these modes and reports both verified counts and a
bounded evidence sample.

The verifier is an operations adapter.  It may read only an explicitly disposable restored
database and an explicitly supplied read-only Artifact snapshot root.  It never writes NAS,
changes runtime activation, or repairs pointers.  Canonical Artifact identity remains the logical
Artifact ID, revision ID, schema/media metadata, manifest and content hashes; a filesystem path is
only a location.

## Access patterns and structures

Artifact revisions are selected with indexed ordered queries.  Revision IDs and member paths are
deduplicated with sets.  Each manifest member is looked up by key rather than repeated scans.  A
bounded deterministic byte sample keeps work O(n + s + m), where `n` is inventory size, `s` is the
selected revision count and `m` is their member count.  `FULL` mode is O(n + M), where `M` is every
member.  Full mode can be requested explicitly but is not the default operational smoke.

The receipt includes the exact backup identity/time/hash, snapshot identity/time/hash, equal
database and snapshot inventory hashes, verification mode and counts, bounded evidence revision
identities, and a canonical receipt SHA-256.  It contains no Artifact bytes, secrets, database URL,
or host paths.  A sampled receipt proves complete metadata identity plus sampled byte integrity; it
must not be represented as a complete byte-restore acceptance.

## Failure and retry

Missing targets, unsafe paths, symlinks, non-regular files, manifest metadata drift, size drift,
and SHA-256 mismatch fail closed.  Exact equality between restored and snapshotted manifests
protects the schema and media metadata carried by each manifest; the verifier does not invent a
new semantic validator for every historical Artifact type.  It performs no recovery substitution
and never chooses a latest revision.  A failed drill may be rerun after creating a new disposable
restore and snapshot; the failed receipt is not rewritten as success.

The simpler alternative—checking only `pg_restore` and row counts—was rejected because it can pass
while all restored Artifact pointers are dangling.
