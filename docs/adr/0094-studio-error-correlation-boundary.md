# ADR 0094: Scientific Studio error correlation boundary

Date: 2026-09-15

Status: Accepted for implementation

## Responsibility and boundary

Scientific Studio owns the browser-facing request boundary. Application API errors are mapped to a
stable, sanitized Studio error code, but the user also needs one bounded inquiry identifier that an
administrator can correlate with the exact BFF request log. The browser must not receive upstream
tokens, payloads, stack traces, filesystem paths, prompts, Item content, or internal response bodies.

The canonical wire value is `studio-problem/1.0`, defined first by JSON Schema 2020-12 and mirrored
by the frozen `StudioProblem` Pydantic model. It contains only a stable error code, a fixed sanitized
message, and one server-generated request ID.

## Identity and access pattern

The request ID is an ephemeral correlation value, not a Workflow, Job, Item, Artifact, revision, or
idempotency identity. One BFF request creates one 96-bit random `webreq_` value. The same value is
stored in request state, written to the bounded request-completion log, returned in the
`X-Request-ID` header, and included in any typed Studio problem body. No derived value is persisted.

The dominant operation is an O(1) lookup from request state. The browser validates the fixed ID
shape and displays it only when a request fails. Routine views continue to hide technical IDs.

## Transaction, failure, and retry

The correlation value neither authorizes nor retries an operation. A timeout remains an unknown
outcome and follows the owning API idempotency contract. If no valid Studio request ID is available,
the browser shows the stable error code without inventing an ID. A body/header mismatch is a server
contract failure covered by tests; the UI uses only a value matching the closed `webreq_` shape.

## Dependency direction and alternatives

The FastAPI boundary creates the ID and materializes the typed problem. Presentation JavaScript
renders the safe fields. Domain, Workflow, Catalog, and storage layers do not depend on this Web
contract. Reusing upstream request IDs would couple browser support to private API topology; creating
a second ID inside each exception handler breaks correlation with the middleware log. One BFF-owned
ID per request is the smallest sufficient design.
