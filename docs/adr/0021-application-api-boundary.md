# ADR 0021: Versioned Application API Boundary

Status: Accepted

The future desktop GUI depends only on `http://127.0.0.1:8765/api/v1`, exported OpenAPI 3.1,
request/response schemas, error codes, resource versions, cursors, permissions, and idempotency
keys. PostgreSQL tables, SQLAlchemy classes, NAS paths, workers, migrations, and internal package
paths are not client contracts.

FastAPI is the HTTP adapter. Pydantic models in `eom_api_contracts` are the stable public values.
Existing application services own commands and invariants; SQLAlchemy query projection is isolated
in an infrastructure adapter. No frontend or file transfer endpoint is included in V0.

Direct GUI database access was simpler initially but would permanently couple client releases to
storage and privilege details. A versioned adapter provides a narrower and testable dependency.
