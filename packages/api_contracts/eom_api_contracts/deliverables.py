"""Deliverable API DTOs."""

from typing import Literal

from pydantic import Field

from eom_api_contracts.common import ApiModel, OpaqueId, UtcDatetime


class DeliverableView(ApiModel):
    deliverable_id: OpaqueId
    deliverable_key: str
    deliverable_type: str
    title: str
    edition: str
    lifecycle_state: str
    deliverable_revision_id: OpaqueId | None = None
    revision_number: int | None = Field(default=None, ge=1)
    created_at: UtcDatetime


class CreateDeliverableRequest(ApiModel):
    deliverable_key: str = Field(min_length=1, max_length=128)
    deliverable_type: Literal["MOCK_EXAM", "TEXTBOOK", "WEEKLY", "OTHER"]
    title: str = Field(min_length=1, max_length=256)
    edition: str = Field(min_length=1, max_length=64)
