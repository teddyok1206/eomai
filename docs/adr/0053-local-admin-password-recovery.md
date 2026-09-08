# ADR 0053: Local Administrator Password Recovery

## Responsibility and boundary

The `eomctl operator emergency-reset-admin-password` use case recovers an existing active
Administrator when no fresh API credential remains. It is a local emergency operation, not a new
HTTP endpoint and not proof that a named human authenticated.

## Canonical source and revision model

PostgreSQL Operator, credential, session, role-assignment, and append-only Operator-event rows are
canonical. The logical Operator ID is preserved; only the credential version and Operator lock
version advance.

## Required pointers and checks

The CLI requires the target Operator ID twice and accepts a bounded owner-only password file. The
application command carries one validated target ID and a closed `ADMIN_CREDENTIAL_LOSS` reason
code; it cannot carry a free-form note that might contain a credential. The recovery use case calls
an injected authorization port rather than accepting an OS-principal string from the command. Its
only production adapter derives the real/effective UID, GID, and account name at call time and
requires the non-root local `eom` account. The CLI preflights that adapter before opening the
database or password file, and the service calls it again immediately before its transaction. The
API composition does not provide this adapter.
Resolution requires the exact target to exist, be ACTIVE, and hold an active ADMIN role. The
password is validated by the shared `PasswordService` and is never emitted or included in an event.

## Access patterns and data structures

The dominant operations are indexed primary-key lookup, the existing indexed active-role lookup,
one credential unique-key lookup, a set-based session update, and append-only event insertion. No
large payload, repeated scan, cache, or new persistent structure is introduced.

## Scale and complexity

Operator and credential resolution are O(1) indexed lookups; role lookup and session revocation are
O(r) and O(s) for that one Operator. Space is O(1) apart from one audit row. Expected `r` and `s`
are small, while the queries remain index-backed.

## Transaction and concurrency

The existing identity advisory lock serializes role membership. The target Operator and its single
credential are then locked `FOR UPDATE`. Credential replacement, failure-lock clearing, session
revocation, version increments, and the event commit in one transaction.

## Dependency direction and ownership

The eomctl adapter implements the narrow local-authorization port and validates the filesystem
presentation boundary. `LocalAdminPasswordRecoveryService` owns the use-case invariants and
transaction. The service depends on the port, while the CLI depends on the service; the service does
not import OS, filesystem, HTTP, or CLI code. Existing identity persistence adapters remain in the
identity service, matching the established `OperatorService` transaction boundary.

## Failure, retry, and idempotency

Unsafe files and non-`eom` execution fail before the service. Missing, disabled, or non-ADMIN
targets and password-policy failures roll back. A successful replay intentionally creates another
credential version, revokes any newly created sessions, and appends another audit event; operators
must inspect the prior result instead of retrying after ambiguous output.

## Secret lifecycle

The reset credential is temporary and forces the normal API password-change flow. The CLI accepts
it only through a same-descriptor validated, regular, single-link, invoking-user-owned mode-0600
file bounded to the password policy size. The caller removes the temporary materialization after
the command. All prior sessions are revoked before commit.

## Tests and operational evidence

Tests cover target and role gates, password policy, reset fields and versions, full session
revocation, closed secret-free audit payloads, OS-principal rejection, unsafe and changing file
identities, and the forced-change login sequence. Production use records only sanitized IDs,
counts, a closed reason code, version, OS principal/UID/GID, and UTC time.

## Simpler alternative rejected

Direct SQL would be shorter, but would bypass password policy, row locks, session revocation,
versioning, and append-only audit. Treating `--actor-id` as authentication is also insufficient:
the existing emergency CLI actor is a presentation value, whereas this recovery must honestly be
recorded as a local SYSTEM action followed by a real API password change.
