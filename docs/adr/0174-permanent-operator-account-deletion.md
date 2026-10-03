# ADR 0174: Permanent Operator account deletion with historical tombstones

## Status

Accepted for implementation.

## Responsibility and boundary

The Identity service remains the sole owner of Operator deletion. The Application API exposes one
fresh-ADMIN command and Scientific Studio only presents that command. Deletion is permanent and is
not an alternate disable/enable state.

Historical workflow, Item, review, audit, and delivery records continue to point at the immutable
`operator_id`. Therefore the canonical `operators` row is retained as a non-login tombstone while
credential secret material, active roles, and sessions are destroyed or revoked. Default account lists and account
lookup endpoints exclude tombstones.

## Canonical source and identity model

`operators.operator_id` remains the immutable logical identity. `deleted_at`, `deleted_by`, and
`delete_reason` record the tombstone. Mutable username and display-name attributes are replaced by
an operator-ID-derived non-secret login name and the generic display name `삭제된 계정`. This frees
the old username without changing historical foreign keys.

The credential row is retained only as a foreign-key-compatible tombstone: its Argon2 hash is
irreversibly replaced by the non-hash marker `DELETED`, its algorithm becomes `deleted`, and lock
state is cleared. Password verification treats this marker as invalid. Active role assignments are
revoked, not erased, so role history remains append-only. Existing sessions are revoked; their
historical rows and API audit events are retained. Retaining this non-secret row also lets an older
compatible binary read historical Operators during a code rollback without crashing on a missing
one-to-one credential relation.

## Pointers and resolution checks

The command resolves an exact `operator_id` under a row lock and checks:

1. the caller is an ACTIVE ADMIN with `operator:delete`;
2. the target exists and is not already deleted;
3. the target is not the caller;
4. deletion does not remove the last ACTIVE ADMIN;
5. the HTTP `If-Match` resource version still matches.

Deleted Operators cannot be enabled, assigned roles, inspected through the account API, or used to
authenticate. No implicit latest or replacement account is selected.

## Access patterns and data structures

- Admin list: ordered indexed scan with `deleted_at IS NULL`; expected account count is hundreds to
  low thousands.
- Mutation: primary-key lookup and row lock, O(log n).
- Last-admin guard: existing indexed active-role count.
- Active roles and sessions: indexed `operator_id` updates.
- Audit: append-only per-Operator monotonic sequence.

`ix_operators_deleted` supports default live-account filtering. No large payload is stored.

## Transaction, concurrency, retry, and idempotency

One Identity transaction holds the identity advisory lock and target row lock, verifies the guard,
revokes sessions and active roles, destroys credential secret material, redacts login attributes, sets tombstone
fields, increments role/resource versions, and appends `OPERATOR_DELETED`.

The Application API uses its existing idempotency record and `If-Match` boundary. Replaying the same
idempotency key returns the original command response. A different request against an already
deleted target fails as not found. Competing delete/enable/role operations serialize on the row and
resource version.

## Dependency direction and adapter ownership

Scientific Studio -> Application API -> Identity application service -> Identity contracts/models.
PostgreSQL, HTTP, CSRF, browser confirmation, and session materialization remain adapter concerns.
The GUI does not reproduce last-admin or identity rules.

## Failure and rollback behavior

Self deletion and last-admin deletion fail with stable errors. A stale version fails before the
Identity transaction. Any transaction failure leaves credential material, roles, sessions, and identity
unchanged. A completed deletion is intentionally irreversible; operational rollback restores code,
not destroyed credential material or redacted usernames. A new account must be created when access
is needed again.

## Simpler alternatives rejected

Physical deletion is incompatible with the many `RESTRICT` foreign keys that preserve authorship
and audit history. Reusing `DISABLED` alone would allow re-enabling an account and retain password
material. Hiding rows only in the GUI would leave authentication and API access intact. A tombstone
plus credential-secret destruction is the smallest implementation that satisfies permanent removal without
corrupting immutable history. Deleting the credential row was also rejected because released code
expects the one-to-one row when projecting Operators; replacing the secret with a non-hash marker
preserves rollback readability without preserving an authentication secret.
