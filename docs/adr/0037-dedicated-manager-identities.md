# ADR 0037: Dedicated manager service identities

## Status

Accepted.

## Responsibility and boundary

Long-running workflow, Catalog, and HWPX managers execute orchestration and Artifact commit use
cases. They are not interactive operator processes and must not inherit the `eom` account's sudo,
LXD, device, or desktop groups. Fixed workers remain separate and never receive manager groups.

## Canonical identity and pointers

The fixed identities are `eom-workflow-runner`, `eom-catalog-manager`, and `eom-hwpx-manager`.
Artifact identity remains logical ID, immutable revision ID, and SHA-256; an OS owner is only a
storage attribute. The canonical NAS is a CIFS mount with server-independent forced ownership. Its
reviewed mount contract is `eom:eom`, directory mode `0750`, file mode `0640`, and
`nosuid,nodev,noexec`. Catalog and HWPX managers receive the existing `eom` storage group; fixed
workers never do. Mount permissions do not replace Artifact authorization, lifecycle, schema, or
hash validation.

## Access patterns and structures

Service identity and group checks are constant-size keyed lookups through the host account database.
The workflow runner additionally needs five fixed worker handoff groups. Catalog and HWPX managers
share only the API socket group and the established `eom` storage group. No dynamic role registry,
recursive ACL walk, or per-request account mutation is introduced. The CIFS mount applies metadata
to the whole share, so systemd `ReadWritePaths` continues to bound each manager's writable subtree;
API, GUI, observability, HWPX builders, and fixed workers keep `/mnt/nas` inaccessible.

## Transaction and concurrency boundary

The deployment refuses active fixed worker/HWPX units, installs accounts and systemd/polkit sources,
then restarts only the three manager services. Database claims and Artifact commits retain their
existing transactions and idempotency keys. A service restart never retries a terminal build or
reinterprets a pinned revision.

## Dependency direction and adapters

System users, groups, polkit, systemd, and CIFS mount options remain infrastructure adapters. Domain
models and protocols do not import or encode Linux identities. Application clients validate the
fixed server socket UID as part of the local transport adapter. The mount hardener changes only the
single reviewed fstab entry, validates it before replacement, records a protected rollback copy,
and restores both fstab and service availability on failure.

## Failure and simpler alternative

Unknown accounts, extra privileged groups, a permissive or mismatched mount, active child units,
socket owner drift, or cross-manager polkit authorization fail closed. Relying on `chmod`/`chgrp`
was rejected because this CIFS mount uses `nounix,forceuid,forcegid`; creation calls cannot override
its presented metadata. A new Artifact-only group was also rejected because this share has one
mount-wide GID and would widen that group to unrelated NAS paths. Keeping `User=eom` plus more
sandbox directives was rejected because systemd cannot subtract the operator account's inherited
supplementary groups. Dynamic users were rejected because polkit subjects require stable identities.
