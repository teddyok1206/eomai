# ADR 0100: Workflow-start V2 for reviewed material briefs

- Status: Accepted
- Date: 2026-09-19 UTC

## Context

The public workflow-start application model accepts the reviewed content-team Item Brief V4 used
by `generic-item-development@1.10.0` through `1.12.0`.  The immutable JSON Schema
`eom://schemas/api/v1/workflow-start/1.0` predates that brief and is byte-pinned.  Consequently a
valid V4 request passed Pydantic validation while no published API JSON Schema could validate the
same request.

## Decision

Publish the additive successor `eom://schemas/api/v1/workflow-start/2.0`.  V2 accepts either an
unchanged V1 request or the closed V4 content-team start shape.  It reuses the existing typed
educational-retrieval and material-requirement schemas and references the immutable V1 production
occurrence and expected-resolution definitions.  V1 bytes remain unchanged.

The API application service remains the transaction and idempotency owner.  This change adds no
database state, queue, cache, worker communication, or storage copy.  It only restores the
schema-first contract for the already supported presentation DTO.

## Data and access patterns

The contract is an immutable, small JSON document.  Validation is one bounded traversal of the
request (`O(n)` time and schema/request space); identity lookup is by the schema `$id`.  The package
mirror is byte-identical to the canonical schema.  No index or persistence change is required.

## Failure and compatibility

Unknown properties, missing V4 material requirements, invalid hashes, and malformed pointers fail
closed.  Semantic cross-field checks remain in the typed Pydantic model.  Released V1 remains
available for historical clients, while new V4 requests validate against V2.  Deployment verifies
that both schema resources are present.

The simpler alternative—editing V1—was rejected because V1 is byte-pinned immutable history.
Relying only on generated OpenAPI/Pydantic was rejected because it would leave the explicit JSON
Schema 2020-12 contract incomplete.
