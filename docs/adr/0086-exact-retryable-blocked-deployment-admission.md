# ADR 0086: Exact retryable-blocked deployment admission

## Status

Accepted for implementation.

## Responsibility and boundary

The privileged Application API release wrapper normally rejects every nonterminal mock-exam
checkpoint. That remains the default. A production defect can, however, leave one execution in a
retryable `BLOCKED` state whose supported continuation requires corrected application code. The
deployment boundary therefore admits one explicitly authorized recovery checkpoint without
classifying it as terminal or weakening admission for any other execution.

## Canonical identity and pointers

The immutable checkpoint revision is canonical; `current.json` is its validated materialization.
Recovery authorization consists only of the logical execution ID, immutable execution revision ID,
SHA-256 of the exact current checkpoint bytes, and its stable top-level failure code. The installed
API contract still validates the complete checkpoint before these pointers are compared. The
checkpoint must be `BLOCKED`, its top-level failure must be retryable, and every supplied pointer
must match. A terminal checkpoint, a different failure, byte drift, a missing execution, or a second
nonterminal execution fails closed.

## Access patterns, data structures, and scale

Admission performs one ordered directory scan over the bounded execution inventory and constant-time
comparisons for the single authorized execution. It hashes each candidate checkpoint once while its
descriptor identity is stable. Time is O(e + b), where `e` is the number of execution directories
and `b` is the authorized checkpoint size bounded at 2 MiB; temporary space is O(b). No database,
index, cache, binary Artifact, or new dependency is introduced.

## Transaction, concurrency, retry, and failure

Mock-exam checkpoints advance only through an explicit coordinator command; no autonomous service
writes them. The operator must keep that command boundary exclusive during deployment. The release
wrapper validates the same exact checkpoint before the build, immediately before wheel replacement,
and again after service health verification. Any observed revision, byte, state, or failure drift
aborts. Re-running with the same exact pointers is idempotent. Normal deployment and Workflow runner
hold/retirement behavior are unchanged, and this mode does not establish a persistent runner hold.

## Dependency direction and alternatives

The standalone deployment verifier owns filesystem resolution and imports only the installed API
contract after dropping to the `eom-api` account. The shell wrapper owns privileged installation and
passes typed scalar identities; neither reaches into coordinator internals or mutates checkpoints.
Editing `current.json`, moving its directory, manually installing wheels, treating all retryable
failures as terminal, or abandoning 25 completed Items would bypass immutable history or broaden the
exception. A general recovery framework is unnecessary; the exact four-pointer authorization is the
smallest auditable boundary for the present use case.
