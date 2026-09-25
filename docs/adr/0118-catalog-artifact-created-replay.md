# ADR 0118: Exact replay of pre-commit Catalog artifact jobs

Status: Accepted

Date: 2026-09-25 UTC

## Context

`CatalogArtifactService.commit_file_set` creates an immutable Job before it stages and validates
artifact members. A source-read or expected-hash failure therefore correctly leaves a Job in
`CREATED`, with no Artifact Revision and no NAS commit. Until now, an exact idempotent replay found
that Job but rejected it as generically incomplete. The caller could neither reuse the immutable
identity nor safely create a replacement identity.

The dominant access patterns are an indexed lookup by unique idempotency key, one lookup by Job ID,
and an append-only transition sequence. Expected scale is one small Job row and one bounded file-set
manifest per call. Artifact bytes remain filesystem/NAS data and are never stored in PostgreSQL.

## Decision

An exact replay may resume only when all of the following hold:

- `submit_structured_job` resolves the same idempotency key and exact request hash;
- no Artifact Revision exists for the Job; and
- the Job is still exactly `CREATED`.

Each caller stages into a fresh per-attempt directory beneath the immutable Job staging directory.
After all sources and expected member hashes validate, the existing row-locked state transition from
`CREATED` to `VALIDATED` selects the only commit winner. Attempt staging is removed after success or
failure. A completed Artifact remains the canonical replay result.

Any Job at `VALIDATED` or later without its Artifact Revision remains fail-closed. Recovery after a
NAS commit, a `COMMITTING` interruption, or an ambiguous database commit is a different problem and
is not inferred by this change.

## Boundaries and invariants

- No JSON Schema, database schema, queue, worker protocol, or NAS layout changes.
- Logical Artifact ID, Artifact Revision ID, Job ID, and hashes remain separately pinned.
- The Job row and request hash are canonical for replay identity; attempt directories are temporary
  materializations only.
- Source validation precedes state advancement. A bad source cannot consume the sole transition.
- The transaction and row lock on the explicit state machine remain the concurrency boundary.
- Lookup is O(1) through the existing unique idempotency-key index; staging and hashing are O(total
  member bytes), which is unavoidable at the validation boundary.

## Alternatives

Creating a new Job after failure was rejected because it breaks idempotency and can duplicate
artifacts. Reusing one shared staging directory was rejected because concurrent exact replays can
overwrite each other. Automatically resuming every incomplete state was rejected because later
states may already have NAS or database side effects that require a separate recovery receipt.

## Verification

The disposable-PostgreSQL test creates a pre-commit hash failure, proves that the Job remains
`CREATED` with zero Artifact Revisions, rejects a different request on the same key, completes an
exact replay with the original Job/Artifact identities, and proves a second replay is idempotent.
It also proves that a `VALIDATED` Job without an Artifact remains blocked.
