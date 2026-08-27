# ADR 0045: HWPX application Manager private staging

## Status

Accepted.

## Context

The HWPX application Manager materializes a bounded per-build workspace under
`/srv/eom/hwpx-workspaces`, then creates small sanitized logs and an Artifact commit staging tree.
The shared `/srv/eom/staging` directory is canonically owned by `eom:eom:0750`; the dedicated
`eom-hwpx-manager` identity may traverse it through its supplementary `eom` group but may not
write it.  Broadening the shared directory would give unrelated producers a wider write boundary.

The dominant operations are one key lookup by immutable job ID, append/write within that job's
private directory, and a single deterministic Artifact commit.  Expected scale is one bounded
directory per HWPX job.  No large binary payload is stored in PostgreSQL; the directory is only a
temporary materialization boundary.

## Decision

The systemd runner pins `EOM_STAGING_ROOT=/var/lib/eom-hwpx-api/staging`.  This path is below the
Manager-owned `StateDirectory`, is mode `0700`, and is not shared with workers or other Managers.
The runner creates and verifies that exact private root before claiming a queued build.  Missing,
symlinked, wrongly owned, or overly broad staging roots fail closed before a build state changes.

The HWPX Manager no longer receives write access to `/srv/eom/staging`.  Builder workspaces remain
separate group handoffs and the fixed builder remains unable to access NAS or Manager state.

## Failure and retry

A staging-readiness failure reports `HWPX_MANAGER_STAGING_UNAVAILABLE` and leaves queued builds
unclaimed.  Terminal builds are never retried automatically.  Application idempotency and the
immutable job ID continue to protect concurrent or repeated creation.

## Rejected alternative

Granting group write on `/srv/eom/staging` is simpler operationally but expands a shared mutable
boundary and makes ownership between producers ambiguous.  The dedicated StateDirectory is both
simpler to reason about and least privilege.
