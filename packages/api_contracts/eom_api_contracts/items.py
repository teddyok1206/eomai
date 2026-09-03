"""Item Registry query DTOs."""

from typing import Literal

from eom_catalog_contracts import AssessmentItemContentContract
from pydantic import Field

from eom_api_contracts.common import ApiModel, ArtifactPointer, OpaqueId, UtcDatetime


class ItemView(ApiModel):
    item_id: OpaqueId
    human_reference_code: str | None = None
    lifecycle_state: str
    current_revision_id: OpaqueId | None = None
    resource_version: int = Field(ge=1)
    created_at: UtcDatetime


class ItemRevisionView(ApiModel):
    item_revision_id: OpaqueId
    item_id: OpaqueId
    revision_number: int = Field(ge=1)
    revision_state: str
    content_pack_release_id: OpaqueId
    workflow_id: OpaqueId
    item_type_key: str
    manifest: ArtifactPointer
    resource_version: int = Field(ge=1)
    created_at: UtcDatetime


class ItemComponentView(ApiModel):
    item_component_id: OpaqueId
    item_revision_id: OpaqueId
    component_type: str
    ordinal: int = Field(ge=0)
    logical_name: str
    required: bool
    artifact: ArtifactPointer


class ItemRelationshipView(ApiModel):
    item_relationship_id: OpaqueId
    source_item_id: OpaqueId
    target_item_id: OpaqueId
    relationship_type: str
    created_at: UtcDatetime


class ItemRetirementRequest(ApiModel):
    reason: str = Field(min_length=1, max_length=1000)


class StructuredItemContentImportRequest(ApiModel):
    """Explicitly reviewed import of one canonical content snapshot."""

    reviewed: Literal[True]
    review_reason: str = Field(min_length=10, max_length=2000)
    content: AssessmentItemContentContract
