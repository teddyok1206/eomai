# ADR 0022: Opaque DB-backed Tokens

## Status

Accepted for Application API V0.

## Decision

Use random selector/verifier access and rotating refresh tokens. Store only selector and keyed HMAC
of verifier in PostgreSQL, relate tokens to a revocable session family, and resolve current Operator
and RBAC state on every request.

## Consequences

Disable, role change, logout, password change, and refresh reuse take effect immediately. Each
authenticated request requires indexed database reads. JWT and stateless permission claims are not
used because their revocation and staleness behavior does not meet the V0 invariants.
