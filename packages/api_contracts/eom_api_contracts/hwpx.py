"""Application-facing HWPX capability, build, and validation contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from eom_api_contracts.common import ApiModel, OpaqueId, Sha256, UtcDatetime


class HwpxCapabilityState(StrEnum):
    READY = "READY"
    PREPARED_NOT_DEPLOYED = "PREPARED_NOT_DEPLOYED"
    UNAVAILABLE = "UNAVAILABLE"
    DEGRADED = "DEGRADED"


class HwpxBuildState(StrEnum):
    REQUESTED = "REQUESTED"
    RUNNING = "RUNNING"
    VALIDATING = "VALIDATING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class HwpxValidationState(StrEnum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class HwpxSupports(ApiModel):
    native_equations: bool
    native_tables: bool


class HwpxCapabilityView(ApiModel):
    capability: Literal["hwpx"] = "hwpx"
    state: HwpxCapabilityState
    renderer: Literal["kordoc"] = "kordoc"
    renderer_version: Literal["4.9.0"] = "4.9.0"
    supports: HwpxSupports
    manager_registered: bool
    detail_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")


class HwpxBuildOptions(ApiModel):
    include_explanation: Literal[True] = True
    require_native_equations: bool = False
    require_native_tables: bool = False
    document_preset: Literal["report"] = "report"


class CreateHwpxBuildRequest(ApiModel):
    renderer: Literal["kordoc"]
    options: HwpxBuildOptions


class HwpxBuildView(ApiModel):
    build_id: OpaqueId
    item_id: OpaqueId
    item_revision_id: OpaqueId
    source_artifact_revision_id: OpaqueId
    source_sha256: Sha256
    renderer: Literal["kordoc"] = "kordoc"
    renderer_version: Literal["4.9.0"] = "4.9.0"
    state: HwpxBuildState
    validation_state: HwpxValidationState
    native_equation_count: int | None = Field(default=None, ge=0, le=32)
    native_table_count: int | None = Field(default=None, ge=0, le=20)
    output_artifact_id: OpaqueId | None = None
    output_artifact_revision_id: OpaqueId | None = None
    output_sha256: Sha256 | None = None
    download_available: bool
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,79}$")
    failure_detail_sanitized: str | None = Field(default=None, max_length=500)
    created_by_operator_id: OpaqueId
    created_at: UtcDatetime
    started_at: UtcDatetime | None = None
    completed_at: UtcDatetime | None = None
    resource_version: int = Field(ge=1)

    @model_validator(mode="after")
    def terminal_pointer_consistency(self) -> HwpxBuildView:
        output = (
            self.output_artifact_id,
            self.output_artifact_revision_id,
            self.output_sha256,
        )
        if self.download_available and (
            self.state is not HwpxBuildState.SUCCEEDED
            or self.validation_state is not HwpxValidationState.PASS
            or any(value is None for value in output)
        ):
            raise ValueError("download requires a validated successful immutable output")
        return self
