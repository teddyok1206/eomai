# Legacy Source Inventory Phase 2 Design

Status: implementation design for the read-only inventory adapter. This phase does not authorize
scanning a real legacy root, Content Intake, NAS/DB mutation, or worker execution.

## Responsibility and boundary

The Catalog-owned adapter observes one operator-configured legacy root through a closed root alias
and emits a validated inventory manifest. It never imports or executes legacy code, never writes to
the observed root, and never turns an observation into canonical educational knowledge. A later
reviewed selection is the only bridge to Content Intake.

The repository-owned scanner policy defines relative scan scopes, classification rules,
exclusions, and capacity limits. A separate protected operator configuration maps a closed alias to
an absolute local root. Absolute paths remain configuration, not protocol data.

## Canonical source and identity

The legacy file remains the source during discovery. Its path is only a locator. An inventory entry
uses `(root alias, normalized relative path)` for a deterministic entry key and records the observed
content SHA-256 when the file is safely readable. The inventory is an immutable observation, not a
source Artifact and not a rights decision.

`legacy-source-inventory/1.0` remains byte-immutable. It included `observed_at` in its self-hash,
which cannot provide the Phase 2 idempotency rule for repeated identical observations. The additive
`legacy-source-inventory/2.0` therefore separates:

- `source_set_sha256`: stable hash of policy/root identity, ordered entries, and summary;
- `inventory_id`: deterministic identity derived from the source-set hash;
- `inventory_sha256`: stable domain hash excluding observation time;
- `observed_at`: audit metadata whose complete bytes are still protected by an eventual Artifact
  manifest hash.

No V1 byte or meaning is changed.

## Access patterns and data structures

The dominant operations are ordered directory traversal, classification lookup, membership,
collision detection, hashing, and immutable serialization.

- classification rules are indexed by root alias and evaluated over a small reviewed tuple;
- visited scan scopes and normalized/casefold paths use sets for expected `O(1)` membership;
- directory entries are sorted once per directory and the final entries once globally;
- eligible file bytes are read once, making scanning `O(n log n + total hashed bytes)` with `O(n)`
  manifest memory;
- duplicate content hashes do not collapse entries because path/provenance and rights may differ.

The initial 5,000-observation/4-GiB policy requires no DB index. If recurring inventories later need
pagination, that is a separate schema/DB design.

## Filesystem and trust model

The adapter opens the configured root and descendants directory-relative with `O_NOFOLLOW`. It
rejects root/directory symlinks, unsafe Unicode/control paths, casefold collisions, hard links,
special files, metadata changes during a read, signature/suffix disagreement, secrets detected in
the bounded prefix, and all capacity violations. Excluded secret/runtime paths are never opened as
content.

Only read descriptors are used against legacy roots. Result manifests are written only to an
explicit protected output boundary or Catalog staging. Logs and CLI summaries contain counts,
closed aliases, stable IDs/hashes, and stable error codes—never source content or absolute roots.

## Transaction, retry, and idempotency

Dry-run has no DB, NAS, service, or source mutation. Identical root identity, policy, and sorted
entries produce the same source-set, inventory ID, and inventory hash. Changed bytes or policy
produce a different identity. A future/optional manifest commit uses the source-set hash as its
idempotency key and delegates Artifact staging/commit to the existing Catalog/Orchestrator Artifact
boundary; it never copies source files.

A failed scan emits no partial manifest. There is no automatic retry. A file mutation, root
mutation, or capacity failure terminates the observation with a stable error code.

## Dependency direction

`eomctl` validates presentation input and calls the Catalog application service. The application
service owns scan orchestration and optional Artifact commit. The filesystem adapter owns only
root resolution and observation. Contract models and schemas contain no filesystem, SQLAlchemy,
NAS, or CLI dependency.

## Simpler alternative rejected

`Path.rglob()` plus suffix checks would be shorter but follows mutable path strings across a hostile
tree, cannot close symlink races, and makes exclusions and bounds implicit. Scanning every path and
subtracting known bad names would also inspect unrelated runtime/model state. The fd-relative,
allowlist-first scanner is the smallest implementation that preserves the required trust boundary.
