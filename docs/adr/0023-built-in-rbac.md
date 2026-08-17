# ADR 0023: Built-in RBAC

## Status

Accepted for Application API V0.

## Decision

Use immutable VIEWER, AUTHOR, REVIEWER, EDITOR, and ADMIN role keys with explicit stable permission
keys. Assignments are many-to-many append-only records revoked by timestamp. Permission checks are
deny-by-default dependencies declared for every protected operation.

## Consequences

Role behavior is testable as one matrix and an existing access token sees changes immediately.
Custom roles are deferred. A fixed PostgreSQL advisory lock and the application service protect the
last-active-ADMIN invariant across concurrent transactions.
