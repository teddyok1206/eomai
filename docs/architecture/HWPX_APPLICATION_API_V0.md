# HWPX Application API V0

## Responsibility and boundary

The browser and Web GUI use only the Application API. The API authenticates, authorizes, validates,
and enqueues an immutable Item Revision build request. A separately deployed HWPX manager runner
claims that request, resolves the pinned source Artifact Revision, invokes the fixed Kordoc adapter
in the isolated `eom-hwpx` builder, validates the result, and commits one canonical Artifact
Revision. The builder has no database, NAS, API credential, or arbitrary-command interface.

## Canonical identity and pointers

`hwpx_application_builds` is the canonical application-facing build resource. It stores a build ID,
the immutable Item Revision, its selected Markdown component's logical Artifact ID and immutable
Artifact Revision ID, schema/media contract, and expected SHA-256. Output is represented only by a
logical Artifact ID, immutable Artifact Revision ID, and SHA-256. The output bytes remain in the
artifact store and are never copied into PostgreSQL.

Pointer resolution requires the Item Revision to be `APPROVED` and current, exactly one eligible
Markdown component, matching artifact/revision ownership, approval, media type, lifecycle, and
SHA-256. Download repeats artifact identity, revision, primary-file containment, regular-file,
non-symlink, size, and SHA-256 checks. Missing, stale, ambiguous, or mismatched pointers fail
explicitly; no implicit latest revision is substituted.

The accepted Application API sandbox remains unable to access `/mnt/nas`. Download authorization
therefore opens no artifact path in the API process. The API sends only a validated `build_id` over
a fixed private Unix socket to the HWPX manager. The manager verifies the peer UID, resolves and
hashes the canonical Artifact Revision, and streams a bounded response header plus bytes. The API
verifies the declared size and SHA-256 while proxying. Socket metadata and its closed JSON Schema
are part of capability readiness; storage paths never cross the protocol.

## Access patterns and structures

- build lookup and secure download: primary-key lookup by `build_id`, O(log n);
- Item Revision history: B-tree `(item_revision_id, created_at, build_id)`, O(log n + k);
- runner claim: partial FIFO index on `(created_at, build_id)` where state is `REQUESTED`;
- API idempotency: unique derived key, O(log n), with a request hash conflict check;
- renderer selection: a closed map keyed by `kordoc`, O(1);
- lifecycle: an explicit transition table, not nested conditionals.

The expected V0 scale is thousands to low millions of immutable build rows. Each row contains small
metadata only. HWPX bytes and long logs remain outside PostgreSQL.

## Transactions, concurrency, retry, and idempotency

Request validation and enqueue occur in one transaction. A runner claims one `REQUESTED` row using
`FOR UPDATE SKIP LOCKED` and commits `RUNNING` before rendering. Only the runner holding that claim
may write its terminal state. API idempotency and the build table's derived unique key make equal
replays return the same build; a different body with the same key is a conflict. V0 does not
automatically retry terminal failures. A stopped runner leaves an explicit non-terminal row for
operator diagnosis rather than silently reusing a PID, workspace, source, or output.

## Dependency direction

API and GUI depend on typed contracts and the HWPX application service. The application service
receives a read-only Item Revision resolver protocol and a renderer port; it does not construct or
import the Catalog implementation. The API and standalone runner composition roots inject the
Catalog application service, while the Kordoc service and filesystem/systemd adapter implement the
renderer port. Contracts and domain state do not import FastAPI, subprocess, filesystem,
SQLAlchemy session, or the Web GUI. The GUI never imports or invokes Kordoc.

The application runner stays non-root. A root-owned `2770` workspace root uses the private
`eom-hwpx` group, granted to the runner only by the systemd unit. Staged inputs are group-readable,
and the fixed builder unit writes group-readable outputs with `UMask=0007`. A start-only polkit
allowlist accepts only `eom-hwpx-kordoc@hwpxbuild_<32 hex>.service`; caller-controlled units,
commands, paths, and renderer arguments are absent. The legacy template renderer adapter remains
unchanged.

The runner also uses a dedicated `eom_hwpx_manager_runtime` PostgreSQL role. Its dominant database
operations are primary-key pointer reads, one FIFO `FOR UPDATE SKIP LOCKED` claim, append-only job
events, job state updates, and immutable Artifact/Artifact Revision insertion. The role therefore
has only `SELECT` on the pinned Item and artifact inputs, `SELECT`/`UPDATE` on
`hwpx_application_builds`, and the exact `SELECT`/`INSERT`/`UPDATE` set needed for Kordoc jobs and
artifact registration. It has no workflow command, Operator identity, API session, schema-create,
delete, truncate, database-create, or role-membership authority. Sharing the broader Application
API role was rejected because it both obscures ownership and still lacks the manager's artifact
commit permissions. The runner verifies its positive privilege matrix before opening the download
socket or claiming a build and fails closed if it differs.

## Failure and validation

Build failures expose only stable codes and sanitized detail. Machine validation requires a valid
HWPX ZIP, Kordoc validation success, deterministic output SHA-256, and exact native equation/table
counts. When a request requires a native structure, zero is never accepted. Capability is `READY`
only after the fixed installed builder reports Node 20+, Kordoc 4.9.0, offline mode, and manager
registration. The probe also verifies the root-owned fixed builder and runner units, their closed
execution directives, and the active/enabled manager runner without starting a build. The builder
checks the reviewed `package-lock.json` SHA-256 and installed Kordoc package identity before Node is
invoked. Absence is `PREPARED_NOT_DEPLOYED`; malformed or mismatched installed capability is
`DEGRADED`.

## Simpler alternative considered

Calling Kordoc synchronously from the API was rejected because the API identity must not gain the
manager's systemd, workspace, or artifact-commit authority. Adding Kordoc columns to the legacy POC
`hwpx_builds` table was also rejected: its required template and manual-Hancom semantics describe a
different resource and would require unsafe nullable reinterpretation of historical rows.
