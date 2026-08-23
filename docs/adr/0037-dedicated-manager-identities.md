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
storage attribute. The `eom-artifact-committers` group grants traversal and creation at the single
canonical NAS Artifact root. It does not replace Artifact authorization, lifecycle, schema, or hash
validation.

## Access patterns and structures

Service identity and group checks are constant-size keyed lookups through the host account database.
The workflow runner additionally needs five fixed worker handoff groups. Catalog and HWPX managers
share only the API socket group and the bounded staging/Artifact groups. No dynamic role registry,
recursive ACL walk, or per-request account mutation is introduced.

## Transaction and concurrency boundary

The deployment refuses active fixed worker/HWPX units, installs accounts and systemd/polkit sources,
then restarts only the three manager services. Database claims and Artifact commits retain their
existing transactions and idempotency keys. A service restart never retries a terminal build or
reinterprets a pinned revision.

## Dependency direction and adapters

System users, groups, polkit, systemd, and NAS directory modes remain infrastructure adapters. Domain
models and protocols do not import or encode Linux identities. Application clients validate the
fixed server socket UID as part of the local transport adapter.

## Failure and simpler alternative

Unknown accounts, extra privileged groups, unsafe metadata, active child units, socket owner drift,
or cross-manager polkit authorization fail closed. Keeping `User=eom` plus more sandbox directives
was rejected because systemd cannot subtract the operator account's inherited supplementary groups.
Dynamic users were rejected because polkit subjects and persistent NAS ownership require stable
identities.
