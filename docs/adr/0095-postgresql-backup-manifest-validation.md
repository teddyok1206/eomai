# ADR 0095: PostgreSQL backup manifest validation

Status: Accepted

## Context

EOM stores PostgreSQL custom-format dumps and small JSON manifests below the fixed NAS backup root.
The restore dry-run previously trusted a path after a shell `-f` check and compared only the hash
named by an untyped JSON object. It did not reject symlinks, hard links, a mismatched file name or
size, or unknown manifest fields. New backups also had no explicit contract identity. These gaps do
not imply that an existing dump is corrupt, but they make recovery evidence weaker than the
pointer-validation rules used by the application.

This decision covers the PostgreSQL dump and its manifest only. It does not claim that the NAS is
an independent backup failure domain, and it does not define backup or restore of the Artifact
store.

## Decision

1. New manifests use JSON Schema 2020-12 contract `postgres-backup-manifest/1.0` and the matching
   frozen Pydantic model.
2. The dump is the canonical backup payload. The manifest is a small immutable value object that
   binds a distinct backup ID, UTC creation time, database name, PostgreSQL version, dump format,
   exact file leaf, byte length, and SHA-256 digest.
3. Resolution is limited to direct children of `/mnt/nas/eom/backups/postgresql`. The root,
   manifest, and dump must resolve without symlinks; payload files must be regular, single-link
   files. Reads use `O_NOFOLLOW`, bounded manifest bytes, stable descriptor identity, and streaming
   hashing.
4. Historical six-field manifests remain readable only through an explicit strict legacy adapter.
   The adapter rejects extra or missing keys and materializes a typed V1 value after the exact dump
   has passed name, size, and hash checks. Historical bytes are not rewritten.
5. The backup writer renders canonical JSON through the typed contract. The restore dry-run runs
   the same validator before copying bytes into PostgreSQL.

## Access patterns and data structures

The dominant operation is an exact lookup of one dump/manifest pair followed by one sequential
hash pass. Direct-child path validation is O(1); hashing is O(n) time and O(1) memory. A frozen model
is sufficient because a manifest has no independent mutable lifecycle. No database table, cache,
queue, or registry is added.

## Transaction, retry, and failure behavior

Backup publication retains the existing `.incomplete` staging names and publishes the dump before
its manifest. Restore is refused unless the pair validates exactly. A retry revalidates the same
immutable bytes. Failed validation creates no restore database. The existing restore database is
disposable and removed by the owning script; production rows and Artifact bytes are never edited.

## Dependency direction and alternatives

The infrastructure script owns filesystem and Docker behavior. The typed contract module owns only
serialization and validation and imports no application service. Using shell string interpolation
or accepting any JSON object was simpler, but could not enforce schema parity or safe pointer
resolution. Introducing a backup service or copying the Artifact store was rejected because there
is only one current PostgreSQL use case and no verified independent NAS snapshot boundary.

## Remaining recovery boundary

A complete disaster-recovery claim still requires an operator-owned inventory of NAS snapshot or
replication policy, a consistent relationship between restored PostgreSQL pointers and Artifact
bytes, an isolated restore drill, and measured RTO/RPO. Until those facts exist,
`ARTIFACT_STORE_RECOVERY` and end-to-end RTO/RPO remain `NOT_VERIFIED`.
