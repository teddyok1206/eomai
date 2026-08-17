"""Workflow command and query DTOs."""

from typing import Literal

from pydantic import Field

from eom_api_contracts.common import ApiModel, OpaqueId, UtcDatetime


class WorkflowStartRequest(ApiModel):
    definition_key: str = Field(min_length=1, max_length=64)
    definition_version: str = Field(min_length=1, max_length=32)
    request_name: Literal["PLACEHOLDER_REQUEST"] = "PLACEHOLDER_REQUEST"
    image_mode: Literal["skip", "required"]
    pack_key: str | None = Field(default=None, max_length=64)
    environment: Literal["development", "test"] = "development"
    source_intake_batch_ids: tuple[str, ...] = Field(default=(), max_length=100)
    registry_mode: Literal["CREATE_ITEM", "REVISE_ITEM"] = "CREATE_ITEM"
    item_id: str | None = Field(default=None, max_length=128)
    base_revision_id: str | None = Field(default=None, max_length=128)


class WorkflowView(ApiModel):
    workflow_id: OpaqueId
    definition_key: str
    definition_version: str
    state: str
    stage: str
    current_step_key: str
    resource_version: int = Field(ge=1)
    rework_cycle_count: int = Field(ge=0)
    created_at: UtcDatetime
    updated_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    failure_code: str | None = None


class WorkflowActionRequest(ApiModel):
    reason: str | None = Field(default=None, max_length=2000)


class WorkflowStepView(ApiModel):
    step_run_id: OpaqueId
    workflow_id: OpaqueId
    step_key: str
    attempt: int = Field(ge=1)
    step_type: str
    worker_role: str | None = None
    state: str
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None
    error_code: str | None = None
