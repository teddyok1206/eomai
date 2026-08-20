# ADR 0028: Disposable Application API Integration Database

## Status

Accepted

## Decision

Destructive identity, concurrency, migration, and privilege tests run only in a uniquely named
disposable PostgreSQL database. A distinct owner performs migrations and fixture cleanup. A
distinct runtime role is reconciled with the production minimum-privilege plan and used for live
privilege probes. State and credentials live outside Git in a 0700 `/tmp` directory.

Preparation mirrors the production initdb prerequisite: it creates schema `app` owned by the
disposable migration owner, grants that owner `USAGE, CREATE`, and fixes its search path to
`app, public` before Alembic runs. Alembic owns objects inside the prepared schema; it does not own
creation of the deployment schema itself.

Preparation and cleanup are explicit root-only phases; tests are unprivileged. Cleanup requires
prefix, deterministic name relation, manifest, database owner, and PostgreSQL comment markers.
Production, template, and administrator identities are protected names.

## Consequences

The test suite no longer needs to accept a deployed database. Operators perform prepare, migrate,
reconcile, test, and cleanup in order. Failure may leave a marked disposable resource for
investigation, but cannot make cleanup target an unmarked or production database.
