"""Health and system information DTOs."""

from typing import Literal

from eom_api_contracts.common import ApiModel, UtcDatetime


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
