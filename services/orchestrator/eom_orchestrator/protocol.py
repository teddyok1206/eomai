"""Protocol bundle identity used by the database registry and doctor."""

from __future__ import annotations

from eom_identifiers import content_sha256
from eom_protocol.validation import SchemaName, load_schema

SCHEMA_NAMES: tuple[SchemaName, ...] = (
    "job-request",
    "worker-input",
    "worker-result",
    "artifact-manifest",
    "error-result",
)


def protocol_schema_hash() -> str:
    return content_sha256({name: load_schema(name) for name in SCHEMA_NAMES})
