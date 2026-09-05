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


class HwpxDeliveryProfile(ApiModel):
    renderer: Literal["eom-template", "content-team"]
    renderer_version: Literal["1.0.0"]
    document_profile: Literal[
        "eom-question-template-v1",
        "content-team-hwp-question-editor-v1",
    ]
    source_schema_ref: Literal[
        "eom.assessment.item-content/1.0",
        "eom.assessment.item-content/2.0",
    ]

    @model_validator(mode="after")
    def exact_renderer_profile(self) -> HwpxDeliveryProfile:
        expected = {
            "eom-template": ("eom-question-template-v1", "eom.assessment.item-content/1.0"),
            "content-team": (
                "content-team-hwp-question-editor-v1",
                "eom.assessment.item-content/2.0",
            ),
        }[self.renderer]
        if (self.document_profile, self.source_schema_ref) != expected:
            raise ValueError("HWPX delivery profile mixes incompatible renderer identities")
        return self


class HwpxCapabilityView(ApiModel):
    capability: Literal["hwpx"] = "hwpx"
    state: HwpxCapabilityState
    renderer: Literal["kordoc"] = "kordoc"
    renderer_version: Literal["4.9.0"] = "4.9.0"
    supports: HwpxSupports
    default_delivery_profile: Literal[
        "eom-question-template-v1", "content-team-hwp-question-editor-v1"
    ]
    delivery_profiles: tuple[HwpxDeliveryProfile, ...] = Field(min_length=1, max_length=8)
    manager_registered: bool
    detail_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")


class HwpxBuildOptions(ApiModel):
    include_explanation: Literal[True] = True
    require_native_equations: bool = False
    require_native_tables: bool = False
    document_preset: Literal["report"] = "report"
    document_profile: Literal[
        "kordoc-report",
        "item-revision-auto",
        "eom-question-template-v1",
        "content-team-hwp-question-editor-v1",
    ] = "kordoc-report"
    item_number: int = Field(default=1, ge=1, le=999)


class CreateHwpxBuildRequest(ApiModel):
    renderer: Literal["auto", "kordoc", "eom-template", "content-team"]
    options: HwpxBuildOptions

    @model_validator(mode="after")
    def renderer_profile_consistency(self) -> CreateHwpxBuildRequest:
        expected = {
            "auto": "item-revision-auto",
            "kordoc": "kordoc-report",
            "eom-template": "eom-question-template-v1",
            "content-team": "content-team-hwp-question-editor-v1",
        }[self.renderer]
        if self.options.document_profile != expected:
            raise ValueError("renderer and document profile must identify the same closed adapter")
        return self


class HwpxBuildView(ApiModel):
    build_id: OpaqueId
    item_id: OpaqueId
    item_revision_id: OpaqueId
    source_artifact_revision_id: OpaqueId
    source_sha256: Sha256
    renderer: Literal["kordoc", "eom-template", "content-team"]
    renderer_version: Literal["4.9.0", "1.0.0"]
    state: HwpxBuildState
    validation_state: HwpxValidationState
    native_equation_count: int | None = Field(default=None, ge=0, le=128)
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
