# ADR 0186: Approved Pair-Only Temporary Login-ID Recovery

## Boundary and reason

The owner approved temporary login-ID passwords for exactly two existing accounts, with forced
change on the next login. This is a local administrative recovery use case, not a relaxed ordinary
password policy, HTTP endpoint or account role change. Existing emergency ADMIN recovery remains
unchanged. The new local use case also supports non-ADMIN targets without promoting their roles.

## Canonical source and pointers

Operator/credential/session rows and append-only identity events remain canonical. Resolve the two
named accounts through the supported authenticated administrator API, then pin their opaque
Operator IDs and original resource versions in an immutable one-use approval set, independent of
CLI inputs. Reject another pair or refreshed version pins before engine construction.
Never put login names, passwords or hashes into source,
commands, results, events or Slack. The temporary password is derived from the locked canonical
username, not supplied as an arbitrary string. Ordinary password changes still reject identity
equality; a specifically named temporary hashing method retains length/NUL/common-password limits.

## Access, concurrency and failure

Use the existing trusted non-root local `eom` authorizer, identity advisory lock, deterministic
Operator-ID lock order and unique credential lookup. The command contains exactly two distinct
version-pinned targets. Validate both ACTIVE states and versions before changing either account.
Hash both candidates before mutation. Rotate credential and Operator versions, clear login lockout,
force password change, revoke existing sessions and append redacted SYSTEM/CLI events in one
transaction. A stale version or successful replay fails without a second reset; an ambiguous
operation is inspected, never blindly resubmitted.

Operations are two indexed lookups plus set-based session revocation and append-only history,
O(s) for the two accounts' sessions and O(1) fixed-cohort storage. No new DB schema, queue,
dependency, runtime service or cache is required. The CLI owns OS/presentation authorization;
the identity application owns locking, version checks and transactions. Tests cover policy
isolation, authorization, exact cohort, stale/replay, disabled target, rollback, forced change,
session revocation and secret-free events. Production execution is an approved application use
case, never a mutating pytest run against production.

## Scope and removal

There is no automatic default reset for other accounts. The operation's pinned versions make
this approval one-use; no retry can reset an account again after success. Subsequent user password
changes follow the unchanged installed authentication path. Remove the local exception entrypoint
when this recovery need is retired; ordinary authentication does not depend on it. Direct SQL,
granting ADMIN to the targets or globally allowing username/password equality would bypass the
approved boundary and is rejected.
