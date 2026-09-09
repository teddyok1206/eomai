"""Health, system, and immutable API release information DTOs."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator

from eom_api_contracts.common import ApiModel, UtcDatetime


class ApiReleaseBuildInfo(ApiModel):
    """Identity of the exact source snapshot embedded in an API wheel."""

    schema_version: Literal["api-release-build-info/1.0"]
    package_version: Annotated[
        str,
        Field(
            min_length=1,
            max_length=64,
            pattern=r"^[0-9A-Za-z][0-9A-Za-z._+!-]{0,63}$",
        ),
    ]
    source_commit: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    source_tree: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
    source_archive_sha256: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    build_timestamp_utc: UtcDatetime

    @field_validator("build_timestamp_utc", mode="before")
    @classmethod
    def require_explicit_utc_json_offset(cls, value: object) -> object:
        if not isinstance(value, (str, datetime)):
            raise ValueError("build timestamp must be a string or datetime")
        if isinstance(value, str) and not value.endswith(("Z", "+00:00")):
            raise ValueError("build timestamp must spell an explicit UTC offset")
        return value


class LiveStatus(ApiModel):
    status: Literal["LIVE"] = "LIVE"
    api_version: Literal["1"] = "1"
    timestamp: UtcDatetime


class ReadyStatus(ApiModel):
    status: Literal["READY", "NOT_READY"]


class Capabilities(ApiModel):
    metadata_queries: bool = True
    content_intake_decision: bool = False
    workflow_commands: bool = True
    operator_management: bool = True
    file_upload: bool = False
    binary_download: bool = False
    hwpx: bool = False
    websocket_events: bool = False


class SystemInfo(ApiModel):
    api_version: Literal["1"] = "1"
    build_version: str
    source_commit: str
    migration_revision: str
    capabilities: Capabilities
    server_time: UtcDatetime


class DoctorStatus(ApiModel):
    status: Literal["PASS", "FAIL"]
    config: bool
    database: bool
    migration: bool
    builtin_rbac: bool
    active_admin: bool
