"""Usage Ledger API DTOs."""

from pydantic import Field

from eom_api_contracts.common import ApiModel, OpaqueId, UtcDatetime


class UsagePlanView(ApiModel):
    usage_plan_id: OpaqueId
    item_id: OpaqueId
    preferred_item_revision_id: OpaqueId | None = None
    deliverable_id: OpaqueId
    deliverable_revision_id: OpaqueId | None = None
    planned_section: str
    planned_sequence: int = Field(ge=1)
    planned_points: str | None = None
    planned_role: str | None = None
    status: str
    resource_version: int = Field(ge=1)
    created_at: UtcDatetime


class UsageRecordView(ApiModel):
    usage_record_id: OpaqueId
    item_id: OpaqueId
    item_revision_id: OpaqueId
    deliverable_id: OpaqueId
    deliverable_revision_id: OpaqueId
    section: str
    sequence: int = Field(ge=1)
    page: int | None = Field(default=None, ge=1)
    points: str | None = None
    usage_role: str
    source_usage_plan_id: OpaqueId | None = None
    recorded_at: UtcDatetime


class CreateUsagePlanRequest(ApiModel):
    item_id: OpaqueId
    preferred_item_revision_id: OpaqueId | None = None
    deliverable_id: OpaqueId
    deliverable_revision_id: OpaqueId | None = None
    planned_section: str = Field(min_length=1, max_length=128)
    planned_sequence: int = Field(ge=1)
    planned_points: str | None = Field(default=None, max_length=16)
    planned_role: str | None = Field(default=None, max_length=64)


class FulfillUsagePlanRequest(ApiModel):
    page: int | None = Field(default=None, ge=1)
    usage_role: str = Field(min_length=1, max_length=64)
