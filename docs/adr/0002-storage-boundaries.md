# ADR 0002: Storage Boundaries

Status: Accepted

## Context

The server has local NVMe SSD and a CIFS NAS mount. PostgreSQL primary data needs low-latency local filesystem semantics. Artifacts need durable shared storage.

## Decision

- `/home/eom/EOM` is source.
- `/srv/eom` is local runtime state, jobs, staging, cache, workspaces, and Conda prefixes.
- `/mnt/nas/eom` is persistent artifact storage.
- PostgreSQL primary data stays on local SSD through a Docker named volume.
- NAS stores approved artifacts, HWPX, images, manifests, long logs, and DB backups.
- Workers cannot access NAS directly.
- The orchestrator stages locally, validates schema/hash, then commits artifacts to NAS.
- Logical ID, revision ID, and content hash are separate identifiers.

## Consequences

NAS outage handling belongs in orchestrator artifact-commit logic. PostgreSQL does not depend on NAS for online operation.
