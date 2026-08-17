# Application API References

Checked on 2026-08-17. Only the linked specifications and project documentation were consulted;
their contents are not copied into this repository.

| Reference | Official source | Applied design | Deviation and reason |
| --- | --- | --- | --- |
| FastAPI security and metadata | <https://fastapi.tiangolo.com/tutorial/security/> and <https://fastapi.tiangolo.com/tutorial/metadata/> | Explicit HTTP Bearer security, dependency-based authorization, OpenAPI 3.1, disabled production docs | Opaque DB tokens are used instead of the tutorial OAuth2/JWT flow |
| FastAPI `HTTPBearer` | <https://fastapi.tiangolo.com/reference/security/> | Extract bearer credentials and declare an OpenAPI HTTP security scheme | Token payload is intentionally not a JWT and `bearerFormat` says `opaque` |
| Starlette middleware | <https://www.starlette.io/middleware/> | Trusted host enforcement and pure ASGI request/body/header middleware | CORS middleware is omitted because V0 CORS is disabled |
| Pydantic 2 models and JSON Schema | <https://docs.pydantic.dev/latest/concepts/models/> and <https://docs.pydantic.dev/latest/concepts/json_schema/> | Frozen strict DTOs, forbidden extra fields, generated JSON Schema | JSON Schema files are exported and validated as protocol artifacts |
| pwdlib | <https://frankie567.github.io/pwdlib/> and <https://frankie567.github.io/pwdlib/reference/pwdlib/> | `PasswordHash.recommended()` with Argon2, verification, and dummy verification | EOM adds explicit Unicode length, encoded byte, identity, NUL, and common-password checks |
| SQLAlchemy 2 Session | <https://docs.sqlalchemy.org/en/20/orm/session_basics.html> | One Session per request, explicit transaction ownership, 2.0 `select()` style | Domain services retain existing synchronous SQLAlchemy adapters |
| SQLAlchemy `with_for_update` | <https://docs.sqlalchemy.org/en/20/core/selectable.html> | Token/session and aggregate row locking | PostgreSQL advisory locks cover invariants spanning absent or multiple rows |
| PostgreSQL advisory locks | <https://www.postgresql.org/docs/18/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS> | Transaction locks for bootstrap and last-admin checks | Fixed application-defined keys are documented and tested |
| PostgreSQL privileges and GRANT | <https://www.postgresql.org/docs/18/ddl-priv.html> and <https://www.postgresql.org/docs/18/sql-grant.html> | Non-owner runtime role with explicit DML and sequence privileges | Migration owner remains separate because object ownership implies DDL rights |
| OpenAPI 3.1 | <https://spec.openapis.org/oas/v3.1.1.html> | Stable operation IDs, JSON Schema, explicit security requirements | Contract stays on 3.1 even if a newer OpenAPI minor exists, for client stability |
| RFC 9457 | <https://www.rfc-editor.org/rfc/rfc9457.html> | `application/problem+json`, stable type URI and extension error fields | Validation issues use a bounded `errors` extension |
| RFC 9110 | <https://www.rfc-editor.org/rfc/rfc9110.html> | Bearer challenge, content semantics, ETag/If-Match, 412 and 415 | V0 requires conditional mutation on selected mutable aggregates |
| RFC 6585 | <https://www.rfc-editor.org/rfc/rfc6585.html> | 428 for missing precondition and 429 with `Retry-After` | Applied to all V0 versioned mutation commands consistently |
| Uvicorn settings | <https://www.uvicorn.org/settings/> | Explicit `127.0.0.1:8765`, one worker, no source app-dir mapping | systemd owns process restart and runtime limits |

The release lock records the exact installed distributions. Method signatures are verified again
inside the isolated environment before implementation and deployment.

## Verified implementation versions

The development environment signatures and OpenAPI behavior were checked with FastAPI `0.141.1`,
Starlette `1.6.0`, Pydantic `2.13.4`, SQLAlchemy `2.0.52`, psycopg `3.3.4`, pwdlib `0.3.1`,
argon2-cffi `25.1.0`, HTTPX `0.28.1`, and Uvicorn `0.52.3`. The isolated runtime lock is the
authoritative deployment record.
