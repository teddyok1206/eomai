"""Content Intake API DTOs."""

from typing import Literal

from pydantic import Field

from eom_api_contracts.common import ApiModel, ArtifactPointer, OpaqueId, UtcDatetime


class ContentIntakeSummary(ApiModel):
    intake_batch_id: OpaqueId
    batch_name: str
    state: str
    purpose: str
    received_by: str
    resource_version: int = Field(ge=1)
    created_at: UtcDatetime
    updated_at: UtcDatetime
    source_manifest: ArtifactPointer | None = None


class SourceFileView(ApiModel):
    source_file_id: OpaqueId
    filename: str
    media_type: str
    size: int = Field(ge=0)
    sha256: str
    artifact: ArtifactPointer
    declared_role: str


class IntakeDetail(ApiModel):
    intake: ContentIntakeSummary
    source_files: tuple[SourceFileView, ...]


class IntakeDecisionRequest(ApiModel):
    decision: Literal["ACCEPT", "ACCEPT_WITH_CHANGES", "REJECT", "SUPERSEDE"]
    proposal_key: str = Field(min_length=1, max_length=128)
    notes: str = Field(min_length=1, max_length=2000)
