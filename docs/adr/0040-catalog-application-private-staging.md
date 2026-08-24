# ADR 0040: Catalog application private staging

## Status

Accepted.

## Responsibility and boundary

Interactive Catalog administration, the workflow runner, and the long-running Catalog application
manager have different operating-system identities. Operator commands own
`/srv/eom/staging/catalog` as `eom:eom`; the workflow runner uses
`eom-workflow-runner:eom`, and the manager runs as `eom-catalog-manager:eom-api`. Artifact
publication needs temporary materialization, but no identity may repair or reuse another identity's
staging tree.

The workflow runner and Catalog application manager therefore own private staging roots at
`/var/lib/eom-workflow-runner/catalog-staging` and `/var/lib/eom-catalog-api/staging`. Their systemd
units create the root and three declared fixed children before startup, with owner/group inherited
from each service identity and exact mode `0750`. The operator staging root remains unchanged and is
explicitly inaccessible to both services.
Canonical artifact bytes continue to be committed only to `/mnt/nas/eom/artifacts`; staging copies
are temporary materialization, not identity.

## Canonical pointers and access patterns

Artifact identity remains logical artifact ID, immutable artifact revision ID, member path, schema
reference, media type, and SHA-256. Staging paths are never persisted as identity. Dominant access
is constant-time lookup of one fixed staging area followed by operation-local directories keyed by
validated job or content hashes. Existing typed manifests and database uniqueness constraints own
deduplication and idempotent replay.

## Transaction, concurrency, and failure

Each publication stages beneath the service-private root, commits an immutable NAS artifact, and
then records its pinned pointers in the existing database transaction sequence. Concurrent jobs use
distinct validated operation keys. Missing, symlinked, wrongly owned, wrongly grouped, or
wrongly-moded roots fail closed before materialization. Service restart recreates only the declared
empty directory structure and does not replay terminal jobs.

## Dependency direction and alternatives

The systemd unit is the infrastructure adapter that binds the existing `CatalogSettings` interface
to a service-owned path. Domain contracts remain unaware of Linux users and filesystem locations.
Changing the shared operator tree to the manager identity was rejected because it would break
operator tools and collapse separate trust boundaries. Relaxing the runtime ownership check or
granting broad write access was rejected because it would make staging provenance ambiguous. A new
staging framework was unnecessary; the existing fixed-root validation already enforces the required
contract once each runtime receives the correct root.
