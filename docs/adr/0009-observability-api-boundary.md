# ADR 0009: Observability API Boundary

Status: Accepted

## Context

A browser must not learn the storage schema or receive raw worker and artifact content. A future main
GUI may reuse stable observability data without depending on this temporary frontend.

## Decision

- Reserve `/observe/`, `/observe/assets/`, and `/observe/api/v1/` for this console.
- Keep `/api/v1/`, `/app/`, and `/admin/` unused for the future main GUI.
- Validate responses with strict Pydantic models and JSON Schema 2020-12.
- Return deterministic node, edge, and event ordering.
- Accept only bounded, typed filter parameters and fixed SQL statements.
- Disable OpenAPI in production and CORS entirely.
- Hide free-form content, full paths, payloads, credentials, prompts, and results.

## Consequences

Storage changes require an adapter change, not a browser change. Contract evolution requires a new
API/schema version. Removing the frontend does not remove the reusable projection contract.
