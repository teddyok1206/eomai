# Workflow Start Expected Resolution and Production Occurrence V1

## Responsibility and boundary

The Application API accepts one immutable expected Workflow resolution and, for coordinated
production, one occurrence identity. The command adapter validates the expectation against the
Workflow definition, Content Pack release, and execution-preset records before it creates a
Workflow. Workers receive only their existing role request and resolved execution plan; production
coordination identities are never prompt or result inputs.

The public HTTP Workflow-start route rejects production-occurrence fields. Only the mock-exam
production application service may submit them through the internal command boundary, after it has
reserved the globally deterministic execution identity and verified checkpoint ownership. This
keeps the generic public Workflow endpoint from forging or replaying a coordinated occurrence.

## Canonical source and revision model

The canonical sources are the stored Workflow definition row, immutable Content Pack release row,
and immutable execution-preset revision row. Their logical IDs/keys, revision IDs/versions, and
content hashes remain distinct. `production_request_id + workflow_call_id` identifies one planned
occurrence; it is not an artifact or content revision.

## Pointers and resolution checks

`workflow-expected-resolution/1.0` pins:

- Workflow definition key, semantic version, and SHA-256;
- Content Pack release ID, pack key, version, bundle SHA-256, and source-tree SHA-256;
- execution preset ID, revision ID, key, and content SHA-256.

Resolution checks target existence, owner/logical identity, released lifecycle, the exact active
pack activation for a fresh creation, compatible role protocol, every expected hash, and
pack/definition compatibility. An expected release is resolved by release ID and is never replaced
with another active release. The preset is resolved by revision ID and is never replaced with the
logical preset's current revision. Exact replay resolves the stored Workflow receipt first and does
not reapply mutable activation checks.

## Access patterns and structures

Definition `(key, version)`, release ID, preset ID, and preset revision ID are indexed or primary-key
lookups, so resolution is O(1) index work plus the bounded profile lookup. Workflow replay remains an
indexed idempotency-key/request-hash lookup. Immutable typed value objects are used instead of an
unstructured resolution dictionary.

## Transaction and concurrency boundary

The command adapter revalidates all expected pointers in the same database transaction that binds
the Content Pack snapshot and creates the Workflow. Knowledge evidence may require an earlier
external call, so the exact preset and definition are checked both before that call and again in the
creation transaction. The accepted resolution written to Workflow runtime context is assembled from
the records observed in that transaction.

Before the coordinator starts its first item, `DatabaseGenerationBlockResolver` resolves the current
admitted definition, exact active pack activation/release, and current released preset with one
read-only joined database statement. The resulting pointer is then the expected resolution for all
25 occurrence-specific starts.

## Retry and idempotency

The business fingerprint includes the immutable request, expected resolution, and production
occurrence. Reusing an idempotency key with different pins or occurrence fails. Replaying the same
request returns the same Workflow even if mutable Content Pack activation or preset-current pointers
have since moved. A different production request or Workflow call creates fresh work while duplicate
submissions of the same occurrence converge.

## Dependency direction and adapter ownership

JSON Schema and Pydantic contracts define the protocol. Workflow domain models own fingerprint
inputs and worker-input exclusion. The Application API command adapter owns transaction orchestration;
the Catalog adapter owns exact Content Pack binding; the query adapter owns the pointer-only accepted
resolution projection.

## Failure behavior

Missing, stale, lifecycle-invalid, owner-mismatched, or hash-mismatched pointers fail with stable
conflict errors before Workflow creation. No fallback to latest is allowed when an expected
resolution is present. A corrupt accepted-resolution runtime snapshot fails closed when queried.

## Scale and alternatives

The expected production scale is tens of starts per exam and many immutable historical Workflows.
The request adds only small constant-size JSON values. Storing only mutable keys and resolving latest
at each retry was simpler, but cannot reproduce a 25-item run or distinguish a new run from a retry,
so it is insufficient.
