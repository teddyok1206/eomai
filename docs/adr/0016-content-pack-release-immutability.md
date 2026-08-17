# ADR 0016: Content Pack Release Immutability

## Status

Accepted

## Decision

A released Content Pack payload is immutable in application code and PostgreSQL. Activation is a
separate environment-scoped pointer with one active release per pack key. Workflows pin a concrete
release ID and hash at creation.

## Consequences

Same key/version/hash import is idempotent. Same key/version with a different hash is rejected.
Deprecation and retirement are lifecycle transitions, not payload edits. Activation changes affect
new workflows only.
