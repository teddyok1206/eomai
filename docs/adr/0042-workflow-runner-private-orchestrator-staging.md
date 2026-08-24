# ADR 0042: Workflow runner private orchestrator staging

## Status

Accepted.

## Responsibility and boundary

The dedicated `eom-workflow-runner` service owns orchestration, worker handoff preparation, and
temporary result/log staging. `/srv/eom/staging` remains the operator-owned root (`eom:eom:0750`)
and is not writable by the dedicated runner identity. The runner therefore uses
`/var/lib/eom-workflow-runner/orchestrator-staging`, owned by `eom-workflow-runner:eom` with mode
`0700`. This is temporary materialization only; canonical artifacts remain immutable revisions on
NAS with typed database pointers.

The dominant access pattern is constant-time creation of one exclusive child keyed by a validated
job ID, followed by bounded writes of worker capture and result material before immutable artifact
commit. Expected concurrency is bounded by configured worker slot capacity. Each job has a unique
database identity, so no shared scan or deduplication structure is required.

## Resolution and failure contract

The systemd unit binds `EOM_STAGING_ROOT` to the private path and makes the operator staging tree
inaccessible. Before any workflow command claim, readiness requires a real non-symlink directory,
the exact service owner/group, mode `0700`, and a bounded create/read/delete probe. Missing,
misowned, linked, wrongly moded, or unwritable staging fails with
`ORCHESTRATOR_STAGING_INVALID` without consuming a command or worker lease.

Job-local paths are temporary locations, never identity. Artifact registration continues to pin
logical artifact ID, immutable artifact revision ID, schema/media contract, and SHA-256. A failed
job is not retried automatically; its API idempotency and workflow history remain authoritative.

## Alternatives and dependency direction

Granting group write on `/srv/eom/staging` was rejected because it would collapse operator and
service trust boundaries. Returning the service to the interactive `eom` identity was rejected
because it would undo runtime isolation. A new staging abstraction was unnecessary: the existing
orchestrator `Settings.staging_root` interface already owns this adapter boundary. Systemd supplies
the runtime path, readiness validates it, and domain/contracts remain independent of filesystem
identity.
